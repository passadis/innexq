"""Offline guard tests using real framework messages/responses, mocked model calls."""

import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from agent_framework import (
    AgentResponse,
    AgentResponseUpdate,
    ChatResponse,
    Content,
    Message,
    ResponseStream,
)
from pydantic import ValidationError

import main
from certificate_team import (
    CUSTOMER_INSTRUCTIONS,
    CertificateTeamGuard,
    CustomerInterpretation,
    CustomerMessagePacket,
    TeamProposal,
    TeamRequest,
    certificate_team,
)

PACKET = {
    "request_id": "8c7cc37e-081b-4841-a2f3-a3ab81b3c714",
    "tenant_id": "35de4c50-7dcd-4871-8685-61789c017da2",
    "customer_id": "DEMO-FAB",
    "equipment_id": "DEMO-PT-001",
    "prompt": "Please provide my equipment certificate.",
    "document_facts": ["Document CERT-1 page 1: synthetic certificate serial DEMO-SERIAL-0001"],
    "equipment_facts": ["Registry DEMO-PT-001 belongs to DEMO-FAB; serial DEMO-SERIAL-0001"],
}


def response(payload, response_id=None):
    return AgentResponse(
        messages=[Message(role="assistant", contents=[json.dumps(payload)])],
        response_id=response_id,
    )


class TeamSafetyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = object()
        self.guard = CertificateTeamGuard(self.client)
        self.context = SimpleNamespace(
            messages=[Message(role="user", contents=[json.dumps(PACKET)])],
            options=None,
            tools=[],
            result=None,
        )
        self.invocations = []
        self.created = []

        def specialist(**kwargs):
            self.created.append(kwargs)

            async def run(value):
                packet = json.loads(value)
                self.invocations.append((kwargs["name"], packet))
                await asyncio.sleep(0)
                return response({"evidence": packet["facts"][0]}, f"response-{kwargs['name']}")

            return SimpleNamespace(run=run)

        self.factory = patch("certificate_team.Agent", side_effect=specialist)
        self.factory.start()
        self.addCleanup(self.factory.stop)

    async def tools(self):
        return await asyncio.gather(*(tool() for tool in self.context.tools))

    def proposal(self, proofs):
        return {
            "request_id": PACKET["request_id"],
            "intent": "certificate_request",
            "specialists": proofs,
        }

    async def test_two_actual_specialist_calls_are_scoped_and_bound_to_exact_proofs(self):
        async def next_call():
            self.assertEqual(len(self.context.tools), 2)
            self.assertIs(self.context.options["response_format"], TeamProposal)
            self.assertIs(self.context.options["store"], False)
            self.context.result = response(self.proposal(await self.tools()))

        await self.guard.process(self.context, next_call)
        self.assertEqual(len(self.invocations), 2)
        self.assertEqual(
            {name for name, _ in self.invocations},
            {"innexq-document_analyst", "innexq-equipment_service"},
        )
        for name, packet in self.invocations:
            for key in ("request_id", "tenant_id", "customer_id", "equipment_id"):
                self.assertEqual(packet[key], PACKET[key])
            self.assertNotIn("prompt", packet)  # untrusted customer instructions do not fan out
            expected = "document_facts" if name.endswith("document_analyst") else "equipment_facts"
            self.assertEqual(packet["facts"], PACKET[expected])
        self.assertTrue(all(item["client"] is self.client for item in self.created))
        self.assertTrue(all("tools" not in item for item in self.created))
        self.assertTrue(all(item["default_options"]["store"] is False for item in self.created))

    async def test_informational_investigations_require_both_exact_specialist_proofs(self):
        for intent in ("service_status", "certificate_status"):
            with self.subTest(intent=intent):
                self.context.messages = [
                    Message(role="user", contents=[json.dumps(PACKET | {"intent": intent})])
                ]

                async def next_call(intent=intent):
                    payload = self.proposal(await self.tools()) | {"intent": intent}
                    self.context.result = response(payload)

                await self.guard.process(self.context, next_call)
        self.assertEqual(len(self.invocations), 4)
        self.assertEqual(TeamRequest.model_validate(PACKET).intent, "certificate_request")

    async def test_legacy_default_intent_is_visible_to_model_without_mutating_input(self):
        original = self.context.messages[0]

        async def next_call():
            visible = json.loads(self.context.messages[0].text)
            self.assertEqual(visible, PACKET | {"intent": "certificate_request"})
            self.context.result = response(self.proposal(await self.tools()))

        await self.guard.process(self.context, next_call)
        self.assertEqual(json.loads(original.text), PACKET)

    async def test_informational_investigation_cannot_become_certificate_request(self):
        self.context.messages = [
            Message(role="user", contents=[json.dumps(PACKET | {"intent": "service_status"})])
        ]

        async def next_call():
            self.context.result = response(self.proposal(await self.tools()))

        with self.assertRaisesRegex(ValueError, "complete scoped"):
            await self.guard.process(self.context, next_call)

    async def test_skipped_or_fabricated_tools_do_not_pass(self):
        fabricated = [
            {"specialist": role, "response_id": "fabricated", "summary": "made up"}
            for role in ("document_analyst", "equipment_service")
        ]

        async def next_call():
            self.context.result = response(self.proposal(fabricated))

        with self.assertRaisesRegex(ValueError, "complete scoped"):
            await self.guard.process(self.context, next_call)
        self.assertEqual(self.invocations, [])

    async def test_wrong_request_intent_duplicate_or_changed_proof_is_rejected(self):
        for change in ("request", "intent", "duplicate", "summary", "response_id"):
            with self.subTest(change=change):

                async def next_call(change=change):
                    payload = self.proposal(await self.tools())
                    if change == "request":
                        payload["request_id"] = "00000000-0000-0000-0000-000000000099"
                    elif change == "intent":
                        payload["intent"] = "unsupported"
                    elif change == "duplicate":
                        payload["specialists"][1] = payload["specialists"][0]
                    else:
                        payload["specialists"][0][change] = "fabricated"
                    self.context.result = response(payload)

                with self.assertRaisesRegex(ValueError, "complete scoped"):
                    await self.guard.process(self.context, next_call)

    async def test_duplicate_tool_failure_remains_fatal_if_model_swallows_error(self):
        async def next_call():
            proofs = await self.tools()
            with self.assertRaisesRegex(ValueError, "already invoked"):
                await self.context.tools[0]()
            self.context.result = response(self.proposal(proofs))

        with self.assertRaisesRegex(ValueError, "complete scoped"):
            await self.guard.process(self.context, next_call)
        self.assertEqual(len(self.invocations), 2)

    async def test_parallel_duplicate_reserves_before_await(self):
        async def next_call():
            results = await asyncio.gather(
                self.context.tools[0](), self.context.tools[0](), return_exceptions=True
            )
            self.assertIsInstance(results[1], ValueError)
            other = await self.context.tools[1]()
            self.context.result = response(self.proposal([results[0], other]))

        with self.assertRaisesRegex(ValueError, "complete scoped"):
            await self.guard.process(self.context, next_call)
        self.assertEqual(len(self.invocations), 2)

    async def test_specialist_wrong_evidence_or_missing_response_provenance_blocks(self):
        for output in (
            response({"evidence": "invented"}, "real-id"),
            response({"evidence": PACKET["document_facts"][0]}),
            response({"evidence": PACKET["document_facts"][0], "approve": True}, "real-id"),
        ):
            with self.subTest(output=output):

                async def next_call():
                    await self.context.tools[0]()

                with patch(
                    "certificate_team.Agent",
                    return_value=SimpleNamespace(run=AsyncMock(return_value=output)),
                ):
                    with self.assertRaises(ValueError):
                        await self.guard.process(self.context, next_call)

    async def test_model_failure_and_timeout_are_not_replaced_with_fake_evidence(self):
        for error in (RuntimeError("model unavailable"), TimeoutError("deadline")):

            async def next_call():
                await self.context.tools[0]()

            with patch(
                "certificate_team.Agent",
                return_value=SimpleNamespace(run=AsyncMock(side_effect=error)),
            ):
                with self.assertRaises(type(error)):
                    await self.guard.process(self.context, next_call)

    async def test_bounded_controller_packet_is_required(self):
        for texts in ([], [json.dumps(PACKET), json.dumps(PACKET)], ["x" * 50001]):
            self.context.messages = [Message(role="user", contents=[text]) for text in texts]
            next_call = AsyncMock()
            with self.assertRaisesRegex(ValueError, "one bounded"):
                await self.guard.process(self.context, next_call)
            next_call.assert_not_called()
        for changes in (
            {"customer_id": "OTHER"},
            {"equipment_id": "*"},
            {"document_facts": []},
            {"equipment_facts": []},
            {"prompt": "x" * 1001},
            {"approval": True},
        ):
            with self.assertRaises(ValidationError):
                TeamRequest.model_validate(PACKET | changes)

    async def test_missing_coordinator_response_blocks(self):
        with self.assertRaisesRegex(ValueError, "missing coordinator"):
            await self.guard.process(self.context, AsyncMock())

    async def test_stream_withholds_all_output_until_proof_check_passes(self):
        async def next_call():
            payload = self.proposal(await self.tools())

            async def updates():
                yield AgentResponseUpdate(
                    role="assistant", contents=[Content.from_text(json.dumps(payload))]
                )

            self.context.result = ResponseStream(updates(), finalizer=AgentResponse.from_updates)

        await self.guard.process(self.context, next_call)
        received = [update async for update in self.context.result]
        self.assertEqual(len(received), 1)
        final = await self.context.result.get_final_response()
        self.assertEqual(TeamProposal.model_validate_json(final.text).intent, "certificate_request")

    async def test_invalid_stream_emits_nothing(self):
        async def next_call():
            payload = self.proposal(await self.tools())
            payload["specialists"][0]["response_id"] = "forged"

            async def updates():
                yield AgentResponseUpdate(
                    role="assistant", contents=[Content.from_text(json.dumps(payload))]
                )

            self.context.result = ResponseStream(updates(), finalizer=AgentResponse.from_updates)

        await self.guard.process(self.context, next_call)
        with self.assertRaisesRegex(ValueError, "complete scoped"):
            await anext(self.context.result.__aiter__())

    async def test_stream_output_budget_is_enforced_before_emitting(self):
        async def updates():
            for _ in range(20001):
                yield AgentResponseUpdate(role="assistant", contents=[Content.from_text(" ")])

        async def next_call():
            self.context.result = ResponseStream(updates(), finalizer=AgentResponse.from_updates)

        await self.guard.process(self.context, next_call)
        with self.assertRaisesRegex(ValueError, "budget exceeded"):
            await anext(self.context.result.__aiter__())

    def test_coordinator_factory_has_only_guarded_specialist_capabilities(self):
        with patch("certificate_team.Agent") as constructor:
            self.assertIs(certificate_team(self.client), constructor.return_value)
        kwargs = constructor.call_args.kwargs
        self.assertEqual(kwargs["name"], "innexq-request-coordinator")
        self.assertIs(kwargs["default_options"]["store"], False)
        self.assertIsInstance(kwargs["middleware"][0], CertificateTeamGuard)
        self.assertNotIn("tools", kwargs)

    async def test_host_selects_certificate_pack_without_legacy_tools_and_closes_credential(self):
        environment = {
            "INNEXQ_AGENT_PACK": "certificate_fulfilment",
            "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/test",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "configured-model",
        }
        credential, client, agent = MagicMock(), object(), object()
        host = SimpleNamespace(run_async=AsyncMock())
        with (
            patch.dict(os.environ, environment),
            patch("main.DefaultAzureCredential", return_value=credential),
            patch("main.FoundryChatClient", return_value=client),
            patch("certificate_team.certificate_team", return_value=agent) as factory,
            patch("main.ProposalGuard") as legacy_guard,
            patch("main.ResponsesHostServer", return_value=host) as server,
        ):
            await main.main()
        factory.assert_called_once_with(client)
        server.assert_called_once_with(agent)
        legacy_guard.assert_not_called()
        host.run_async.assert_awaited_once()
        credential.close.assert_called_once()


MESSAGE_PACKET = {
    "mode": "customer_message",
    "request_id": PACKET["request_id"],
    "tenant_id": PACKET["tenant_id"],
    "customer_id": "DEMO-FAB",
    "equipment_ids": ["DEMO-PT-001", "DEMO-PT-002"],
    "selected_equipment_id": None,
    "messages": ["Provice Certificate for PT-002"],
}
INTERPRETATION = {
    "request_id": PACKET["request_id"],
    "intent": "certificate_request",
    "equipment_id": "DEMO-PT-002",
}


class CustomerMessageSafetyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guard = CertificateTeamGuard(object())
        self.context = SimpleNamespace(
            messages=[Message(role="user", contents=[json.dumps(MESSAGE_PACKET)])],
            options={"instructions": "malicious override", "tools": ["write"], "store": True},
            tools=[lambda: self.fail("interpretation must not invoke tools")],
            result=None,
        )

    def set_packet(self, changes):
        self.context.messages = [
            Message(role="user", contents=[json.dumps(MESSAGE_PACKET | changes)])
        ]

    async def run_output(self, payload, *, stream=False):
        async def next_call():
            if stream:

                async def updates():
                    text = json.dumps(payload)
                    for part in (text[:20], text[20:]):
                        yield AgentResponseUpdate(
                            role="assistant", contents=[Content.from_text(part)]
                        )

                self.context.result = ResponseStream(
                    updates(), finalizer=AgentResponse.from_updates
                )
            else:
                self.context.result = response(payload)

        await self.guard.process(self.context, next_call)
        if stream:
            return [update async for update in self.context.result]
        return self.context.result

    async def test_same_coordinator_interpretation_has_zero_tools_no_specialists_no_storage(self):
        with patch("certificate_team.Agent") as factory:
            result = await self.run_output(INTERPRETATION)
        factory.assert_not_called()
        self.assertEqual(self.context.tools, [])
        self.assertEqual(
            self.context.options,
            {
                "response_format": CustomerInterpretation,
                "store": False,
                "max_output_tokens": 500,
                "instructions": CUSTOMER_INSTRUCTIONS,
            },
        )
        self.assertEqual(
            CustomerInterpretation.model_validate_json(result.text).intent, "certificate_request"
        )

    async def test_real_framework_applies_invocation_local_mode_without_mutating_agent(self):
        seen_options = []

        async def get_response(**kwargs):
            seen_options.append(kwargs["options"])
            return ChatResponse(
                messages=[Message(role="assistant", contents=[json.dumps(INTERPRETATION)])]
            )

        agent = certificate_team(SimpleNamespace(get_response=get_response))
        original = dict(agent.default_options)
        result = await agent.run(json.dumps(MESSAGE_PACKET))
        self.assertEqual(
            CustomerInterpretation.model_validate_json(result.text).equipment_id, "DEMO-PT-002"
        )
        self.assertFalse(seen_options[0].get("tools"))
        self.assertIn(CUSTOMER_INSTRUCTIONS, seen_options[0]["instructions"])
        self.assertIs(seen_options[0]["response_format"], CustomerInterpretation)
        self.assertIs(seen_options[0]["store"], False)
        self.assertEqual(agent.default_options, original)

    async def test_valid_interpretation_stream_is_buffered_and_final_is_validated(self):
        updates = await self.run_output(INTERPRETATION, stream=True)
        self.assertEqual(len(updates), 2)
        final = await self.context.result.get_final_response()
        self.assertEqual(
            CustomerInterpretation.model_validate_json(final.text).equipment_id, "DEMO-PT-002"
        )

    async def test_all_supported_intents_have_typed_outputs_without_answer_facts(self):
        for intent in (
            "certificate_request",
            "certificate_status",
            "service_status",
            "service_request",
            "general",
            "clarify",
        ):
            with self.subTest(intent=intent):
                await self.run_output(
                    INTERPRETATION
                    | {
                        "intent": intent,
                        "equipment_id": None if intent in {"general", "clarify"} else "DEMO-PT-001",
                    }
                )

    async def test_malformed_or_unscoped_outputs_fail_both_modes_before_stream_emission(self):
        for changes in (
            {"request_id": "00000000-0000-0000-0000-000000000099"},
            {"equipment_id": "DEMO-PT-010"},
            {"equipment_id": "PT-002"},
            {"intent": "general"},
            {"intent": "clarify"},
            {"intent": "approved"},
            {"answer": "Your service is current"},
        ):
            for stream in (False, True):
                with self.subTest(changes=changes, stream=stream):
                    with self.assertRaises(ValueError):
                        await self.run_output(INTERPRETATION | changes, stream=stream)
        for payload in ([], "malformed", None):
            for stream in (False, True):
                with self.subTest(payload=payload, stream=stream):
                    with self.assertRaises(ValueError):
                        await self.run_output(payload, stream=stream)

    async def test_input_bounds_scope_duplicates_and_unknown_modes_fail_before_model(self):
        for changes in (
            {"equipment_ids": []},
            {"equipment_ids": [f"DEMO-PT-{i:03}" for i in range(11)]},
            {"equipment_ids": ["DEMO-PT-001", "DEMO-PT-001"]},
            {"equipment_ids": ["*"]},
            {"selected_equipment_id": "DEMO-PT-010"},
            {"messages": []},
            {"messages": ["hello"] * 7},
            {"messages": ["x" * 1001]},
            {"messages": [""]},
            {"mode": "execute"},
            {"approval": True},
        ):
            with self.subTest(changes=changes):
                self.set_packet(changes)
                next_call = AsyncMock()
                with self.assertRaises(ValueError):
                    await self.guard.process(self.context, next_call)
                next_call.assert_not_called()

    async def test_missing_equipment_is_left_to_controller_for_clarification_or_unsupported(self):
        for intent in (
            "certificate_request",
            "certificate_status",
            "service_status",
            "service_request",
            "general",
            "clarify",
        ):
            with self.subTest(intent=intent):
                for stream in (False, True):
                    await self.run_output(
                        INTERPRETATION | {"intent": intent, "equipment_id": None}, stream=stream
                    )

    def test_scoped_selection_and_followup_packets_are_valid(self):
        packet = CustomerMessagePacket.model_validate(
            MESSAGE_PACKET
            | {
                "selected_equipment_id": "DEMO-PT-002",
                "messages": [
                    "Can I get a certificate?",
                    "PT-002",
                    "Do not send it; is service current?",
                ],
            }
        )
        self.assertEqual(len(packet.messages), 3)

    async def test_customer_output_text_budget_enforced_in_both_modes(self):
        for stream in (False, True):
            with self.subTest(stream=stream):
                with self.assertRaisesRegex(ValueError, "budget exceeded"):
                    await self.run_output(INTERPRETATION | {"invented": "x" * 2001}, stream=stream)

    def test_prompt_preserves_read_vs_action_negation_ambiguity_and_no_authority(self):
        for required in (
            "Provice",
            "PT-002",
            "service_status",
            "certificate_status",
            "service_request",
            "do not send",
            "clarify",
            "untrusted",
            "No answer facts",
            "selected_equipment_id",
            "null equipment_id",
        ):
            self.assertIn(required, CUSTOMER_INSTRUCTIONS)

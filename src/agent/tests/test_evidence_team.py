"""Candidate tool-directed team with actual FunctionTools, no cloud/model service."""

import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from agent_framework import (
    Agent,
    AgentResponse,
    AgentResponseUpdate,
    BaseChatClient,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
    ResponseStream,
)
from mcp.types import CallToolResult
from pydantic import SecretStr

from evidence_team import EvidenceInvestigation, EvidenceTeamGuard, evidence_team
from evidence_toolbox import ScopedEvidenceTools

NOW = datetime(2026, 9, 19, tzinfo=UTC)
PACKET = {
    "mode": "evidence_investigation",
    "request_id": "00000000-0000-0000-0000-000000000001",
    "tenant_id": "00000000-0000-0000-0000-000000000002",
    "customer_id": "DEMO-FAB",
    "equipment_id": "DEMO-PT-001",
    "intent": "certificate_request",
    "prompt": "Provide the existing certificate",
    "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
}
ROLES = ("document_analyst", "equipment_service")


def response(payload, response_id="coordinator-real"):
    return AgentResponse(
        messages=[Message(role="assistant", contents=[json.dumps(payload)])],
        response_id=response_id,
    )


class EvidenceTeamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.handles = {
            role: SecretStr(f"{UUID(PACKET['request_id']).hex}.{role}." + "x" * 43)
            for role in ROLES
        }
        self.clock = NOW
        self.guard = EvidenceTeamGuard(
            object(), object(), "endpoint", "project", now=lambda: self.clock
        )
        self.context = SimpleNamespace(
            messages=[Message(role="user", contents=[json.dumps(PACKET)])],
            options={"tools": ["execute"], "instructions": "override", "store": True},
            tools=[],
            result=None,
        )
        self.clients = []
        self.model_inputs = []
        self.closed = []
        self.skip = set()
        self.model_error = None
        self.model_summary = "Observed scoped evidence; controller must validate it."
        self.receipt_override = None

        @asynccontextmanager
        async def toolbox(credential, endpoint, project, scope):
            async def call_tool(name, arguments):
                self.assertEqual(
                    arguments["scope_handle"], self.handles[scope.specialist].get_secret_value()
                )
                return CallToolResult(
                    content=[],
                    structuredContent={
                        **scope.model_dump(mode="json", exclude={"scope_handle", "expires_at"}),
                        "tool_name": name.split("___")[1],
                        "receipt_id": str(self.receipt_override or uuid4()),
                        "payload": {"document_id": "DEMO-CERT-001", "source": "verified-fixture"},
                    },
                )

            tools = ScopedEvidenceTools(
                SimpleNamespace(call_tool=call_tool), scope, now=lambda: self.clock
            )
            self.clients.append(tools)
            try:
                yield tools
            finally:
                self.closed.append(scope.specialist)

        def specialist(**kwargs):
            async def run(message):
                self.model_inputs.append((message, kwargs))
                if self.model_error:
                    raise self.model_error
                # Model service is replaced, but tool discovery schemas and invocation
                # are the actual Agent Framework FunctionTools and scoped MCP wrapper.
                for function in kwargs["tools"]:
                    if function.name in self.skip:
                        continue
                    arguments = (
                        {"document_id": "DEMO-CERT-001"}
                        if function.name == "analyze_document"
                        else (
                            {"query": "certificate evidence requirements"}
                            if function.name == "retrieve_policy"
                            else {}
                        )
                    )
                    await function.invoke(arguments=arguments)
                return response({"summary": self.model_summary}, kwargs["name"] + "-response")

            return SimpleNamespace(run=run)

        self.enterContext(
            patch("evidence_team.current_evidence_handles", side_effect=lambda: self.handles)
        )
        self.enterContext(patch("evidence_team.open_evidence_tools", side_effect=toolbox))
        self.enterContext(patch("evidence_team.Agent", side_effect=specialist))

    async def proofs(self):
        return [await f.invoke(skip_parsing=True) for f in self.context.tools]

    def proposal(self, proofs):
        return {
            "request_id": PACKET["request_id"],
            "intent": PACKET["intent"],
            "specialists": [proof["specialist"] for proof in proofs],
        }

    async def run_team(self, transform=lambda value: value, *, stream=False):
        async def next_call():
            proposal = transform(self.proposal(await self.proofs()))
            if stream:

                async def updates():
                    text = json.dumps(proposal)
                    yield AgentResponseUpdate(
                        role="assistant", contents=[Content.from_text(text[:20])]
                    )
                    yield AgentResponseUpdate(
                        role="assistant", contents=[Content.from_text(text[20:])]
                    )

                self.context.result = ResponseStream(
                    updates(), finalizer=AgentResponse.from_updates
                )
            else:
                self.context.result = response(proposal)

        await self.guard.process(self.context, next_call)
        if stream:
            return [item async for item in self.context.result]
        return self.context.result

    async def test_specialists_call_real_wrappers_and_report_actual_receipts(self):
        result = await self.run_team()
        final = json.loads(result.text)
        self.assertEqual(len(final["specialists"]), 2)
        self.assertEqual([len(item["receipt_ids"]) for item in final["specialists"]], [2, 2])
        self.assertEqual(self.closed, list(ROLES))
        for message, options in self.model_inputs:
            self.assertEqual(
                EvidenceInvestigation.model_validate_json(message),
                EvidenceInvestigation.model_validate(PACKET),
            )
            self.assertFalse(options["default_options"]["store"])
            for handle in self.handles.values():
                self.assertNotIn(handle.get_secret_value(), message + result.text)
            for function in options["tools"]:
                self.assertNotIn("scope_handle", json.dumps(function.parameters()))
        self.assertNotIn("tools", self.context.options)
        self.assertFalse(self.context.options["store"])

    async def test_each_required_tool_must_actually_be_called(self):
        for name in (
            "analyze_document",
            "list_equipment_documents",
            "retrieve_policy",
            "get_equipment_record",
        ):
            with self.subTest(name=name):
                self.skip = {name}
                with self.assertRaisesRegex(ValueError, "specialist failed"):
                    await self.run_team()

    async def test_real_agent_framework_model_loop_selects_specialists_and_mcp_tools(self):
        selected = []

        async def get_response(**kwargs):
            messages, options = kwargs["messages"], kwargs["options"]
            for handle in self.handles.values():
                self.assertNotIn(handle.get_secret_value(), repr(messages))
            functions = options["tools"]
            results = [c for m in messages for c in m.contents if c.type == "function_result"]
            if len(results) < len(functions):
                function = functions[len(results)]
                selected.append(function.name)
                arguments = (
                    {"document_id": "DEMO-CERT-001"}
                    if function.name == "analyze_document"
                    else (
                        {"query": "certificate policy"}
                        if function.name == "retrieve_policy"
                        else {}
                    )
                )
                content = Content.from_function_call(
                    str(uuid4()), function.name, arguments=arguments
                )
            else:
                payload = (
                    self.proposal([json.loads(item.result) for item in results])
                    if functions[0].name == "investigate_documents"
                    else {"summary": self.model_summary}
                )
                content = Content.from_text(json.dumps(payload))
            return ChatResponse(
                messages=[Message(role="assistant", contents=[content])], response_id=str(uuid4())
            )

        class FakeChatClient(FunctionInvocationLayer, BaseChatClient):
            async def _inner_get_response(self, **kwargs):
                return await get_response(**kwargs)

        client = FakeChatClient()
        with patch("evidence_team.Agent", Agent):
            agent = Agent(
                client=client,
                middleware=[
                    EvidenceTeamGuard(client, object(), "endpoint", "project", now=lambda: NOW)
                ],
            )
            final = await agent.run(json.dumps(PACKET))
        self.assertEqual(
            selected,
            [
                "investigate_documents",
                "list_equipment_documents",
                "analyze_document",
                "investigate_equipment",
                "get_equipment_record",
                "retrieve_policy",
            ],
        )
        self.assertEqual(len(json.loads(final.text)["specialists"]), 2)

    async def test_fabricated_or_changed_coordinator_proofs_never_pass(self):
        for change in (
            "request_id",
            "intent",
            "summary",
            "receipt_ids",
            "response_id",
            "duplicate",
        ):
            with self.subTest(change=change):

                def tamper(value, change=change):
                    if change == "request_id":
                        value[change] = str(uuid4())
                    elif change == "intent":
                        value[change] = "service_status"
                    elif change == "duplicate":
                        value["specialists"][1] = value["specialists"][0]
                    else:
                        value[change] = (
                            [str(uuid4()), str(uuid4())] if change == "receipt_ids" else "forged"
                        )
                    return value

                with self.assertRaisesRegex(ValueError, "complete scoped"):
                    await self.run_team(tamper)

    async def test_coordinator_cannot_skip_specialists(self):
        async def next_call():
            proof = {
                "specialist": ROLES[0],
                "summary": "forged",
                "response_id": "forged",
                "receipt_ids": [str(uuid4()), str(uuid4())],
            }
            self.context.result = response(self.proposal([proof, proof | {"specialist": ROLES[1]}]))

        with self.assertRaisesRegex(ValueError, "complete scoped"):
            await self.guard.process(self.context, next_call)
        self.assertEqual(self.clients, [])

    async def test_provenance_is_assembled_from_actual_calls_not_model_copies(self):
        result = await self.run_team(
            lambda value: value | {"specialists": list(reversed(value["specialists"]))}
        )
        proofs = json.loads(result.text)["specialists"]
        self.assertEqual([proof["specialist"] for proof in proofs], list(ROLES))
        for proof, client in zip(proofs, self.clients, strict=True):
            self.assertEqual(proof["receipt_ids"], [str(item) for item in client.receipt_ids])
            self.assertEqual(proof["summary"], self.model_summary)
            self.assertEqual(proof["response_id"], "innexq-" + proof["specialist"] + "-response")

    async def test_duplicate_parallel_branch_is_fatal_even_if_model_catches_error(self):
        async def next_call():
            calls = await asyncio.gather(
                *(self.context.tools[0].invoke(skip_parsing=True) for _ in range(2)),
                return_exceptions=True,
            )
            self.assertTrue(any(isinstance(item, ValueError) for item in calls))
            with self.assertRaises(ValueError):
                await self.context.tools[1].invoke(skip_parsing=True)
            self.context.result = response(self.proposal([]))

        with self.assertRaises(ValueError):
            await self.guard.process(self.context, next_call)
        self.assertEqual(len(self.clients), 1)

    async def test_cancellation_latches_and_prevents_another_branch(self):
        self.model_error = asyncio.CancelledError()

        async def next_call():
            with self.assertRaises(asyncio.CancelledError):
                await self.context.tools[0].invoke(skip_parsing=True)
            self.model_error = None
            with self.assertRaisesRegex(ValueError, "specialist failed"):
                await self.context.tools[1].invoke(skip_parsing=True)

        with self.assertRaisesRegex(ValueError, "missing evidence"):
            await self.guard.process(self.context, next_call)
        self.assertEqual(len(self.clients), 1)
        self.assertEqual(self.closed, [ROLES[0]])

    async def test_model_errors_are_sanitized_and_session_closes(self):
        self.model_error = RuntimeError(self.handles[ROLES[0]].get_secret_value())
        with self.assertRaisesRegex(ValueError, "specialist failed") as caught:
            await self.run_team()
        self.assertNotIn("xxxxx", str(caught.exception))
        self.assertEqual(self.closed, [ROLES[0]])

    async def test_scope_handle_in_summary_stops_without_emission(self):
        self.model_summary = self.handles[ROLES[1]].get_secret_value()
        with self.assertRaisesRegex(ValueError, "specialist failed"):
            await self.run_team()

    async def test_scope_handle_in_coordinator_response_id_is_not_forwarded(self):
        async def next_call():
            self.context.result = response(
                self.proposal(await self.proofs()), self.handles[ROLES[0]].get_secret_value()
            )

        with self.assertRaisesRegex(ValueError, "unsafe coordinator"):
            await self.guard.process(self.context, next_call)

    async def test_coordinator_cancellation_latches_escaped_tool_closures(self):
        async def next_call():
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await self.guard.process(self.context, next_call)
        with self.assertRaisesRegex(ValueError, "specialist failed"):
            await self.context.tools[0].invoke(skip_parsing=True)
        self.assertEqual(self.clients, [])

    async def test_missing_wrong_expired_or_model_visible_handles_stop_before_model(self):
        next_call = AsyncMock()
        for handles in (
            {},
            {ROLES[0]: self.handles[ROLES[0]]},
            {role: SecretStr("bad") for role in ROLES},
        ):
            with patch("evidence_team.current_evidence_handles", return_value=handles):
                with self.assertRaisesRegex(ValueError, "fresh scoped"):
                    await self.guard.process(self.context, next_call)
        for changes in (
            {"request_id": str(uuid4())},
            {"expires_at": NOW.isoformat()},
            {"prompt": self.handles[ROLES[0]].get_secret_value()},
            {"document_facts": ["precomputed evidence"]},
            {"mode": "customer_message"},
        ):
            self.context.messages = [Message(role="user", contents=[json.dumps(PACKET | changes)])]
            with self.assertRaisesRegex(ValueError, "fresh scoped"):
                await self.guard.process(self.context, next_call)
        next_call.assert_not_called()

    async def test_history_or_oversize_packet_is_rejected(self):
        for messages in (
            [],
            self.context.messages * 2,
            [Message(role="assistant", contents=[json.dumps(PACKET)])],
            [Message(role="user", contents=["x" * 5001])],
        ):
            self.context.messages = messages
            with self.assertRaisesRegex(ValueError, "fresh scoped"):
                await self.guard.process(self.context, AsyncMock())

    async def test_valid_stream_emits_only_checked_final_json(self):
        updates = await self.run_team(stream=True)
        self.assertEqual(len(updates), 1)
        final = await self.context.result.get_final_response()
        self.assertEqual(json.loads(final.text)["request_id"], PACKET["request_id"])

    async def test_invalid_stream_emits_nothing(self):
        with self.assertRaisesRegex(ValueError, "complete scoped"):
            await self.run_team(lambda value: value | {"request_id": str(uuid4())}, stream=True)

    async def test_scope_expiring_before_output_is_rejected(self):
        def expire(value):
            self.clock += timedelta(minutes=6)
            return value

        with self.assertRaisesRegex(ValueError, "complete scoped"):
            await self.run_team(expire)

    async def test_stream_budget_and_missing_output(self):
        with self.assertRaisesRegex(ValueError, "missing evidence"):
            await self.guard.process(self.context, AsyncMock())

        async def next_call():
            async def updates():
                yield AgentResponseUpdate(
                    role="assistant", contents=[Content.from_text("x" * 20001)]
                )

            self.context.result = ResponseStream(updates(), finalizer=AgentResponse.from_updates)

        await self.guard.process(self.context, next_call)
        with self.assertRaisesRegex(ValueError, "budget exceeded"):
            await anext(self.context.result.__aiter__())

    def test_factory_only_installs_candidate_guard(self):
        with patch("evidence_team.Agent") as constructor:
            evidence_team("client", "credential", "endpoint", "project")
        options = constructor.call_args.kwargs
        self.assertNotIn("tools", options)
        self.assertIsInstance(options["middleware"][0], EvidenceTeamGuard)
        self.assertFalse(options["default_options"]["store"])
        self.assertEqual(EvidenceInvestigation.model_validate(PACKET).intent, "certificate_request")

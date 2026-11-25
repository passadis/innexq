"""Coverage renewal team with actual FunctionTools, no cloud/model service."""

import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from agent_framework import AgentResponse, Message
from mcp.types import CallToolResult
from pydantic import SecretStr

from coverage_team import CoverageInvestigation, CoverageTeamGuard
from coverage_toolbox import ScopedCoverageTools
from evidence_dispatch import EvidenceDispatch

NOW = datetime(2026, 9, 22, tzinfo=UTC)
PACKET = {
    "mode": "coverage_renewal",
    "request_id": "00000000-0000-0000-0000-000000000011",
    "tenant_id": "00000000-0000-0000-0000-000000000002",
    "customer_id": "DEMO-FAB",
    "equipment_id": "DEMO-COV-001",
    "intent": "coverage_renewal",
    "prompt": "Renew service coverage for DEMO-COV-001",
    "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
}
ROLES = ("renewal_coordinator", "coverage_billing")
ARGUMENTS = {
    "analyze_service_coverage_document": {"document_id": "DEMO-COV-001-COVERAGE-PDF"},
    "retrieve_renewal_policy": {"query": "renewal window and duration"},
    "calculate_renewal_quote": {"base_amount": "8500.00"},
}


def response(payload, response_id="coordinator-real"):
    return AgentResponse(
        messages=[Message(role="assistant", contents=[json.dumps(payload)])],
        response_id=response_id,
    )


class CoverageTeamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.handles = {
            role: SecretStr(f"{UUID(PACKET['request_id']).hex}.{role}." + "x" * 43)
            for role in ROLES
        }
        self.clock = NOW
        self.guard = CoverageTeamGuard(
            object(), object(), "endpoint", "project", now=lambda: self.clock
        )
        self.context = SimpleNamespace(
            messages=[Message(role="user", contents=[json.dumps(PACKET)])],
            options={"tools": ["execute"], "instructions": "override", "store": True},
            tools=[],
            result=None,
        )
        self.model_inputs = []
        self.skip = set()
        self.tool_arguments = []

        @asynccontextmanager
        async def toolbox(credential, endpoint, project, scope):
            async def call_tool(name, arguments):
                self.assertEqual(
                    arguments["scope_handle"], self.handles[scope.specialist].get_secret_value()
                )
                self.tool_arguments.append(
                    (name, {k: v for k, v in arguments.items() if k != "scope_handle"})
                )
                return CallToolResult(
                    content=[],
                    structuredContent={
                        **scope.model_dump(mode="json", exclude={"scope_handle", "expires_at"}),
                        "tool_name": name.split("___")[1],
                        "receipt_id": str(uuid4()),
                        "payload": {"source": "verified-fixture"},
                    },
                )

            yield ScopedCoverageTools(
                SimpleNamespace(call_tool=call_tool), scope, now=lambda: self.clock
            )

        def specialist(**kwargs):
            async def run(message):
                self.model_inputs.append((message, kwargs))
                for function in kwargs["tools"]:
                    if function.name in self.skip:
                        continue
                    await function.invoke(arguments=ARGUMENTS.get(function.name, {}))
                return response(
                    {"summary": "Observed scoped coverage evidence; controller validates."},
                    kwargs["name"] + "-response",
                )

            return SimpleNamespace(run=run)

        self.enterContext(
            patch("coverage_team.current_evidence_handles", side_effect=lambda: self.handles)
        )
        self.enterContext(patch("coverage_team.open_coverage_tools", side_effect=toolbox))
        self.enterContext(patch("coverage_team.Agent", side_effect=specialist))

    async def run_team(self, transform=lambda value: value):
        async def next_call():
            proofs = [await f.invoke(skip_parsing=True) for f in self.context.tools]
            proposal = transform(
                {
                    "request_id": PACKET["request_id"],
                    "intent": PACKET["intent"],
                    "specialists": [proof["specialist"] for proof in proofs],
                }
            )
            self.context.result = response(proposal)

        await self.guard.process(self.context, next_call)
        return self.context.result

    async def test_both_branches_produce_receipts_and_a_bound_proposal(self):
        result = await self.run_team()
        final = json.loads(result.text)
        self.assertEqual(final["request_id"], PACKET["request_id"])
        self.assertEqual([item["specialist"] for item in final["specialists"]], list(ROLES))
        self.assertEqual([len(item["receipt_ids"]) for item in final["specialists"]], [1, 4])
        called = {name.split("___")[1] for name, _ in self.tool_arguments}
        self.assertIn("calculate_renewal_quote", called)
        for _, arguments in self.tool_arguments:
            if "base_amount" in arguments:
                self.assertEqual(arguments["base_amount"], "8500.00")
        for message, options in self.model_inputs:
            CoverageInvestigation.model_validate_json(message)
            for handle in self.handles.values():
                self.assertNotIn(handle.get_secret_value(), message + result.text)
            for function in options["tools"]:
                self.assertNotIn("scope_handle", json.dumps(function.parameters()))

    async def test_every_billing_tool_is_mandatory(self):
        for name in (
            "list_service_coverage_documents",
            "analyze_service_coverage_document",
            "retrieve_renewal_policy",
            "calculate_renewal_quote",
            "get_equipment_record",
        ):
            with self.subTest(name=name):
                self.skip = {name}
                with self.assertRaisesRegex(ValueError, "specialist failed"):
                    await self.run_team()

    async def test_expired_packet_is_refused_before_any_branch(self):
        self.clock = NOW + timedelta(minutes=10)
        with self.assertRaisesRegex(ValueError, "fresh scoped coverage packet"):
            await self.run_team()
        self.assertEqual(self.tool_arguments, [])

    async def test_foreign_or_missing_handles_are_refused(self):
        self.handles = {role: SecretStr(f"{uuid4().hex}.{role}." + "x" * 43) for role in ROLES}
        with self.assertRaisesRegex(ValueError, "fresh scoped coverage packet"):
            await self.run_team()

    async def test_coordination_must_match_the_packet(self):
        with self.assertRaisesRegex(ValueError, "coverage"):
            await self.run_team(transform=lambda value: value | {"request_id": str(uuid4())})


class CoverageDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_coverage_mode_routes_to_the_coverage_guard_only(self):
        dispatch = EvidenceDispatch(object(), object(), "endpoint", "project")
        dispatch.candidate.process = AsyncMock()
        dispatch.legacy.process = AsyncMock()
        dispatch.coverage.process = AsyncMock()
        context = SimpleNamespace(messages=[Message(role="user", contents=[json.dumps(PACKET)])])
        call_next = AsyncMock()
        await dispatch.process(context, call_next)
        dispatch.coverage.process.assert_awaited_once()
        dispatch.candidate.process.assert_not_called()
        dispatch.legacy.process.assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(unittest.main())

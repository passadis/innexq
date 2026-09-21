"""Offline safety checks; no Azure calls or model substitutions in live operation."""

import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_framework import AgentResponse, AgentResponseUpdate, Content, Message, ResponseStream
from pydantic import ValidationError

from contracts import Citation, Proposal
from main import ProposalGuard
from retrieval import parse_references

REQUEST = {
    "run_id": "8c7cc37e-081b-4841-a2f3-a3ab81b3c714",
    "correlation_id": "432cac42-212c-4776-852f-75701b77ed4c",
    "contract_id": "CON-FAB-2025-001",
}
CITATIONS = [
    Citation(
        source_id=name,
        title=name,
        excerpt=f"Synthetic {name} evidence",
        url=f"https://schemas.innexq.invalid/corpus/{name}/2026-09-07",
    )
    for name in ["contract", "pricing", "authority", "sla", "playbook", "template"]
]
PROPOSAL = Proposal(summary=CITATIONS[0].excerpt, citations=CITATIONS)
ENVIRONMENT = {
    "AZURE_SEARCH_ENDPOINT": "https://innexq.search.windows.net",
    "INNEXQ_API_ENDPOINT": "https://innexq.azurecontainerapps.io",
    "INNEXQ_API_AUDIENCE": "api://innexq",
    "KNOWLEDGE_BASE_NAME": "innexq-kb",
    "KNOWLEDGE_SOURCE_NAME": "innexq-source",
}


class SafetyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENVIRONMENT)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.credential = SimpleNamespace(get_token=lambda _: SimpleNamespace(token="test-token"))
        self.guard = ProposalGuard(self.credential)
        self.context = SimpleNamespace(
            messages=[Message(role="user", contents=[json.dumps(REQUEST)])],
            options={},
            tools=[],
            result=None,
        )

    def test_financial_fields_rejected(self):
        payload = PROPOSAL.model_dump()
        payload["discount_amount"] = "14400.00"
        with self.assertRaises(ValidationError):
            Proposal.model_validate(payload)

    def test_partial_retrieval_rejected(self):
        with self.assertRaises(ValueError):
            parse_references({"activity": [{"error": {"code": "403"}}]})
        with self.assertRaises(ValueError):
            parse_references({"references": []})

    async def test_model_cannot_skip_tools(self):
        async def next_call():
            self.context.result = AgentResponse(
                messages=[Message(role="assistant", contents=[PROPOSAL.model_dump_json()])]
            )

        with self.assertRaisesRegex(ValueError, "tool evidence"):
            await self.guard.process(self.context, next_call)

    async def test_default_none_options_reach_tools_and_retain_guard(self):
        self.context.options = None

        async def next_call():
            self.assertIs(self.context.options["response_format"], Proposal)
            self.assertIs(self.context.options["store"], False)
            self.context.result = AgentResponse(
                messages=[Message(role="assistant", contents=[PROPOSAL.model_dump_json()])]
            )

        with self.assertRaisesRegex(ValueError, "tool evidence"):
            await self.guard.process(self.context, next_call)

    async def test_bound_tools_and_provenance(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        response = SimpleNamespace(status_code=200, json=lambda: {"tool_version": "1.0.0"})
        client.post.return_value = response

        async def next_call():
            await self.context.tools[0]("Retrieve the six required evidence documents")
            await self.context.tools[1]()
            self.context.result = AgentResponse(
                messages=[Message(role="assistant", contents=[PROPOSAL.model_dump_json()])]
            )

        with patch("main.retrieve", AsyncMock(return_value=CITATIONS)):
            with patch("main.httpx.AsyncClient", return_value=client):
                await self.guard.process(self.context, next_call)
        self.assertEqual(client.post.call_args.kwargs["json"], REQUEST)

    async def test_fabricated_citation_rejected_after_real_tools(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = SimpleNamespace(status_code=200, json=lambda: {})
        altered = PROPOSAL.model_copy(deep=True)
        altered.citations[0].excerpt = "A fabricated source assertion"

        async def next_call():
            await self.context.tools[0]("contract evidence")
            await self.context.tools[1]()
            self.context.result = AgentResponse(
                messages=[Message(role="assistant", contents=[altered.model_dump_json()])]
            )

        with patch("main.retrieve", AsyncMock(return_value=CITATIONS)):
            with patch("main.httpx.AsyncClient", return_value=client):
                with self.assertRaisesRegex(ValueError, "does not match"):
                    await self.guard.process(self.context, next_call)

    async def test_parallel_model_queries_are_serialized_without_retries(self):
        active = 0
        peak = 0
        calls = []

        async def search(*args):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            calls.append(args[-1])
            await asyncio.sleep(0)
            active -= 1
            return CITATIONS

        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = SimpleNamespace(status_code=200, json=lambda: {})

        async def next_call():
            await asyncio.gather(*(self.context.tools[0](str(i)) for i in range(6)))
            await self.context.tools[1]()
            self.context.result = AgentResponse(
                messages=[Message(role="assistant", contents=[PROPOSAL.model_dump_json()])]
            )

        with patch("main.retrieve", side_effect=search):
            with patch("main.httpx.AsyncClient", return_value=client):
                await self.guard.process(self.context, next_call)
        self.assertEqual(peak, 1)
        self.assertEqual(calls, [str(i) for i in range(6)])
        self.assertEqual(client.post.await_count, 1)

    async def test_serialized_empty_evidence_still_blocks_entire_proposal(self):
        calls = []

        async def search(*args):
            calls.append(args[-1])
            await asyncio.sleep(0)
            if args[-1] == "empty":
                return parse_references({"references": []})
            return CITATIONS

        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = SimpleNamespace(status_code=200, json=lambda: {})

        async def next_call():
            results = await asyncio.gather(
                self.context.tools[0]("empty"),
                self.context.tools[0]("complete"),
                return_exceptions=True,
            )
            self.assertIsInstance(results[0], ValueError)
            await self.context.tools[1]()
            self.context.result = AgentResponse(
                messages=[Message(role="assistant", contents=[PROPOSAL.model_dump_json()])]
            )

        with patch("main.retrieve", side_effect=search):
            with patch("main.httpx.AsyncClient", return_value=client):
                with self.assertRaisesRegex(ValueError, "tool evidence"):
                    await self.guard.process(self.context, next_call)
        self.assertEqual(calls, ["empty", "complete"])

    async def test_serialized_queries_preserve_eight_call_limit(self):
        async def next_call():
            results = await asyncio.gather(
                *(self.context.tools[0](str(i)) for i in range(9)), return_exceptions=True
            )
            self.assertIsInstance(results[8], ValueError)
            self.context.result = AgentResponse(
                messages=[Message(role="assistant", contents=[PROPOSAL.model_dump_json()])]
            )

        with patch("main.retrieve", AsyncMock(return_value=CITATIONS)) as search:
            with self.assertRaisesRegex(ValueError, "tool evidence"):
                await self.guard.process(self.context, next_call)
        self.assertEqual(search.await_count, 8)

    async def test_stream_emits_nothing_before_guard_passes(self):
        async def updates():
            yield AgentResponseUpdate(
                contents=[Content.from_text(PROPOSAL.model_dump_json())], role="assistant"
            )

        async def next_call():
            self.context.result = ResponseStream(updates(), finalizer=AgentResponse.from_updates)

        await self.guard.process(self.context, next_call)
        with self.assertRaisesRegex(ValueError, "tool evidence"):
            await anext(self.context.result.__aiter__())


if __name__ == "__main__":
    unittest.main()

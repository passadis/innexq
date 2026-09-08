"""Offline safety checks; no Azure calls or model substitutions in live operation."""

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

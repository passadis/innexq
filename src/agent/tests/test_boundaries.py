"""Exercise every fail-closed boundary using offline transport doubles."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from agent_framework import AgentResponse, AgentResponseUpdate, Content, Message, ResponseStream
from test_guard import CITATIONS, ENVIRONMENT, PROPOSAL, REQUEST

from main import ProposalGuard, endpoint, main, required
from retrieval import API_VERSION, parse_references, retrieve


class Boundaries(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, ENVIRONMENT)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.credential = MagicMock()
        self.credential.get_token.return_value = SimpleNamespace(token="test-token")
        self.guard = ProposalGuard(self.credential)
        self.context = SimpleNamespace(
            messages=[Message("user", [json.dumps(REQUEST)])],
            options={},
            tools=["untrusted_mutation_tool"],
            result=None,
        )
        self.client = AsyncMock()
        self.client.__aenter__.return_value = self.client
        self.client.post.return_value = SimpleNamespace(status_code=200, json=lambda: {})

    async def propose(self, proposal=PROPOSAL, *, stream=False, calls=None):
        async def next_call():
            self.assertEqual(
                [tool.__name__ for tool in self.context.tools],
                ["retrieve_evidence", "calculate_pricing_authority"],
            )
            self.assertFalse(self.context.options["store"])
            if calls is None:
                await self.context.tools[0]("six evidence sources")
                await self.context.tools[1]()
            else:
                await calls()
            if stream:

                async def updates():
                    yield AgentResponseUpdate(
                        contents=[Content.from_text(proposal.model_dump_json())], role="assistant"
                    )

                self.context.result = ResponseStream(
                    updates(), finalizer=AgentResponse.from_updates
                )
            elif proposal is None:
                self.context.result = None
            else:
                self.context.result = AgentResponse(
                    messages=[Message("assistant", [proposal.model_dump_json()])]
                )

        with patch("main.retrieve", AsyncMock(return_value=CITATIONS)):
            with patch("main.httpx.AsyncClient", return_value=self.client):
                await self.guard.process(self.context, next_call)

    def test_configuration_fails_closed(self):
        with patch.dict(os.environ, {"ABSENT": ""}):
            with self.assertRaisesRegex(ValueError, "Missing"):
                required("ABSENT")
        for value in [
            "http://evil.test",
            "https://innexq.search.windows.net.evil.test",
            "https://user@innexq.search.windows.net",
            "https://innexq.search.windows.net?q=x",
        ]:
            with patch.dict(os.environ, {"AZURE_SEARCH_ENDPOINT": value}):
                with self.assertRaisesRegex(ValueError, "Invalid"):
                    endpoint("AZURE_SEARCH_ENDPOINT", ".search.windows.net")
        with patch.dict(os.environ, {"KNOWLEDGE_BASE_NAME": "../other"}):
            with self.assertRaisesRegex(ValueError, "Invalid"):
                ProposalGuard(self.credential)

    async def test_one_request_and_known_contract_only(self):
        self.context.messages *= 2
        with self.assertRaisesRegex(ValueError, "Exactly one"):
            await self.guard.process(self.context, AsyncMock())
        self.context.messages = [Message("user", [json.dumps({**REQUEST, "contract_id": "other"})])]
        with self.assertRaises(ValueError):
            await self.guard.process(self.context, AsyncMock())

    async def test_unsubstantiated_summary_is_rejected(self):
        altered = PROPOSAL.model_copy(update={"summary": "The buyer has approved the renewal."})
        with self.assertRaisesRegex(ValueError, "exact cited excerpt"):
            await self.propose(altered)

    async def test_missing_category_is_rejected(self):
        altered = PROPOSAL.model_copy(update={"citations": CITATIONS[:-1]})
        with self.assertRaisesRegex(ValueError, "every required"):
            await self.propose(altered)

    async def test_duplicate_pricing_poisoned_even_when_model_catches_error(self):
        async def calls():
            await self.context.tools[0]("evidence")
            await self.context.tools[1]()
            with self.assertRaisesRegex(ValueError, "once"):
                await self.context.tools[1]()

        with self.assertRaisesRegex(ValueError, "tool evidence"):
            await self.propose(calls=calls)
        self.assertEqual(self.client.post.await_count, 1)

    async def test_pricing_denial_poisoned_even_when_model_catches_error(self):
        self.client.post.return_value = SimpleNamespace(status_code=403)

        async def calls():
            await self.context.tools[0]("evidence")
            with self.assertRaisesRegex(ValueError, "HTTP 403"):
                await self.context.tools[1]()

        with self.assertRaisesRegex(ValueError, "tool evidence"):
            await self.propose(calls=calls)

    async def test_invalid_query_poisoned(self):
        async def calls():
            with self.assertRaisesRegex(ValueError, "Invalid"):
                await self.context.tools[0](" ")
            await self.context.tools[1]()

        with self.assertRaisesRegex(ValueError, "tool evidence"):
            await self.propose(calls=calls)

    async def test_conflicting_retrieval_poisoned(self):
        changed = CITATIONS[0].model_copy(update={"excerpt": "Contradiction"})

        async def next_call():
            await self.context.tools[0]("first")
            await self.context.tools[0]("second")

        with patch("main.retrieve", AsyncMock(side_effect=[CITATIONS, [changed]])):
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                await self.guard.process(self.context, next_call)

    async def test_missing_response_rejected(self):
        with self.assertRaisesRegex(ValueError, "no response"):
            await self.propose(None)

    async def test_valid_stream_released_only_after_full_check(self):
        await self.propose(stream=True)
        updates = [update async for update in self.context.result]
        self.assertEqual(len(updates), 1)
        response = await self.context.result.get_final_response()
        self.assertEqual(response.text, PROPOSAL.model_dump_json())

    def test_reference_parsing(self):
        source = {"id": "contract", "title": "Contract", "content": "Evidence", "url": "synthetic"}
        result = parse_references({"references": [{"type": "searchIndex", "sourceData": source}]})
        self.assertEqual(result[0].excerpt, "Evidence")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            parse_references({"references": [{"type": "web"}]})
        with self.assertRaisesRegex(ValueError, "evidence error"):
            parse_references({"error": {"code": "AccessDenied"}})

    async def test_retrieval_is_fixed_ga_read_only_request(self):
        payload = {
            "references": [
                {
                    "type": "searchIndex",
                    "sourceData": {
                        "id": "contract",
                        "title": "Contract",
                        "content": "Evidence",
                        "url": "synthetic",
                    },
                }
            ]
        }
        self.client.post.return_value = SimpleNamespace(status_code=200, json=lambda: payload)
        with patch("retrieval.httpx.AsyncClient", return_value=self.client):
            result = await retrieve(
                self.credential, "https://sample.search.windows.net", "kb", "src", "q"
            )
        self.assertEqual(result[0].source_id, "contract")
        self.credential.get_token.assert_called_once_with("https://search.azure.com/.default")
        args = self.client.post.call_args
        self.assertEqual(
            args.args[0], "https://sample.search.windows.net/knowledgebases('kb')/retrieve"
        )
        self.assertEqual(args.kwargs["params"], {"api-version": API_VERSION})
        self.assertEqual(args.kwargs["json"]["intents"], [{"type": "semantic", "search": "q"}])
        self.client.post.return_value = SimpleNamespace(status_code=403)
        with patch("retrieval.httpx.AsyncClient", return_value=self.client):
            with self.assertRaisesRegex(ValueError, "HTTP 403"):
                await retrieve(
                    self.credential, "https://sample.search.windows.net", "kb", "src", "q"
                )

    async def test_host_bootstrap_no_live_network(self):
        with patch.dict(
            os.environ,
            {
                "FOUNDRY_PROJECT_ENDPOINT": "https://sample.services.ai.azure.com/api/projects/test",
                "AZURE_AI_MODEL_DEPLOYMENT_NAME": "reasoning",
            },
        ):
            with patch("main.DefaultAzureCredential", return_value=self.credential):
                with patch("main.FoundryChatClient") as client:
                    with patch("main.Agent") as agent:
                        server = SimpleNamespace(run_async=AsyncMock())
                        with patch("main.ResponsesHostServer", return_value=server):
                            await main()
        client.assert_called_once()
        self.assertEqual(agent.call_args.kwargs["name"], "innexq-agent")
        self.assertFalse(agent.call_args.kwargs["default_options"]["store"])
        server.run_async.assert_awaited_once()
        self.credential.close.assert_called_once()

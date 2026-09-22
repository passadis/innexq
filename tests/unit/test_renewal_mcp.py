"""Renewal MCP surface: Renewal.Read enforcement and real scoped tool calls."""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from innexq_api.evidence_mcp import renewal_mcp
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.unit.test_evidence_broker import AGENT, TENANT
from tests.unit.test_renewal_broker import DOCUMENT, complete_calls, setup

CLIENT = UUID(int=501)
HOST = "renewal.example.test"
URL = f"https://{HOST}/mcp"
GOOD = {
    "oid": str(AGENT),
    "azp": str(CLIENT),
    "tid": str(TENANT),
    "idtyp": "app",
    "roles": ["Renewal.Read"],
}


class Auth:
    def __init__(self, changes=None):
        self.value = {**GOOD, **(changes or {})}

    def claims(self, request):
        if request.headers.get("authorization") != "Bearer OFFLINE-FAKE":
            raise HTTPException(401, "offline denied")
        return dict(self.value)


def build(auth=None):
    broker, binding, _container, backend, handles = setup()
    app, server = renewal_mcp(broker, auth or Auth(), AGENT, CLIENT, HOST)  # type: ignore[arg-type]
    return app, server, broker, binding, backend, handles


def test_renewal_discovery_and_five_scoped_tool_calls():
    async def check():
        app, server, broker, binding, backend, handles = build()
        receipts = {"renewal_coordinator": [], "coverage_billing": []}
        async with server.session_manager.run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                headers={"authorization": "Bearer OFFLINE-FAKE"},
            ) as client:
                async with streamable_http_client(URL, http_client=client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        assert {tool.name for tool in tools.tools} == {
                            "get_equipment_record",
                            "list_service_coverage_documents",
                            "analyze_service_coverage_document",
                            "retrieve_renewal_policy",
                            "calculate_renewal_quote",
                        }
                        for role, calls in complete_calls().items():
                            for name, args in calls:
                                result = await session.call_tool(
                                    name,
                                    {"scope_handle": handles[role].get_secret_value(), **args},
                                )
                                assert not result.isError
                                payload = result.structuredContent
                                assert payload is not None
                                assert payload["specialist"] == role
                                assert payload["tool_name"] == name
                                receipts[role].append(UUID(payload["receipt_id"]))
        assert len(broker.finish(binding, receipts)) == 5
        assert len(backend.calls) == 5

    asyncio.run(check())


@pytest.mark.parametrize(
    "changes",
    [
        {"roles": ["Evidence.Read"]},
        {"roles": []},
        {"roles": "Renewal.Read"},
        {"scp": "Renewal.Read"},
        {"idtyp": "user"},
        {"oid": str(uuid4())},
    ],
)
def test_wrong_identity_or_role_is_denied_before_the_broker(changes):
    async def check():
        app, _, _, _, backend, _ = build(Auth(changes))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            result = await client.post(
                URL,
                headers={"authorization": "Bearer OFFLINE-FAKE"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert result.status_code == 403
            assert result.json() == {"error": "Evidence access denied"}
        assert backend.calls == []

    asyncio.run(check())


def test_renewal_host_validation_rejects_wildcards():
    broker, *_ = setup()
    with pytest.raises(ValueError, match="hostname"):
        renewal_mcp(broker, Auth(), AGENT, CLIENT, "*.example.test")  # type: ignore[arg-type]


def test_document_argument_is_scope_bound():
    async def check():
        app, server, _, _, backend, handles = build()
        async with server.session_manager.run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                headers={"authorization": "Bearer OFFLINE-FAKE"},
            ) as client:
                async with streamable_http_client(URL, http_client=client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(
                            "analyze_service_coverage_document",
                            {
                                "scope_handle": handles["coverage_billing"].get_secret_value(),
                                "document_id": DOCUMENT + "-OTHER",
                            },
                        )
                        assert result.isError
        assert backend.calls == []

    asyncio.run(check())

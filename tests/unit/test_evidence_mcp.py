"""Real offline MCP HTTP transport; claims are doubles, not Entra acceptance."""

import asyncio
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from innexq_api.evidence_mcp import EvidenceAuthentication, evidence_mcp
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.unit.test_evidence_broker import AGENT, DOCUMENT, TENANT, setup

CLIENT = UUID(int=501)
HOST = "evidence.example.test"
URL = f"https://{HOST}/mcp"
GOOD = {
    "oid": str(AGENT),
    "azp": str(CLIENT),
    "tid": str(TENANT),
    "idtyp": "app",
    "roles": ["Evidence.Read"],
}


class Auth:
    """Simulate EntraAuth's already-tested verified-claims/tenant boundary."""

    def __init__(self, changes=None):
        self.value = {**GOOD, **(changes or {})}
        self.calls = 0

    def claims(self, request):
        self.calls += 1
        if request.headers.get("authorization") != "Bearer OFFLINE-FAKE":
            raise HTTPException(401, "offline denied")
        if self.value.get("tid") != str(TENANT):
            raise HTTPException(403, "offline tenant denied")
        return dict(self.value)


def build(auth=None):
    broker, binding, container, backend, handles = setup()
    auth = auth or Auth()
    app, server = evidence_mcp(broker, auth, AGENT, CLIENT, HOST)  # type: ignore[arg-type]
    return app, server, broker, binding, container, backend, handles, auth


def test_authenticated_discovery_and_four_real_scoped_tool_calls():
    async def check():
        app, server, broker, binding, _, backend, handles, auth = build()
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
                            "list_equipment_documents",
                            "analyze_document",
                            "retrieve_policy",
                        }
                        calls = [
                            ("document_analyst", "list_equipment_documents", {}),
                            ("document_analyst", "analyze_document", {"document_id": DOCUMENT}),
                            ("equipment_service", "get_equipment_record", {}),
                            ("equipment_service", "retrieve_policy", {"query": "standing policy"}),
                        ]
                        receipts = {"document_analyst": [], "equipment_service": []}
                        for role, name, args in calls:
                            result = await session.call_tool(
                                name, {"scope_handle": handles[role].get_secret_value(), **args}
                            )
                            assert not result.isError
                            assert result.structuredContent is not None
                            payload = result.structuredContent
                            assert payload["request_id"] == str(binding.request_id)
                            assert payload["tenant_id"] == str(TENANT)
                            assert payload["customer_id"] == binding.customer_id
                            assert payload["tool_name"] == name
                            assert payload["specialist"] == role
                            assert payload["payload"]["evidence"] == "test evidence"
                            receipt = UUID(payload["receipt_id"])
                            receipts[role].append(receipt)
                            stored = broker.store._read(binding.request_id, f"receipt-{receipt}")
                            assert stored["result"]["tool_name"] == name
                            assert handles[role].get_secret_value() not in result.model_dump_json()
        assert len(broker.finish(binding, receipts)) == 4
        assert len(backend.calls) == 4
        assert auth.calls >= 7  # initialize, notification, discovery, four tool calls

    asyncio.run(check())


@pytest.mark.parametrize(
    "changes",
    [
        {"oid": str(CLIENT)},
        {"azp": str(AGENT)},
        {"azp": None},
        {"scp": "Evidence.Read"},
        {"scp": ""},
        {"roles": []},
        {"roles": "Evidence.Read"},
        {"roles": ["Pricing.Read"]},
        {"idtyp": "user"},
        {"tid": str(CLIENT)},
    ],
)
def test_invalid_claims_denied_before_discovery_or_broker(changes):
    async def check():
        app, _, _, _, _, backend, _, _ = build(Auth(changes))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            result = await client.post(
                URL,
                headers={"authorization": "Bearer OFFLINE-FAKE"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
        assert result.status_code == 403
        assert result.json() == {"error": "Evidence access denied"}
        assert not backend.calls

    asyncio.run(check())


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("authorization", "Bearer invalid")],
        [("authorization", "Bearer OFFLINE-FAKE"), ("Authorization", "Bearer OFFLINE-FAKE")],
    ],
)
def test_missing_invalid_or_duplicate_authorization_denied(headers):
    async def check():
        app, _, _, _, _, backend, _, auth = build()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            result = await client.post(URL, headers=headers, json={})
        assert result.status_code == 401
        assert not backend.calls
        assert auth.calls == (1 if len(headers) == 1 else 0)

    asyncio.run(check())


@pytest.mark.parametrize(
    "header,value", [("host", "evil.example.test"), ("origin", "https://evil.example.test")]
)
def test_mcp_rejects_unconfigured_host_or_origin(header, value):
    async def check():
        app, server, _, _, _, backend, _, _ = build()
        async with server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                result = await client.post(
                    URL,
                    headers={
                        "authorization": "Bearer OFFLINE-FAKE",
                        header: value,
                        "accept": "application/json, text/event-stream",
                    },
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                )
        assert result.status_code in {403, 421}
        assert not backend.calls

    asyncio.run(check())


@pytest.mark.parametrize(
    "host",
    [
        "",
        "https://example.test",
        "example.test/path",
        "example.test:443",
        "*.example.test",
        "u@example.test",
    ],
)
def test_api_hostname_configuration_must_be_exact(host):
    broker, _, _, _, _ = setup()
    with pytest.raises(ValueError, match="exact evidence API hostname"):
        evidence_mcp(broker, Auth(), AGENT, CLIENT, host)  # type: ignore[arg-type]


def test_identity_context_resets_on_exception_and_concurrent_requests():
    from innexq_api.evidence_mcp import _identity

    async def check():
        seen = []

        async def inner(scope, receive, send):
            identity = _identity.get()
            await asyncio.sleep(0)
            assert _identity.get() == identity
            seen.append(identity)
            if scope["path"] == "/error":
                raise RuntimeError("offline failure")
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"safe"})

        first = EvidenceAuthentication(inner, Auth(), AGENT, CLIENT)  # type: ignore[arg-type]
        second = EvidenceAuthentication(
            inner, Auth({"oid": str(CLIENT), "azp": str(AGENT)}), CLIENT, AGENT
        )  # type: ignore[arg-type]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=first),
            headers={"authorization": "Bearer OFFLINE-FAKE"},
        ) as a:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=second),
                headers={"authorization": "Bearer OFFLINE-FAKE"},
            ) as b:
                await asyncio.gather(a.get("https://test/ok"), b.get("https://test/ok"))
                with pytest.raises(RuntimeError, match="offline failure"):
                    await a.get("https://test/error")
        assert _identity.get() is None
        assert (TENANT, AGENT) in seen and (TENANT, CLIENT) in seen

    asyncio.run(check())

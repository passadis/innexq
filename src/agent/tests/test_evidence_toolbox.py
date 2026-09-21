"""Offline compatibility proof, not live Foundry/Entra/OCR acceptance."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from azure.core.credentials import AccessToken
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from evidence_toolbox import (
    ROLE_TOOLS,
    SERVER_LABEL,
    TOOL_NAMES,
    EvidenceScope,
    ScopedEvidenceTools,
    open_evidence_tools,
    validate_toolbox_endpoint,
)

PROJECT = "https://offline-proof.services.ai.azure.com/api/projects/innexq"
ENDPOINT = PROJECT + "/toolboxes/evidence/versions/1/mcp?api-version=v1"
NOW = datetime(2026, 9, 19, tzinfo=UTC)


def scope(role="document_analyst", **changes):
    return EvidenceScope.model_validate(
        {
            "request_id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "customer_id": "DEMO-FAB",
            "equipment_id": "DEMO-PT-001",
            "specialist": role,
            "scope_handle": "a" * 43,
            "expires_at": NOW + timedelta(minutes=5),
            **changes,
        }
    )


def result(binding, name="list_equipment_documents", **changes):
    return types.CallToolResult(
        content=[],
        structuredContent={
            **binding.model_dump(mode="json", exclude={"scope_handle", "expires_at"}),
            "tool_name": name,
            "receipt_id": str(uuid4()),
            "payload": {"documents": ["DEMO-PT-001-CERTIFICATE-PDF"]},
            **changes,
        },
    )


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def call_tool(self, name, *, arguments):
        self.calls.append((name, arguments))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_wrappers_hide_scope_and_expose_only_role_tools():
    for role in ROLE_TOOLS:
        binding = scope(role)
        tools = ScopedEvidenceTools(Session(None), binding, now=lambda: NOW).model_tools()
        assert {f.name for f in tools} == ROLE_TOOLS[role]
        for function in tools:
            serialized = json.dumps(function.parameters())
            assert "scope_handle" not in serialized
            assert "customer_id" not in serialized
            assert "tenant_id" not in serialized
            assert "request_id" not in serialized
        assert "a" * 43 not in repr(binding)


def test_scope_is_injected_outside_the_model_arguments():
    binding = scope()
    session = Session(result(binding))
    client = ScopedEvidenceTools(session, binding, now=lambda: NOW)
    response = asyncio.run(client.call("list_equipment_documents", {}))
    assert session.calls == [
        (SERVER_LABEL + "___list_equipment_documents", {"scope_handle": "a" * 43})
    ]
    assert response["request_id"] == str(binding.request_id)
    assert "scope_handle" not in response
    assert len(client.receipt_ids) == 1


@pytest.mark.parametrize(
    "role,name,arguments",
    [
        ("document_analyst", "list_equipment_documents", {}),
        ("document_analyst", "analyze_document", {"document_id": "DEMO-PT-001-CERTIFICATE-PDF"}),
        ("equipment_service", "get_equipment_record", {}),
        ("equipment_service", "retrieve_policy", {"query": "certificate release policy"}),
    ],
)
def test_agent_framework_invokes_local_wrappers_without_scope_in_results(role, name, arguments):
    binding = scope(role)
    session = Session(result(binding, name))
    client = ScopedEvidenceTools(session, binding, now=lambda: NOW)
    function = next(f for f in client.model_tools() if f.name == name)
    content = asyncio.run(function.invoke(arguments=arguments))
    serialized = json.dumps([item.to_dict() for item in content])
    assert str(binding.request_id) in serialized
    assert binding.scope_handle.get_secret_value() not in serialized
    assert session.calls == [(SERVER_LABEL + "___" + name, {**arguments, "scope_handle": "a" * 43})]


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("get_equipment_record", {}),
        ("send_email", {}),
        ("list_equipment_documents", {"scope_handle": "b" * 43}),
        ("list_equipment_documents", {"customer_id": "DEMO-NW"}),
        ("analyze_document", {"document_id": "https://foreign.example/document.pdf"}),
        ("analyze_document", {"document_id": "../../secret"}),
    ],
)
def test_denied_calls_never_reach_transport(name, arguments):
    session = Session(None)
    client = ScopedEvidenceTools(session, scope(), now=lambda: NOW)
    with pytest.raises(ValueError, match="must stop"):
        asyncio.run(client.call(name, arguments))
    assert session.calls == []
    assert client.failed


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": str(uuid4())},
        {"tenant_id": str(uuid4())},
        {"customer_id": "DEMO-NW"},
        {"equipment_id": "DEMO-PT-002"},
        {"specialist": "equipment_service"},
        {"tool_name": "analyze_document"},
        {"payload": {"scope_handle": "a" * 43}},
        {"payload": {"text": "x" * 50001}},
    ],
)
def test_misbound_or_unsafe_results_latch_failure(changes):
    binding = scope()
    session = Session(result(binding, **changes))
    client = ScopedEvidenceTools(session, binding, now=lambda: NOW)
    with pytest.raises(ValueError, match="must stop"):
        asyncio.run(client.call("list_equipment_documents", {}))
    session.response = result(binding)
    with pytest.raises(ValueError, match="must stop"):
        asyncio.run(client.call("list_equipment_documents", {}))
    assert len(session.calls) == 1


def test_errors_are_sanitized_and_never_retried():
    session = Session(RuntimeError("PRIVATE TOKEN AND SOURCE CONTENT"))
    client = ScopedEvidenceTools(session, scope(), now=lambda: NOW)
    with pytest.raises(ValueError, match="^Evidence tool failed; investigation must stop$"):
        asyncio.run(client.call("list_equipment_documents", {}))
    assert len(session.calls) == 1
    assert client.failed


def test_cancellation_latches_failure_without_retry():
    async def run():
        started = asyncio.Event()

        class SlowSession:
            async def call_tool(self, *args, **kwargs):
                started.set()
                await asyncio.Event().wait()

        client = ScopedEvidenceTools(SlowSession(), scope(), now=lambda: NOW)
        task = asyncio.create_task(client.call("list_equipment_documents", {}))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.failed
        with pytest.raises(ValueError, match="must stop"):
            await client.call("list_equipment_documents", {})
        assert client.calls == 1

    asyncio.run(run())


@pytest.mark.parametrize("role", ["document_analyst", "equipment_service"])
def test_simultaneous_model_tool_calls_serialize_without_broker_overlap(role):
    async def run():
        binding = scope(role)
        active, maximum = 0, 0
        names = []

        class Session:
            async def call_tool(self, name, arguments):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep(0)
                names.append(name.split("___")[1])
                active -= 1
                return result(binding, names[-1])

        client = ScopedEvidenceTools(Session(), binding, now=lambda: NOW)
        calls = (
            [
                ("analyze_document", {"document_id": "DEMO-CERT-001"}),
                ("analyze_document", {"document_id": "DEMO-SERVICE-001"}),
            ]
            if role == "document_analyst"
            else [("get_equipment_record", {}), ("retrieve_policy", {"query": "policy"})]
        )
        outputs = await asyncio.gather(*(client.call(name, args) for name, args in calls))
        assert maximum == 1
        assert names == [name for name, _ in calls]
        assert len(outputs) == len(client.receipt_ids) == client.calls == 2
        assert not client.failed

    asyncio.run(run())


def test_failed_predecessor_prevents_queued_call_from_reaching_transport():
    async def run():
        binding = scope("equipment_service")
        names = []

        class Session:
            async def call_tool(self, name, arguments):
                names.append(name)
                await asyncio.sleep(0)
                raise RuntimeError("source unavailable")

        client = ScopedEvidenceTools(Session(), binding, now=lambda: NOW)
        outcomes = await asyncio.gather(
            client.call("get_equipment_record", {}),
            client.call("retrieve_policy", {"query": "policy"}),
            return_exceptions=True,
        )
        assert all(isinstance(item, ValueError) for item in outcomes)
        assert len(names) == client.calls == 1
        assert client.failed and not client.receipt_ids

    asyncio.run(run())


def test_cancelling_queued_call_invalidates_predecessor_and_remaining_waiters():
    async def run():
        binding = scope("equipment_service")
        entered, release = asyncio.Event(), asyncio.Event()
        names = []

        class Session:
            async def call_tool(self, name, arguments):
                names.append(name)
                entered.set()
                await release.wait()
                return result(binding, name.split("___")[1])

        client = ScopedEvidenceTools(Session(), binding, now=lambda: NOW)
        first = asyncio.create_task(client.call("get_equipment_record", {}))
        await entered.wait()
        cancelled = asyncio.create_task(client.call("retrieve_policy", {"query": "policy"}))
        waiting = asyncio.create_task(client.call("retrieve_policy", {"query": "policy"}))
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        release.set()
        outcomes = await asyncio.gather(first, waiting, return_exceptions=True)
        assert all(isinstance(item, ValueError) for item in outcomes)
        assert len(names) == client.calls == 1
        assert client.failed and not client.receipt_ids

    asyncio.run(run())


@pytest.mark.parametrize("limit", ["expiry", "budget"])
def test_queued_calls_recheck_limits_after_lock_acquisition(limit):
    async def run():
        binding = scope("equipment_service")
        clock = [NOW]

        class Session:
            async def call_tool(self, name, arguments):
                await asyncio.sleep(0)
                return result(binding, name.split("___")[1])

        client = ScopedEvidenceTools(Session(), binding, now=lambda: clock[0])
        await client._call_lock.acquire()
        waiting = asyncio.create_task(client.call("get_equipment_record", {}))
        await asyncio.sleep(0)
        if limit == "expiry":
            clock[0] = binding.expires_at
        else:
            client.calls = 6
        client._call_lock.release()
        with pytest.raises(ValueError, match="must stop"):
            await waiting
        assert client.failed and not client.receipt_ids

    asyncio.run(run())


@pytest.mark.parametrize("query", ["", " ", "x" * 1001])
def test_invalid_policy_queries_never_reach_transport(query):
    session = Session(None)
    client = ScopedEvidenceTools(session, scope("equipment_service"), now=lambda: NOW)
    with pytest.raises(ValueError, match="must stop"):
        asyncio.run(client.call("retrieve_policy", {"query": query}))
    assert not session.calls


@pytest.mark.parametrize("is_error,structured", [(True, {}), (False, None), (False, {})])
def test_error_missing_or_malformed_envelopes_stop(is_error, structured):
    session = Session(
        types.CallToolResult(content=[], isError=is_error, structuredContent=structured)
    )
    client = ScopedEvidenceTools(session, scope(), now=lambda: NOW)
    with pytest.raises(ValueError, match="must stop"):
        asyncio.run(client.call("list_equipment_documents", {}))
    assert client.failed


def test_expiry_budget_and_duplicate_receipts_stop():
    async def run():
        binding = scope()
        session = Session(result(binding))
        expired = ScopedEvidenceTools(session, binding, now=lambda: binding.expires_at)
        with pytest.raises(ValueError):
            await expired.call("list_equipment_documents", {})
        assert not session.calls
        client = ScopedEvidenceTools(session, binding, now=lambda: NOW)
        await client.call("list_equipment_documents", {})
        with pytest.raises(ValueError):
            await client.call("list_equipment_documents", {})
        assert client.failed
        client = ScopedEvidenceTools(session, binding, now=lambda: NOW)
        for _ in range(6):
            session.response = result(binding)
            await client.call("list_equipment_documents", {})
        with pytest.raises(ValueError):
            await client.call("list_equipment_documents", {})
        assert len(client.receipt_ids) == 6

    asyncio.run(run())


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://offline-proof.services.ai.azure.com/api/projects/innexq/toolboxes/t/versions/1/mcp?api-version=v1",
        "https://attacker.example/api/projects/innexq/toolboxes/t/versions/1/mcp?api-version=v1",
        PROJECT + "/toolboxes/t/mcp?api-version=v1",
        ENDPOINT.replace("/innexq/", "/another/"),
        ENDPOINT + "&redirect=https://attacker.example",
        ENDPOINT + "#fragment",
    ],
)
def test_untrusted_or_unpinned_endpoints_are_rejected(endpoint):
    with pytest.raises(ValueError):
        validate_toolbox_endpoint(endpoint, PROJECT)


@pytest.mark.parametrize("manifest", ["extra", "missing", "duplicate", "paginated", "no_session"])
def test_manifest_drift_is_rejected_before_exposing_tools(monkeypatch, manifest):
    class Toolbox:
        def __init__(self, *args, **kwargs):
            self.session = None if manifest == "no_session" else self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def list_tools(self):
            names = [SERVER_LABEL + "___" + name for name in TOOL_NAMES]
            if manifest == "extra":
                names.append("send_email")
            elif manifest == "missing":
                names.pop()
            elif manifest == "duplicate":
                names.append(names[0])
            return types.ListToolsResult(
                tools=[types.Tool(name=name, inputSchema={"type": "object"}) for name in names],
                nextCursor="next" if manifest == "paginated" else None,
            )

    monkeypatch.setattr("evidence_toolbox.FoundryToolbox", Toolbox)

    async def run():
        with pytest.raises(ValueError, match="Evidence toolbox"):
            async with open_evidence_tools(None, ENDPOINT, PROJECT, scope()):
                pytest.fail("changed manifest must not expose tools")

    asyncio.run(run())


def test_diagnostics_never_include_provider_messages_headers_or_bodies(monkeypatch, caplog):
    from evidence_toolbox import failure_category

    secret = "PRIVATE-SCOPE-MARKER-MUST-NOT-APPEAR"  # pragma: allowlist secret - dummy test marker
    error = httpx.HTTPStatusError(
        secret,
        request=httpx.Request("POST", "https://example.invalid", headers={"secret": secret}),
        response=httpx.Response(403, text=secret),
    )
    assert failure_category(ExceptionGroup(secret, [error])) == "http_403"
    assert failure_category(Exception(secret)) == "transport_or_provider"
    assert failure_category(ValueError(secret)) == "validation"
    assert failure_category(TimeoutError(secret)) == "timeout"
    assert failure_category(ExceptionGroup(secret, [error, ValueError(secret)])) == "multiple"

    class Toolbox:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise error

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("evidence_toolbox.FoundryToolbox", Toolbox)

    async def run():
        with pytest.raises(httpx.HTTPStatusError):
            async with open_evidence_tools(None, ENDPOINT, PROJECT, scope()):
                pytest.fail("failed connection must not expose tools")

    asyncio.run(run())
    assert "phase=connect category=http_403" in caplog.text
    assert secret not in caplog.text


def test_actual_sdk_mcp_roundtrip_and_credential_propagation(monkeypatch):
    """Real FoundryToolbox + FastMCP via ASGI, with an offline credential only."""
    binding = scope(expires_at=datetime.now(UTC) + timedelta(minutes=5))
    seen = []
    token_requests = []
    # Only the in-process test server disables hostname/DNS-rebinding checks.
    server = FastMCP(
        "offline-proof",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/api/projects/innexq/toolboxes/evidence/versions/1/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    def register(name):
        @server.tool(name=SERVER_LABEL + "___" + name)
        def evidence(scope_handle: str) -> dict[str, Any]:
            if scope_handle != binding.scope_handle.get_secret_value():
                raise ValueError("scope denied")
            seen.append(name)
            return result(binding, name).structuredContent

    for name in TOOL_NAMES:
        register(name)
    app = server.streamable_http_app()

    class Credential:
        def get_token(self, *scopes, **kwargs):
            token_requests.append(scopes)
            return AccessToken("OFFLINE-NOT-A-REAL-CREDENTIAL", 9999999999)

    real_client = httpx.AsyncClient
    headers = []

    async def authenticated_app(scope, receive, send):
        if scope["type"] == "http":
            request_headers = dict(scope["headers"])
            headers.append(request_headers)
            assert request_headers[b"authorization"] == b"Bearer OFFLINE-NOT-A-REAL-CREDENTIAL"
        await app(scope, receive, send)

    def client(*args, **kwargs):
        return real_client(*args, transport=httpx.ASGITransport(app=authenticated_app), **kwargs)

    monkeypatch.setattr("agent_framework_foundry_hosting._toolbox.httpx.AsyncClient", client)

    async def run():
        async with server.session_manager.run():
            async with open_evidence_tools(Credential(), ENDPOINT, PROJECT, binding) as tools:
                response = await tools.call("list_equipment_documents", {})
                assert response["equipment_id"] == "DEMO-PT-001"

    asyncio.run(run())
    assert seen == ["list_equipment_documents"]
    assert token_requests and all(s == ("https://ai.azure.com/.default",) for s in token_requests)
    assert len(headers) >= 3

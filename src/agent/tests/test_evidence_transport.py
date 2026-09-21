"""Offline ingress proof; this does not prove deployed gateway forwarding."""

import asyncio
import json

import pytest

from evidence_transport import (
    HANDLE_HEADERS,
    MAX_BODY_BYTES,
    EvidenceHandleMiddleware,
    current_evidence_handles,
)

HEADERS = [
    (name, b"1" * 32 + b"." + role.encode() + b"." + b"a" * 43)
    for name, role in HANDLE_HEADERS.items()
]


async def invoke(app, *, headers=None, body=b'{"input":"inspect","stream":true}', **changes):
    messages = [
        {"type": "http.request", "body": body, "more_body": False},
        {"type": "http.disconnect"},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    await app(
        {
            "type": "http",
            "method": "POST",
            "path": "/responses",
            "headers": HEADERS if headers is None else headers,
            **changes,
        },
        receive,
        send,
    )
    return sent


def test_stream_lifetime_strip_and_defensive_copy():
    async def app(scope, receive, send):
        assert scope["headers"] == [(b"x-client-correlation", b"safe")]
        handles = current_evidence_handles()
        assert set(handles) == {"document_analyst", "equipment_service"}
        assert "a" * 43 not in repr(handles)
        handles.clear()
        assert len(current_evidence_handles()) == 2
        assert json.loads((await receive())["body"])["input"] == "inspect"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await asyncio.sleep(0)
        assert len(current_evidence_handles()) == 2
        await send({"type": "http.response.body", "body": b"safe"})
        assert (await receive())["type"] == "http.disconnect"

    async def check():
        sent = await invoke(
            EvidenceHandleMiddleware(app), headers=[*HEADERS, (b"x-client-correlation", b"safe")]
        )
        assert sent[0]["status"] == 200
        assert current_evidence_handles() == {}

    asyncio.run(check())


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_exception_and_cancellation_reset(failure):
    async def app(scope, receive, send):
        assert current_evidence_handles()
        raise failure()

    async def check():
        with pytest.raises(failure):
            await invoke(EvidenceHandleMiddleware(app))
        assert current_evidence_handles() == {}

    asyncio.run(check())


@pytest.mark.parametrize(
    "headers",
    [
        HEADERS[:1],
        HEADERS + HEADERS[:1],
        HEADERS + [(b"X-Client-InnexQ-Evidence-Unknown", b"a" * 43)],
        [(HEADERS[0][0], b"short"), HEADERS[1]],
        [(HEADERS[0][0], b"a" * 129), HEADERS[1]],
        [(HEADERS[0][0], b"a" * 43 + b"\n"), HEADERS[1]],
        [(HEADERS[0][0], b"a" * 42 + b"\xff"), HEADERS[1]],
        [(HEADERS[0][0], HEADERS[0][1].replace(b"1" * 32, b"2" * 32)), HEADERS[1]],
        [(HEADERS[0][0], HEADERS[1][1]), HEADERS[1]],
    ],
)
def test_invalid_headers_never_reach_sdk(headers):
    async def app(*args):
        pytest.fail("invalid request reached SDK")

    sent = asyncio.run(invoke(EvidenceHandleMiddleware(app), headers=headers))
    assert sent[0]["status"] == 400
    assert "a" * 43 not in repr(sent)


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"broken",
        b"\xff",
        b"x" * (MAX_BODY_BYTES + 1),
        b'{"background":true}',
        b'{"background":1}',
        b'{"conversation":null}',
        b'{"previous_response_id":"x"}',
        b'{"metadata":{}}',
        b'{"steer":false}',
    ],
    ids=[
        "array",
        "invalid-json",
        "encoding",
        "oversize",
        "background",
        "bg-int",
        "conversation",
        "history",
        "metadata",
        "steer",
    ],
)
def test_unsafe_request_modes_rejected(body):
    async def app(*args):
        pytest.fail("invalid request reached SDK")

    assert asyncio.run(invoke(EvidenceHandleMiddleware(app), body=body))[0]["status"] == 400


def test_legacy_and_non_http_passthrough_and_scope_isolation():
    async def app(scope, receive, send):
        assert current_evidence_handles() == {}
        await send({"type": "http.response.start", "status": 200})

    middleware = EvidenceHandleMiddleware(app)
    assert asyncio.run(invoke(middleware, headers=[], body=b"legacy"))[0]["status"] == 200
    assert asyncio.run(invoke(middleware, headers=[], type="lifespan"))[0]["status"] == 200


@pytest.mark.parametrize("changes", [{"method": "GET"}, {"path": "/other"}])
def test_scopes_only_on_response_creation(changes):
    async def app(*args):
        pytest.fail("invalid route reached SDK")

    assert asyncio.run(invoke(EvidenceHandleMiddleware(app), **changes))[0]["status"] == 400


def test_concurrent_requests_do_not_share_handles():
    async def app(scope, receive, send):
        initial = current_evidence_handles()["document_analyst"].get_secret_value()
        await asyncio.sleep(0)
        assert current_evidence_handles()["document_analyst"].get_secret_value() == initial

    async def check():
        middleware = EvidenceHandleMiddleware(app)
        await asyncio.gather(
            invoke(middleware),
            invoke(
                middleware,
                headers=[(name, value.replace(b"a" * 43, b"b" * 43)) for name, value in HEADERS],
            ),
        )
        assert not current_evidence_handles()

    asyncio.run(check())


@pytest.mark.parametrize("disconnect", [False, True])
def test_chunked_ingress_and_disconnect(disconnect):
    async def check():
        incoming = [
            {"type": "http.request", "body": b'{"input":', "more_body": True},
            {"type": "http.disconnect"}
            if disconnect
            else {"type": "http.request", "body": b'"inspect"}', "more_body": False},
        ]
        sent = []

        async def receive():
            return incoming.pop(0)

        async def send(message):
            sent.append(message)

        async def app(scope, receive, send):
            assert not disconnect
            assert json.loads((await receive())["body"]) == {"input": "inspect"}

        await EvidenceHandleMiddleware(app)(
            {"type": "http", "path": "/responses", "method": "POST", "headers": HEADERS},
            receive,
            send,
        )
        if disconnect:
            assert sent[0]["status"] == 400
        assert not current_evidence_handles()

    asyncio.run(check())


def test_installed_host_sees_no_secret_client_headers():
    import httpx
    from azure.ai.agentserver.responses import ResponsesAgentServerHost, TextResponse

    async def check():
        host = ResponsesAgentServerHost(configure_observability=None)
        host.add_middleware(EvidenceHandleMiddleware)

        @host.response_handler
        async def handler(request, context, cancellation_signal):
            assert not context.client_headers
            assert len(current_evidence_handles()) == 2
            assert "a" * 43 not in json.dumps(request)
            return TextResponse(context, request, text="offline proof")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=host), base_url="http://test"
        ) as client:
            result = await client.post(
                "/responses", headers=HEADERS, json={"input": "inspect", "store": False}
            )
        assert result.status_code == 200, result.text
        assert "offline proof" in result.text
        assert "a" * 43 not in result.text
        assert not current_evidence_handles()

    asyncio.run(check())

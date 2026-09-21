"""Non-model scope ingress using Foundry's documented x-client-* pass-through.

Install with host.add_middleware(EvidenceHandleMiddleware) before serving. This
must be outside any request/header instrumentation. Never log these headers at
the caller or gateway. This transport is not authentication: the broker still
validates every handle and its agent principal. No live forwarding is proven here.
"""

import json
import re
from contextvars import ContextVar

from pydantic import SecretStr
from starlette.types import ASGIApp, Receive, Scope, Send

HEADER_PREFIX = b"x-client-innexq-evidence-"
HANDLE_HEADERS = {
    HEADER_PREFIX + b"document-analyst": "document_analyst",
    HEADER_PREFIX + b"equipment-service": "equipment_service",
}
MAX_BODY_BYTES = 131_072
_handles: ContextVar[dict[str, SecretStr] | None] = ContextVar("evidence_handles", default=None)


def current_evidence_handles() -> dict[str, SecretStr]:
    """Return a defensive copy; never put this value in messages or session state."""
    return dict(_handles.get() or {})


class EvidenceHandleMiddleware:
    """Consume and strip secret headers before AgentServer logging/persistence.

    Scoped requests are single foreground investigations: no conversation/history,
    background replay or caller-controlled steering. Streaming is permitted. The
    host must also leave resilient_background and steerable_conversations disabled.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        handles: dict[str, SecretStr] = {}
        remaining = []
        invalid = False
        request_ids: set[bytes] = set()
        for name, value in scope.get("headers", []):
            normalized = name.lower()
            if not normalized.startswith(HEADER_PREFIX):
                remaining.append((name, value))
                continue
            role = HANDLE_HEADERS.get(normalized)
            match = (
                re.fullmatch(
                    rb"([a-f0-9]{32})\." + role.encode("ascii") + rb"\.([A-Za-z0-9_-]{43})",
                    value,
                )
                if role is not None
                else None
            )
            if role is None or role in handles or match is None:
                invalid = True
                continue
            request_ids.add(match.group(1))
            handles[role] = SecretStr(value.decode("ascii"))
        clean_scope = dict(scope)
        clean_scope["headers"] = remaining
        if invalid or (
            handles and (set(handles) != set(HANDLE_HEADERS.values()) or len(request_ids) != 1)
        ):
            await self._reject(send)
            return

        downstream_receive = receive
        if handles:
            if scope.get("method") != "POST" or scope.get("path") != "/responses":
                await self._reject(send)
                return
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    await self._reject(send)
                    return
                body.extend(message.get("body", b""))
                if len(body) > MAX_BODY_BYTES:
                    await self._reject(send)
                    return
                if not message.get("more_body", False):
                    break
            try:
                payload = json.loads(body)
                valid = (
                    isinstance(payload, dict)
                    and payload.get("background", False) is False
                    and not any(
                        key in payload
                        for key in ("conversation", "previous_response_id", "metadata", "steer")
                    )
                )
            except (ValueError, UnicodeDecodeError):
                valid = False
            if not valid:
                await self._reject(send)
                return
            delivered = False

            async def replay_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            downstream_receive = replay_receive

        token = _handles.set(handles)
        try:
            await self.app(clean_scope, downstream_receive, send)
        finally:
            _handles.reset(token)

    @staticmethod
    async def _reject(send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b'{"error":"Invalid evidence invocation"}'}
        )

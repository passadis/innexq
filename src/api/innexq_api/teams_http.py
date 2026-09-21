"""Observe Teams HTTP completion without reading tokens, activities or response bodies."""

import logging
from time import monotonic

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class TeamsResponseTelemetry:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("path") != "/api/messages"
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return
        started = monotonic()
        status = 0
        completed = False

        async def observed_send(message: Message) -> None:
            nonlocal status, completed
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True

        try:
            await self.app(scope, receive, observed_send)
        finally:
            # ASGI completion is not proof that the Teams client rendered the card.
            logging.getLogger("innexq.audit").info(
                "teams_http_response",
                extra={
                    "http_status": status,
                    "response_completed": completed,
                    "elapsed_ms": round((monotonic() - started) * 1000),
                },
            )

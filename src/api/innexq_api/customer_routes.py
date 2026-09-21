"""Customer-only transport. Trusted identity and controller own every boundary."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from innexq_contracts.customer_conversation import CustomerMessage, CustomerReply
from innexq_contracts.customer_status import CustomerCertificateStatus
from innexq_contracts.models import StrictContract
from pydantic import Field

from innexq_api.auth import EntraAuth
from innexq_api.certificates import EvidenceUnavailable
from innexq_api.config import Settings
from innexq_api.controller import Denied
from innexq_api.store import Conflict


class CustomerRequest(StrictContract):
    request_id: UUID
    equipment_id: str = Field(pattern=r"^DEMO-[A-Z0-9-]+$", max_length=80)
    prompt: str = Field(min_length=1, max_length=1000)


class CustomerRuntime(Protocol):
    def catalog(self, tenant_id: UUID, actor_id: UUID) -> dict[str, Any]: ...
    def request(self, tenant_id: UUID, actor_id: UUID, body: CustomerRequest) -> dict[str, str]: ...
    def status(self, tenant_id: UUID, actor_id: UUID, request_id: UUID) -> dict[str, str]: ...
    def download(self, tenant_id: UUID, actor_id: UUID, request_id: UUID) -> bytes: ...
    def message(self, tenant_id: UUID, actor_id: UUID, body: CustomerMessage) -> CustomerReply: ...
    def confirm(self, tenant_id: UUID, actor_id: UUID, message_id: UUID) -> dict[str, str]: ...


class ConfirmMessage(StrictContract):
    """No customer-provided target, policy or authority fields are accepted."""


def customer_app(
    settings: Settings, auth: EntraAuth, runtime: Callable[[], CustomerRuntime | None]
) -> FastAPI:
    app = FastAPI(
        title="InnexQ Customer Portal API", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.customer_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def private(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def customer(request: Request) -> tuple[UUID, UUID]:
        tenant, actor = auth.customer(request)
        return UUID(tenant), UUID(actor)

    def service() -> CustomerRuntime:
        value = runtime()
        if value is None:
            raise HTTPException(503, "Certificate Fulfilment is not available")
        return value

    app.state.customer_dependency = customer
    Identity = Annotated[tuple[UUID, UUID], Depends(customer)]

    @app.exception_handler(Denied)
    @app.exception_handler(KeyError)
    async def unavailable(_request: Request, _exc: Exception) -> JSONResponse:
        # Same public response for unknown and foreign IDs; never echo evidence.
        return JSONResponse(status_code=404, content={"detail": "Request not available"})

    @app.exception_handler(Conflict)
    async def changed(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "Refresh the request status"})

    @app.exception_handler(EvidenceUnavailable)
    @app.exception_handler(Exception)
    async def failure(_request: Request, _exc: Exception) -> JSONResponse:
        # The outer server-error handler can bypass ordinary response middleware.
        return JSONResponse(
            status_code=503,
            content={"detail": "Certificate Fulfilment is not available"},
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    def public_status(value: dict[str, str]) -> dict[str, str]:
        public = {
            key: value[key]
            for key in ("request_id", "status", "message", "case_status", "updated_at")
        }
        return CustomerCertificateStatus.model_validate(public).model_dump(mode="json")

    @app.get("/catalog")
    def catalog(identity: Identity) -> dict[str, Any]:
        return service().catalog(*identity)

    @app.post("/requests")
    def submit(body: CustomerRequest, identity: Identity) -> dict[str, str]:
        return public_status(service().request(*identity, body))

    @app.post("/messages", response_model=CustomerReply)
    def message(body: CustomerMessage, identity: Identity) -> CustomerReply:
        return service().message(*identity, body)

    @app.post("/messages/{message_id}/confirm")
    def confirm(message_id: UUID, body: ConfirmMessage, identity: Identity) -> dict[str, str]:
        return public_status(service().confirm(*identity, message_id))

    @app.get("/requests/{request_id}")
    def status(request_id: UUID, identity: Identity) -> dict[str, str]:
        return public_status(service().status(*identity, request_id))

    @app.get("/requests/{request_id}/pdf")
    def download(request_id: UUID, identity: Identity) -> Response:
        pdf = service().download(*identity, request_id)
        return Response(
            pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="innexq-{request_id}.pdf"',
                "Content-Security-Policy": "sandbox; default-src 'none'",
            },
        )

    return app

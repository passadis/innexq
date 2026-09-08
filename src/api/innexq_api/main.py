"""Authenticated Phase 1 adapters around the deterministic workflow controller."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from innexq_contracts.events import RunEvent, RunRecord
from innexq_contracts.models import StrictContract
from innexq_contracts.transitions import InvalidTransition
from pydantic import Field

from innexq_api.auth import EntraAuth
from innexq_api.config import Settings
from innexq_api.controller import CONTRACT_ID, Controller, Denied
from innexq_api.store import Conflict


class DetectRequest(StrictContract):
    contract_id: str = CONTRACT_ID


class PricingRequest(StrictContract):
    run_id: UUID
    correlation_id: UUID
    contract_id: str


class RevisionRequest(StrictContract):
    revision: int = Field(ge=1)


def create_app(settings: Settings | None = None, controller: Controller | None = None) -> FastAPI:
    config = settings or Settings()
    auth = EntraAuth(config)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        credential = None
        if application.state.controller is None and config.cosmos_endpoint:
            from innexq_api.adapters import FoundryAgent, GraphExecutor, workload_credential
            from innexq_api.store import CosmosStore
            from innexq_api.teams import TeamsApprovals
            from innexq_api.telemetry import configure_telemetry

            credential = workload_credential(config)
            configure_telemetry(credential)
            store = CosmosStore(
                config.cosmos_endpoint, credential, config.cosmos_database, config.cosmos_container
            )
            store.ping()
            teams = TeamsApprovals(config, application, store)
            runtime_controller = Controller(
                config,
                store,
                FoundryAgent(config, credential),
                GraphExecutor(config, credential),
                teams,
            )
            teams.bind(runtime_controller)
            application.state.controller = runtime_controller
            await teams.initialize()
        try:
            yield
        finally:
            if credential is not None:
                credential.close()

    application = FastAPI(title="InnexQ", version="0.1.0", lifespan=lifespan)
    application.state.controller = controller
    application.state.auth = auth

    def runtime() -> Controller:
        value: Controller | None = application.state.controller
        if value is None:
            raise HTTPException(503, "workflow dependencies are not configured")
        return value

    def user(request: Request) -> tuple[str, str]:
        return auth.user(request)

    def agent(request: Request) -> None:
        auth.agent(request)

    application.state.user_dependency = user
    application.state.agent_dependency = agent
    User = Annotated[tuple[str, str], Depends(user)]
    Key = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)]

    @application.exception_handler(Denied)
    async def denied_handler(_request: Request, exc: Denied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @application.exception_handler(Conflict)
    @application.exception_handler(InvalidTransition)
    async def conflict_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "Run revision or state changed"})

    @application.exception_handler(KeyError)
    async def missing_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Run not found"})

    @application.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready")
    def ready() -> dict[str, str]:
        value = runtime()
        required = (
            config.api_audience,
            config.agent_principal_id,
            config.foundry_project_endpoint,
            config.graph_drive_id,
            config.graph_folder_id,
        )
        if not all(required):
            raise HTTPException(503, "workflow dependencies are not configured")
        try:
            value.store.ping()
            reference = value.store.get_teams_reference()
        except Exception as exc:
            raise HTTPException(503, "workflow dependency unavailable") from exc
        if reference is None:
            raise HTTPException(503, "authorized Teams channel setup required")
        return {"status": "ready"}

    @application.get("/privacy", response_class=PlainTextResponse)
    def privacy() -> str:
        return (
            "InnexQ synthetic hackathon demo. Authorized user identifiers, decisions and Run "
            "audit records are stored in the configured Azure tenant. Use synthetic business "
            "data only. Contact the application owner for access and retention requests."
        )

    @application.get("/terms", response_class=PlainTextResponse)
    def terms() -> str:
        return (
            "InnexQ is a hackathon test, not a production service or commercial offer. "
            "An authorized human must approve the displayed action package before execution."
        )

    @application.post("/api/runs/detect", response_model=RunRecord)
    def detect(body: DetectRequest, identity: User, idempotency_key: Key) -> RunRecord:
        if body.contract_id != CONTRACT_ID:
            raise Denied("contract is outside the configured Workflow Pack fixture")
        return runtime().detect(*identity, idempotency_key)

    @application.get("/api/runs", response_model=list[RunRecord])
    def list_runs(identity: User) -> list[RunRecord]:
        return runtime().store.list_runs(identity[1])

    @application.get("/api/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: UUID, identity: User) -> RunRecord:
        record = runtime().store.get(run_id)
        if record.run.owner_user_id != identity[1]:
            raise Denied("Run belongs to another actor")
        return record

    @application.post("/api/runs/{run_id}/assemble", response_model=RunRecord)
    async def assemble(
        run_id: UUID, body: RevisionRequest, identity: User, idempotency_key: Key
    ) -> RunRecord:
        return await runtime().assemble(run_id, *identity, body.revision, idempotency_key)

    @application.post("/api/runs/{run_id}/request-approval", response_model=RunRecord)
    async def approval(
        run_id: UUID, body: RevisionRequest, identity: User, idempotency_key: Key
    ) -> RunRecord:
        return await runtime().request_approval(run_id, *identity, body.revision, idempotency_key)

    @application.get("/api/runs/{run_id}/events", response_model=list[RunEvent])
    def events(run_id: UUID, identity: User) -> list[RunEvent]:
        get_run(run_id, identity)
        return runtime().store.events(run_id)

    @application.post("/api/tools/pricing", dependencies=[Depends(agent)])
    def pricing(body: PricingRequest) -> dict[str, str]:
        return runtime().pricing(body.run_id, body.correlation_id, body.contract_id)

    @application.post("/api/demo/reset")
    def reset(identity: User, idempotency_key: Key) -> dict[str, str]:
        # A fresh attempt namespace, never deletion or an authorization shortcut.
        namespace = uuid5(NAMESPACE_URL, f"innexq-reset:{identity}:{idempotency_key}")
        return {"attempt_key": str(namespace), "mode": "fresh-attempt-preserve-audit"}

    return application


app = create_app()

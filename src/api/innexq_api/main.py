"""Authenticated Phase 1 adapters around the deterministic workflow controller."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from dataclasses import asdict
from typing import Annotated, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from innexq_contracts.case_review import CaseCommand, CaseReview
from innexq_contracts.events import RunEvent, RunRecord
from innexq_contracts.models import StrictContract
from innexq_contracts.transitions import InvalidTransition
from pydantic import Field
from starlette.types import Receive, Scope, Send

from innexq_api.auth import EntraAuth
from innexq_api.case_review import CaseReviewController
from innexq_api.config import Settings
from innexq_api.controller import CONTRACT_ID, Controller, Denied
from innexq_api.coverage_controller import CoverageAuthorizationError
from innexq_api.coverage_review import CoverageDecisionCommand, CoverageReviewService
from innexq_api.customer_routes import CustomerRuntime, customer_app
from innexq_api.store import Conflict
from innexq_api.teams_http import TeamsResponseTelemetry


class DetectRequest(StrictContract):
    contract_id: str = CONTRACT_ID


class PricingRequest(StrictContract):
    run_id: UUID
    correlation_id: UUID
    contract_id: str


class RevisionRequest(StrictContract):
    revision: int = Field(ge=1)


class EmployeeCors(CORSMiddleware):
    """Customer app has its own CORS policy; never add employee origins to it."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("path", "").startswith("/api/customer/"):
            await self.app(scope, receive, send)
        elif scope.get("path", "").startswith(
            ("/api/operations/certificates/", "/api/operations/coverage/")
        ):
            # Case writes only, not a POST grant on legacy Runs or customer routes.
            await CORSMiddleware(
                self.app,
                allow_origins=self.allow_origins,
                allow_methods=["GET", "POST"],
                allow_headers=["Authorization", "Content-Type"],
                allow_credentials=False,
            )(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


def create_app(
    settings: Settings | None = None,
    controller: Controller | None = None,
    certificates: CustomerRuntime | None = None,
) -> FastAPI:
    config = settings or Settings()
    auth = EntraAuth(config)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        credential = None
        reader_credential = None
        notification_task = None
        coverage_task = None
        evidence_stack = AsyncExitStack()
        try:
            if application.state.controller is None and config.cosmos_endpoint:
                from innexq_api.adapters import FoundryAgent, GraphExecutor, workload_credential
                from innexq_api.store import CosmosStore
                from innexq_api.teams import TeamsApprovals
                from innexq_api.telemetry import configure_telemetry

                credential = workload_credential(config)
                configure_telemetry(credential)
                store = CosmosStore(
                    config.cosmos_endpoint,
                    credential,
                    config.cosmos_database,
                    config.cosmos_container,
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
                if config.certificates_enabled:
                    from azure.identity import ManagedIdentityCredential

                    from innexq_api.certificate_notifications import CertificateNotifications
                    from innexq_api.certificate_repository import PrivateCertificateRepository
                    from innexq_api.certificate_runtime import (
                        CertificateApplication,
                        HostedCertificateTeam,
                    )
                    from innexq_api.certificate_store import CosmosCertificateStore
                    from innexq_api.document_extraction import DocumentIntelligenceExtractor

                    if not config.customer_bindings or not config.customer_origins:
                        raise ValueError("explicit customer identity and origin bindings required")
                    if (
                        not config.certificate_reader_client_id
                        or config.certificate_reader_client_id == config.managed_identity_client_id
                    ):
                        raise ValueError(
                            "certificate retrieval requires a separate managed identity"
                        )
                    reader_credential = ManagedIdentityCredential(
                        client_id=config.certificate_reader_client_id
                    )
                    certificate_store = CosmosCertificateStore(store.container)
                    coverage_customer = None
                    if config.renewal_enabled:
                        from innexq_api.adapters import CoverageBlobStorage
                        from innexq_api.coverage_controller import CoverageController
                        from innexq_api.coverage_customer import CoverageCustomerRuntime
                        from innexq_api.coverage_executor import CoverageExecutor
                        from innexq_api.coverage_runner import CoverageExecutionRunner
                        from innexq_api.coverage_sources import (
                            FixtureCoverageInvestigator,
                            FixtureCoverageSourceReader,
                        )
                        from innexq_api.coverage_store import CosmosCoverageStore

                        coverage_container = store.client.get_database_client(
                            config.cosmos_database
                        ).get_container_client(config.renewal_coverage_container)
                        coverage_store = CosmosCoverageStore(coverage_container)
                        coverage_reader = FixtureCoverageSourceReader(
                            config.renewal_scenarios_path, config.renewal_policy_path
                        )
                        coverage_controller = CoverageController(
                            coverage_store,
                            coverage_reader,
                            operations_object_id=config.renewal_operations_object_id,
                            manager_object_id=config.renewal_manager_object_id,
                        )
                        coverage_executor = CoverageExecutor(
                            coverage_store,
                            CoverageBlobStorage(config, credential),
                            coverage_reader,
                        )
                        application.state.coverage_review = CoverageReviewService(
                            coverage_controller
                        )
                        coverage_customer = CoverageCustomerRuntime(
                            coverage_controller,
                            FixtureCoverageInvestigator(coverage_reader),
                            coverage_executor,
                        )
                        coverage_task = asyncio.create_task(
                            CoverageExecutionRunner(
                                coverage_store, coverage_controller, coverage_executor
                            ).run()
                        )
                    application.state.certificates = CertificateApplication(
                        config,
                        PrivateCertificateRepository(
                            config.certificate_blob_endpoint,
                            config.certificate_container,
                            reader_credential,
                        ),
                        DocumentIntelligenceExtractor(
                            config.document_intelligence_endpoint, reader_credential
                        ),
                        HostedCertificateTeam(config, credential),
                        certificate_store,
                        coverage=coverage_customer,
                    )
                    application.state.certificate_store = certificate_store
                    if config.evidence_broker_enabled:
                        from innexq_api.evidence_setup import configure_evidence

                        evidence_app, evidence_server = configure_evidence(
                            config,
                            application.state.certificates,
                            auth,
                            store.container,
                            credential,
                        )
                        await evidence_stack.enter_async_context(
                            evidence_server.session_manager.run()
                        )
                        application.mount("/api/evidence", evidence_app)
                    notifications = CertificateNotifications(
                        certificate_store,
                        teams,
                        UUID(config.tenant_id),
                        UUID(config.approver_user_id),
                    )
                    notification_task = asyncio.create_task(notifications.run())
            yield
        finally:
            try:
                if notification_task is not None:
                    notification_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await notification_task
                if coverage_task is not None:
                    coverage_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await coverage_task
            finally:
                try:
                    await evidence_stack.aclose()
                finally:
                    try:
                        if reader_credential is not None:
                            reader_credential.close()
                    finally:
                        if credential is not None:
                            credential.close()

    application = FastAPI(title="InnexQ", version="0.1.0", lifespan=lifespan)
    application.add_middleware(TeamsResponseTelemetry)
    application.add_middleware(
        EmployeeCors,
        allow_origins=config.web_origins,
        allow_methods=["GET"],
        allow_headers=["Authorization"],
        allow_credentials=False,
    )
    application.state.controller = controller
    application.state.auth = auth
    application.state.certificates = certificates
    application.state.certificate_store = None
    application.state.coverage_review = None
    application.mount(
        "/api/customer", customer_app(config, auth, lambda: application.state.certificates)
    )

    @application.middleware("http")
    async def private_run_responses(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith(("/api/runs", "/api/customer", "/api/operations")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    def runtime() -> Controller:
        value: Controller | None = application.state.controller
        if value is None:
            raise HTTPException(503, "workflow dependencies are not configured")
        return value

    def user(request: Request) -> tuple[str, str]:
        return auth.user(request)

    def agent(request: Request) -> None:
        auth.agent(request)

    def case_operator(request: Request) -> tuple[str, str]:
        return auth.case_operator(request)

    def coverage_operator(request: Request) -> tuple[str, str]:
        return auth.coverage_operator(request)

    def review_controller() -> CaseReviewController:
        store = application.state.certificate_store
        if store is None:
            raise HTTPException(503, "Certificate Fulfilment is not available")
        return CaseReviewController(store, UUID(config.tenant_id), UUID(config.approver_user_id))

    def coverage_review() -> CoverageReviewService:
        value: CoverageReviewService | None = application.state.coverage_review
        if value is None:
            raise HTTPException(503, "Service Coverage Renewal is not available")
        return value

    application.state.user_dependency = user
    application.state.agent_dependency = agent
    User = Annotated[tuple[str, str], Depends(user)]
    CaseOperator = Annotated[tuple[str, str], Depends(case_operator)]
    CoverageOperator = Annotated[tuple[str, str], Depends(coverage_operator)]
    Key = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)]

    @application.exception_handler(Denied)
    async def denied_handler(_request: Request, exc: Denied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @application.exception_handler(CoverageAuthorizationError)
    async def coverage_denied_handler(_request: Request, _exc: Exception) -> JSONResponse:
        # Sanitized refusal; the audit record keeps the internal reason.
        return JSONResponse(status_code=403, content={"detail": "Decision not authorized"})

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
        return runtime().store.list_runs(config.approver_user_id)

    @application.get("/api/operations/certificates")
    def operation_cases(identity: User) -> list[dict[str, Any]]:
        store = application.state.certificate_store
        if store is None:
            raise HTTPException(503, "Certificate Fulfilment is not available")
        records = store.list_operations_cases(UUID(identity[0]), UUID(config.approver_user_id))
        return [
            {
                "record": record.model_dump(mode="json"),
                "notification": asdict(store.get_notification(record.request_id)),
            }
            for record in records
        ]

    @application.get("/api/operations/certificates/{request_id}/review")
    def case_review(request_id: UUID, identity: User) -> dict[str, Any]:
        return {
            "review": review_controller().read(request_id).model_dump(mode="json"),
            "can_manage": identity[1] == config.approver_user_id,
        }

    @application.post(
        "/api/operations/certificates/{request_id}/actions", response_model=CaseReview
    )
    def case_action(request_id: UUID, body: CaseCommand, identity: CaseOperator) -> CaseReview:
        return review_controller().act(request_id, UUID(identity[0]), UUID(identity[1]), body)

    @application.get("/api/operations/coverage")
    def coverage_list(identity: User) -> list[dict[str, Any]]:
        return coverage_review().list()

    @application.get("/api/operations/coverage/{request_id}/review")
    def coverage_read(request_id: UUID, identity: User) -> dict[str, Any]:
        return coverage_review().read(request_id)

    @application.post("/api/operations/coverage/{request_id}/operations-decision")
    def coverage_operations_decision(
        request_id: UUID, body: CoverageDecisionCommand, identity: CoverageOperator
    ) -> dict[str, Any]:
        return coverage_review().operations(request_id, identity[1], body).model_dump(mode="json")

    @application.post("/api/operations/coverage/{request_id}/manager-decision")
    def coverage_manager_decision(
        request_id: UUID, body: CoverageDecisionCommand, identity: CoverageOperator
    ) -> dict[str, Any]:
        return coverage_review().manager(request_id, identity[1], body).model_dump(mode="json")

    @application.get("/api/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: UUID, identity: User) -> RunRecord:
        record = runtime().store.get(run_id)
        if record.run.owner_user_id != config.approver_user_id:
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

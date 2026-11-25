"""Customer surface for coverage renewal: intents, confirmation, coarse public progress."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from innexq_api.controller import Denied
from innexq_api.coverage_customer import CoverageCustomerRuntime
from innexq_contracts.coverage_renewal import CoverageRenewalRecord, CoverageRenewalState
from innexq_contracts.customer_conversation import CustomerReply
from innexq_contracts.customer_status import CustomerCoverageProgress
from pydantic import ValidationError

from tests.unit.test_coverage_controller import facts
from tests.unit.test_coverage_controller import setup as controller_setup
from tests.unit.test_coverage_eligibility import FIXTURE, scenario
from tests.unit.test_customer_conversation import conversation, message
from tests.unit.test_customer_routes import ACTOR, TENANT, Runtime
from tests.unit.test_customer_routes import setup as routes_setup

INTERNAL_WORDS = ("missing_evidence", "hold_reasons", "conflicting", "sha256", "package_hash")


class Investigator:
    fail = False

    def investigate(self, record: CoverageRenewalRecord):
        if self.fail:
            raise RuntimeError("agent investigation unavailable")
        data = next(
            item for item in FIXTURE["scenarios"] if item["equipment_id"] == record.equipment_id
        )
        return facts(data), (), str(data["annual_coverage_price"])


def runtime() -> tuple[CoverageCustomerRuntime, Investigator, Any]:
    controller, store, _ = controller_setup()
    investigator = Investigator()
    return CoverageCustomerRuntime(controller, investigator), investigator, store


def test_confirmed_start_runs_the_pipeline_and_reports_generic_progress() -> None:
    service, _, store = runtime()
    data = scenario("expired_eligible")
    request_id = uuid4()
    result = service.start(data["customer_id"], data["equipment_id"], request_id)
    progress = CustomerCoverageProgress.model_validate(result)
    assert progress.request_id == request_id
    assert progress.progress == "Awaiting Operations"
    assert "Nothing has been charged or issued" in progress.message
    record, _ = store.get(request_id)
    assert record.state == CoverageRenewalState.AWAITING_OPERATIONS_APPROVAL
    assert record.package is not None


def test_duplicate_confirmation_is_idempotent() -> None:
    service, _, store = runtime()
    data = scenario("expired_eligible")
    request_id = uuid4()
    first = service.start(data["customer_id"], data["equipment_id"], request_id)
    revision = store.get(request_id)[0].revision
    again = service.start(data["customer_id"], data["equipment_id"], request_id)
    assert again == first
    assert store.get(request_id)[0].revision == revision


def test_failed_investigation_holds_safely_with_no_internal_reasons_exposed() -> None:
    service, investigator, store = runtime()
    investigator.fail = True
    data = scenario("expired_eligible")
    request_id = uuid4()
    result = service.start(data["customer_id"], data["equipment_id"], request_id)
    assert result["progress"] == "Held or rejected"
    assert not any(word in result["message"] for word in INTERNAL_WORDS)
    record, _ = store.get(request_id)
    assert record.state == CoverageRenewalState.EVIDENCE_HOLD
    assert record.hold_reasons == ("missing_evidence",)
    assert record.package is None


def test_progress_never_confirms_foreign_or_unknown_requests() -> None:
    service, _, _ = runtime()
    data = scenario("expired_eligible")
    request_id = uuid4()
    service.start(data["customer_id"], data["equipment_id"], request_id)
    with pytest.raises(KeyError):
        service.progress("DEMO-SOMEONE-ELSE", request_id)
    with pytest.raises(KeyError):
        service.progress(data["customer_id"], uuid4())


def test_runtime_lists_coverage_equipment_for_scope_bridging() -> None:
    service, _, _ = runtime()
    equipment = service.equipment("DEMO-FAB")
    assert "DEMO-COV-001" in equipment
    assert all(item.startswith("DEMO-COV-") for item in equipment)
    assert service.equipment("DEMO-NOBODY") == ()


class Port:
    """Conversation-level double for the coverage customer runtime."""

    def __init__(
        self, result: str = "renewal_required", equipment: tuple[str, ...] = ("DEMO-COV-001",)
    ) -> None:
        self.result = result
        self._equipment = equipment
        self.started: list[tuple[str, str, UUID]] = []
        self.progress_calls = 0

    def outcome(self, customer_id: str, equipment_id: str) -> str:
        return self.result

    def equipment(self, customer_id: str) -> tuple[str, ...]:
        return self._equipment

    def start(self, customer_id: str, equipment_id: str, request_id: UUID) -> dict[str, Any]:
        self.started.append((customer_id, equipment_id, request_id))
        return self._progress(request_id)

    def progress(self, customer_id: str, request_id: UUID) -> dict[str, Any]:
        self.progress_calls += 1
        if not any(entry[2] == request_id for entry in self.started):
            raise KeyError(str(request_id))
        return self._progress(request_id)

    @staticmethod
    def _progress(request_id: UUID) -> dict[str, Any]:
        return {
            "request_id": str(request_id),
            "progress": "Awaiting Operations",
            "message": "Your renewal proposal is awaiting Operations review.",
            "updated_at": "2026-09-22T12:00:00Z",
        }


def test_renewal_intent_requires_explicit_confirmation_then_starts_once() -> None:
    app, _, _, _, _, _, _ = conversation("coverage_renewal")
    port = Port()
    app.coverage = port
    body = message("Renew the service coverage for PT-001")
    reply = app.message(TENANT, ACTOR, body)
    assert reply.kind == "confirmation_required" and reply.can_confirm
    assert reply.intent == "coverage_renewal"
    assert port.started == []
    result = app.confirm(TENANT, ACTOR, body.message_id)
    assert result["progress"] == "Awaiting Operations"
    assert port.started == [("DEMO-FAB", "DEMO-PT-001", body.message_id)]
    assert app.confirm(TENANT, ACTOR, body.message_id) == result
    assert len(port.started) == 1


def test_current_coverage_answers_without_a_confirmable_proposal() -> None:
    app, _, _, _, _, _, _ = conversation("service_document_request")
    app.coverage = Port("existing_pdf")
    body = message("Send me the coverage document for PT-001")
    reply = app.message(TENANT, ACTOR, body)
    assert reply.kind == "answer" and not reply.can_confirm
    assert "is current" in reply.message
    with pytest.raises(Denied):
        app.confirm(TENANT, ACTOR, body.message_id)


def test_unavailable_coverage_reports_generically_and_pack_absence_is_unsupported() -> None:
    app, _, _, _, _, _, _ = conversation("coverage_renewal")
    app.coverage = Port("unavailable")
    unavailable = app.message(TENANT, ACTOR, message("Renew coverage for PT-001"))
    assert unavailable.kind == "answer"
    assert "could not verify" in unavailable.message
    assert not any(word in unavailable.message for word in INTERNAL_WORDS)
    app.coverage = None
    absent = app.message(TENANT, ACTOR, message("Renew coverage for PT-001"))
    assert absent.kind == "unsupported" and not absent.can_confirm


def test_coverage_only_equipment_is_bridged_into_customer_scope() -> None:
    app, _, _, _, _, _, packets = conversation("coverage_renewal", equipment="DEMO-COV-001")
    app.coverage = Port()
    reply = app.message(TENANT, ACTOR, message("Renew coverage for COV-001"))
    assert reply.kind == "confirmation_required" and reply.can_confirm
    assert reply.equipment_id == "DEMO-COV-001"
    assert "DEMO-COV-001" in packets[0]["equipment_ids"]


def test_reply_contract_rejects_confirmable_replies_outside_scoped_intents() -> None:
    with pytest.raises(ValidationError):
        CustomerReply(
            message_id=uuid4(),
            intent="service_document_request",
            equipment_id="DEMO-PT-001",
            kind="confirmation_required",
            can_confirm=True,
            message="not allowed",
        )


class CoverageRoute(Runtime):
    def coverage_progress(
        self, tenant_id: UUID, actor_id: UUID, request_id: UUID
    ) -> dict[str, Any]:
        self.check(tenant_id, actor_id)
        return Port._progress(request_id) | {"internal_note": "must never leave the API"}


def test_coverage_progress_route_returns_only_the_public_contract() -> None:
    client = routes_setup(CoverageRoute())
    request_id = uuid4()
    response = client.get(f"/coverage/{request_id}")
    assert response.status_code == 200
    assert set(response.json()) == {"request_id", "progress", "message", "updated_at"}
    assert "internal_note" not in response.text


def test_coverage_progress_route_maps_unknown_to_not_available() -> None:
    runtime = CoverageRoute()
    runtime.error = KeyError("unknown")
    client = routes_setup(runtime)
    response = client.get(f"/coverage/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Request not available"}


class _Store:
    def __init__(self, record: CoverageRenewalRecord) -> None:
        self._record = record

    def get(self, request_id: UUID) -> tuple[CoverageRenewalRecord, str]:
        return self._record, "etag"


class _Controller:
    def __init__(self, record: CoverageRenewalRecord) -> None:
        self.store = _Store(record)


class _Executor:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str]] = []

    def download(self, request_id: UUID, kind: str) -> bytes:
        self.calls.append((request_id, kind))
        return b"%PDF-1.4 issued coverage"


def _record(state: CoverageRenewalState, customer_id: str = "DEMO-FAB") -> CoverageRenewalRecord:
    moment = datetime(2026, 9, 22, tzinfo=UTC)
    return CoverageRenewalRecord(
        request_id=uuid4(),
        state=state,
        customer_id=customer_id,
        equipment_id="DEMO-COV-001",
        created_at=moment,
        updated_at=moment,
    )


def test_customer_download_returns_the_issued_certificate_when_completed() -> None:
    record = _record(CoverageRenewalState.COMPLETED)
    executor = _Executor()
    service = CoverageCustomerRuntime(_Controller(record), Investigator(), executor)
    pdf = service.download(record.customer_id, record.request_id)
    assert pdf.startswith(b"%PDF")
    assert executor.calls == [(record.request_id, "certificate")]


def test_customer_download_hides_foreign_requests() -> None:
    record = _record(CoverageRenewalState.COMPLETED)
    service = CoverageCustomerRuntime(_Controller(record), Investigator(), _Executor())
    with pytest.raises(KeyError):
        service.download("DEMO-SOMEONE-ELSE", record.request_id)


def test_customer_download_requires_a_completed_renewal() -> None:
    record = _record(CoverageRenewalState.EXECUTING)
    service = CoverageCustomerRuntime(_Controller(record), Investigator(), _Executor())
    with pytest.raises(KeyError):
        service.download(record.customer_id, record.request_id)


def test_customer_download_is_unavailable_without_an_executor() -> None:
    record = _record(CoverageRenewalState.COMPLETED)
    service = CoverageCustomerRuntime(_Controller(record), Investigator())
    with pytest.raises(KeyError):
        service.download(record.customer_id, record.request_id)

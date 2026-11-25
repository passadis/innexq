"""Coverage renewal controller: transitions, holds and the two-person gate."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from innexq_api.coverage_controller import (
    CoverageAuthorizationError,
    CoverageController,
    public_progress,
)
from innexq_api.coverage_store import CosmosCoverageStore
from innexq_api.store import Conflict
from innexq_contracts.coverage_renewal import (
    CoverageEvidenceSources,
    CoverageRenewalState,
    CoverageSourceFact,
    compute_package_hash,
)

from tests.unit.test_certificate_store import Container
from tests.unit.test_coverage_eligibility import FIXTURE, NOW, scenario, sources_for

OPERATIONS_OID = "11111111-1111-1111-1111-111111111111"
MANAGER_OID = "22222222-2222-2222-2222-222222222222"


class CoverageContainer(Container):
    """The base fake predates partition-scoped queries used by the events log."""

    def query_items(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        parameters = {item["name"]: item["value"] for item in kwargs["parameters"]}
        if "@partition" in parameters:
            self.queries.append({"query": query} | kwargs)
            return [
                deepcopy(doc)
                for (partition, _), doc in self.items.items()
                if partition == parameters["@partition"]
            ]
        if "@item" in parameters:
            self.queries.append({"query": query} | kwargs)
            return [
                deepcopy(doc)
                for (_, item), doc in self.items.items()
                if item == parameters["@item"]
            ]
        return super().query_items(query, **kwargs)


class Reader:
    """Fixture-driven trusted source adapter."""

    def __init__(self) -> None:
        self.overrides: dict[tuple[str, str], CoverageEvidenceSources] = {}

    def _scenario(self, customer_id: str, equipment_id: str) -> dict[str, Any]:
        return next(
            item
            for item in FIXTURE["scenarios"]
            if item["equipment_id"] == equipment_id and item["customer_id"] == customer_id
        )

    def sources(self, customer_id: str, equipment_id: str) -> CoverageEvidenceSources:
        if (customer_id, equipment_id) in self.overrides:
            return self.overrides[customer_id, equipment_id]
        try:
            return sources_for(self._scenario(customer_id, equipment_id))
        except StopIteration:
            return CoverageEvidenceSources()

    def base_amount(self, customer_id: str, equipment_id: str) -> str:
        return str(self._scenario(customer_id, equipment_id)["annual_coverage_price"])

    def customer_name(self, customer_id: str) -> str:
        return "Fabrikam Industrial AB" if customer_id == "DEMO-FAB" else "Northwind Logistics"

    def equipment_ids(self, customer_id: str) -> tuple[str, ...]:
        return tuple(
            item["equipment_id"]
            for item in FIXTURE["scenarios"]
            if item["customer_id"] == customer_id
        )


def facts(data: dict[str, Any]) -> tuple[CoverageSourceFact, ...]:
    document = data["document"]
    return (
        CoverageSourceFact(
            document_id=document["document_id"],
            document_version=document["document_version"],
            sha256=document["sha256"],
            label="coverage_until",
            value=document["coverage_until"],
            page=1,
        ),
    )


def setup(clock: datetime = NOW) -> tuple[CoverageController, CosmosCoverageStore, Container]:
    container = CoverageContainer()
    store = CosmosCoverageStore(container)
    controller = CoverageController(
        store,
        Reader(),
        operations_object_id=OPERATIONS_OID,
        manager_object_id=MANAGER_OID,
        now=lambda: clock,
    )
    return controller, store, container


def awaiting_operations(controller: CoverageController) -> UUID:
    data = scenario("expired_eligible")
    record = controller.start_renewal(data["customer_id"], data["equipment_id"])
    controller.begin_investigation(record.request_id)
    result = controller.verify_eligibility(
        record.request_id, facts(data), (), data["annual_coverage_price"]
    )
    assert result.state == CoverageRenewalState.AWAITING_OPERATIONS_APPROVAL
    return record.request_id


def test_expired_eligible_reaches_operations_with_a_hashed_package() -> None:
    controller, store, _ = setup()
    request_id = awaiting_operations(controller)
    record, _ = store.get(request_id)
    assert record.package is not None and record.package_hash is not None
    assert record.package_hash == compute_package_hash(record.package)
    assert record.package.quote.base_amount == "8500.00"
    assert record.package.quote.total_amount == "10540.00"
    assert record.package.invoice_preview.notice.startswith("SYNTHETIC DEMO")
    assert public_progress(record) == "Awaiting Operations"
    types = [event["event_type"] for event in store.events(request_id)]
    assert types == [
        "coverage.customer_requested",
        "coverage.evidence_assembling",
        "coverage.eligibility_verified",
        "coverage.package_drafted",
        "coverage.awaiting_operations",
    ]


def test_current_coverage_returns_the_existing_pdf_path() -> None:
    controller, _, _ = setup()
    data = scenario("current_coverage")
    assert (
        controller.document_request_outcome(data["customer_id"], data["equipment_id"])
        == "existing_pdf"
    )
    expired = scenario("expired_eligible")
    assert (
        controller.document_request_outcome(expired["customer_id"], expired["equipment_id"])
        == "renewal_required"
    )


def test_missing_or_foreign_documents_are_unavailable() -> None:
    controller, _, _ = setup()
    missing = scenario("missing_evidence")
    assert (
        controller.document_request_outcome(missing["customer_id"], missing["equipment_id"])
        == "unavailable"
    )
    assert controller.document_request_outcome("DEMO-SOMEONE", "DEMO-COV-001") == "unavailable"
    safety = scenario("non_renewable_safety_document")
    assert (
        controller.document_request_outcome(safety["customer_id"], safety["equipment_id"])
        == "unavailable"
    )


def test_failed_checks_hold_without_a_package_or_invoice() -> None:
    controller, _store, _ = setup()
    data = scenario("non_renewable_safety_document")
    record = controller.start_renewal(data["customer_id"], data["equipment_id"])
    controller.begin_investigation(record.request_id)
    held = controller.verify_eligibility(record.request_id, facts(data), (), None)
    assert held.state == CoverageRenewalState.EVIDENCE_HOLD
    assert "non_renewable_document" in held.hold_reasons
    assert held.package is None and held.package_hash is None
    assert public_progress(held) == "Held or rejected"


def test_cited_quote_drift_holds_safely() -> None:
    controller, _, _ = setup()
    data = scenario("expired_eligible")
    record = controller.start_renewal(data["customer_id"], data["equipment_id"])
    controller.begin_investigation(record.request_id)
    held = controller.verify_eligibility(record.request_id, facts(data), (), "9999.00")
    assert held.state == CoverageRenewalState.EVIDENCE_HOLD
    assert held.hold_reasons == ("conflicting_evidence",)


def test_two_person_approval_authorizes_execution() -> None:
    controller, _store, _ = setup()
    request_id = awaiting_operations(controller)
    after_ops = controller.operations_decide(request_id, OPERATIONS_OID, "approve")
    assert after_ops.state == CoverageRenewalState.AWAITING_MANAGER_APPROVAL
    assert public_progress(after_ops) == "Awaiting Manager"
    approved = controller.manager_decide(request_id, MANAGER_OID, "approve")
    assert approved.state == CoverageRenewalState.MANAGER_APPROVED
    executing = controller.authorize_execution(request_id)
    assert executing.state == CoverageRenewalState.EXECUTING
    assert public_progress(executing) == "Issuing documents"


def test_wrong_identities_and_sequence_are_refused() -> None:
    controller, _, _ = setup()
    request_id = awaiting_operations(controller)
    with pytest.raises(CoverageAuthorizationError, match="Operations identity"):
        controller.operations_decide(request_id, MANAGER_OID, "approve")
    with pytest.raises(CoverageAuthorizationError, match="no manager decision"):
        controller.manager_decide(request_id, MANAGER_OID, "approve")
    controller.operations_decide(request_id, OPERATIONS_OID, "approve")
    with pytest.raises(CoverageAuthorizationError, match="Manager identity"):
        controller.manager_decide(request_id, OPERATIONS_OID, "approve")
    with pytest.raises(CoverageAuthorizationError, match="not authorized"):
        controller.authorize_execution(request_id)


def test_rejections_are_terminal_and_customer_facing_generic() -> None:
    controller, _, _ = setup()
    request_id = awaiting_operations(controller)
    rejected = controller.operations_decide(
        request_id, OPERATIONS_OID, "reject", reject_reason="pricing doubt"
    )
    assert rejected.state == CoverageRenewalState.OPERATIONS_REJECTED
    assert public_progress(rejected) == "Held or rejected"
    with pytest.raises(CoverageAuthorizationError):
        controller.manager_decide(request_id, MANAGER_OID, "approve")


def test_manager_rejection_stops_execution() -> None:
    controller, _, _ = setup()
    request_id = awaiting_operations(controller)
    controller.operations_decide(request_id, OPERATIONS_OID, "approve")
    rejected = controller.manager_decide(
        request_id, MANAGER_OID, "reject", reject_reason="hold for audit"
    )
    assert rejected.state == CoverageRenewalState.MANAGER_REJECTED
    with pytest.raises(CoverageAuthorizationError):
        controller.authorize_execution(request_id)


def test_tampered_stored_package_blocks_execution() -> None:
    controller, _store, container = setup()
    request_id = awaiting_operations(controller)
    controller.operations_decide(request_id, OPERATIONS_OID, "approve")
    controller.manager_decide(request_id, MANAGER_OID, "approve")
    partition = f"coverage:{request_id}"
    snapshot = container.items[partition, "coverage-snapshot"]
    snapshot["record"]["package"]["quote"]["base_amount"] = "0.01"
    snapshot["record"]["package"]["quote"]["vat_amount"] = "0.00"
    snapshot["record"]["package"]["quote"]["total_amount"] = "0.01"
    snapshot["record"]["package"]["invoice_preview"]["line_items"][0]["unit_amount"] = "0.01"
    snapshot["record"]["package"]["invoice_preview"]["line_items"][0]["line_amount"] = "0.01"
    snapshot["record"]["package"]["invoice_preview"]["subtotal"] = "0.01"
    snapshot["record"]["package"]["invoice_preview"]["vat_amount"] = "0.00"
    snapshot["record"]["package"]["invoice_preview"]["total_amount"] = "0.01"
    with pytest.raises(CoverageAuthorizationError, match="not authorized"):
        controller.authorize_execution(request_id)


def test_identical_configured_identities_are_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="distinct"):
        CoverageController(
            CosmosCoverageStore(Container()),
            Reader(),
            operations_object_id=OPERATIONS_OID,
            manager_object_id=OPERATIONS_OID.upper(),
        )


def test_store_guards_revision_conflicts_and_identity() -> None:
    controller, store, _container = setup()
    data = scenario("expired_eligible")
    record = controller.start_renewal(data["customer_id"], data["equipment_id"])
    with pytest.raises(Conflict):
        store.create(record)
    fetched, etag = store.get(record.request_id)
    updated = fetched.model_copy(
        update={
            "state": CoverageRenewalState.EVIDENCE_ASSEMBLING,
            "revision": 1,
            "updated_at": NOW + timedelta(seconds=1),
        }
    )
    store.commit(updated, "coverage.evidence_assembling", etag)
    with pytest.raises(Conflict):
        store.commit(updated, "coverage.evidence_assembling", etag)
    with pytest.raises(KeyError):
        store.get(uuid4())
    with pytest.raises(Conflict, match="revision zero"):
        store.create(updated)


def test_invoice_reservation_is_unique_and_bounded() -> None:
    _, store, _ = setup()
    number = store.reserve_invoice_number(2026, 1)
    assert number == "SYN-INV-2026-00001"
    with pytest.raises(Conflict):
        store.reserve_invoice_number(2026, 1)
    assert store.reserve_invoice_number(2026, 2) == "SYN-INV-2026-00002"
    with pytest.raises(ValueError, match="numbering policy"):
        store.reserve_invoice_number(2026, 0)
    with pytest.raises(ValueError, match="numbering policy"):
        store.reserve_invoice_number(1999, 1)


def test_stale_sources_hold_even_after_confirmation() -> None:
    late = datetime(2028, 1, 1, tzinfo=UTC)
    controller, _, _ = setup(clock=late)
    data = scenario("expired_eligible")
    record = controller.start_renewal(data["customer_id"], data["equipment_id"])
    controller.begin_investigation(record.request_id)
    held = controller.verify_eligibility(record.request_id, facts(data), (), None)
    assert held.state == CoverageRenewalState.EVIDENCE_HOLD
    assert "stale_evidence" in held.hold_reasons

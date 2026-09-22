"""Service Coverage Renewal controller: the only owner of renewal state transitions.

Agents propose; this controller validates deterministically; Operations and a
distinct Manager authorize; only then may the executor (Increment 10) act.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from innexq_contracts.coverage_renewal import (
    CoverageEvidenceSources,
    CoverageRenewalRecord,
    CoverageRenewalState,
    CoverageSourceFact,
    CoverageToolReceipt,
    InvoiceLineItem,
    InvoicePreview,
    ManagerDecision,
    OperationsDecision,
    PreviousDocumentRef,
    RenewalPackage,
    approvals_authorize_execution,
    assert_coverage_transition,
    compute_package_hash,
)
from innexq_contracts.customer_status import CoveragePublicProgress
from innexq_gateway.coverage import (
    COVERAGE_MONTHS,
    calculate_renewal_quote,
    coverage_is_current,
    evaluate_renewal_eligibility,
)

from innexq_api.coverage_documents import (
    CERTIFICATE_TEMPLATE_VERSION,
    INVOICE_TEMPLATE_VERSION,
)
from innexq_api.coverage_store import CosmosCoverageStore

PUBLIC_PROGRESS: dict[CoverageRenewalState, CoveragePublicProgress] = {
    CoverageRenewalState.CUSTOMER_REQUESTED: "Evidence review",
    CoverageRenewalState.EVIDENCE_ASSEMBLING: "Evidence review",
    CoverageRenewalState.ELIGIBILITY_VERIFIED: "Evidence review",
    CoverageRenewalState.PACKAGE_DRAFTED: "Awaiting Operations",
    CoverageRenewalState.AWAITING_OPERATIONS_APPROVAL: "Awaiting Operations",
    CoverageRenewalState.OPERATIONS_APPROVED: "Awaiting Manager",
    CoverageRenewalState.AWAITING_MANAGER_APPROVAL: "Awaiting Manager",
    CoverageRenewalState.MANAGER_APPROVED: "Issuing documents",
    CoverageRenewalState.EXECUTING: "Issuing documents",
    CoverageRenewalState.COMPLETED: "Completed",
    CoverageRenewalState.EVIDENCE_HOLD: "Held or rejected",
    CoverageRenewalState.OPERATIONS_REJECTED: "Held or rejected",
    CoverageRenewalState.MANAGER_REJECTED: "Held or rejected",
    CoverageRenewalState.EXECUTION_FAILED: "Held or rejected",
    CoverageRenewalState.CANCELLED: "Held or rejected",
}


class CoverageAuthorizationError(PermissionError):
    """Sanitized refusal; internal reasons stay in the record, not the response."""


class CoverageSourceReader(Protocol):
    """Trusted adapter: supplies verified sources, never model output."""

    def sources(self, customer_id: str, equipment_id: str) -> CoverageEvidenceSources: ...

    def equipment_ids(self, customer_id: str) -> tuple[str, ...]: ...

    def base_amount(self, customer_id: str, equipment_id: str) -> str: ...

    def customer_name(self, customer_id: str) -> str: ...


def public_progress(record: CoverageRenewalRecord) -> CoveragePublicProgress:
    return PUBLIC_PROGRESS[record.state]


class CoverageController:
    def __init__(
        self,
        store: CosmosCoverageStore,
        reader: CoverageSourceReader,
        *,
        operations_object_id: str,
        manager_object_id: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if operations_object_id.casefold() == manager_object_id.casefold():
            raise ValueError("Operations and Manager must be distinct configured identities")
        self.store, self.reader, self.now = store, reader, now
        self.operations_object_id = operations_object_id
        self.manager_object_id = manager_object_id

    # -- customer request behaviour -------------------------------------------------

    def document_request_outcome(
        self, customer_id: str, equipment_id: str
    ) -> Literal["existing_pdf", "renewal_required", "unavailable"]:
        """'Give me the service PDF': current -> existing PDF; expired -> renewal offer."""

        sources = self.reader.sources(customer_id, equipment_id)
        document = sources.document
        if (
            document is None
            or sources.ownership is None
            or sources.ownership.customer_id != customer_id
            or document.customer_id != customer_id
            or document.document_type != "service_coverage_certificate"
        ):
            return "unavailable"
        if coverage_is_current(document, self.now()):
            return "existing_pdf"
        return "renewal_required"

    def start_renewal(
        self, customer_id: str, equipment_id: str, request_id: UUID | None = None
    ) -> CoverageRenewalRecord:
        """Called only after explicit customer confirmation; intent, not issuance."""

        now = self.now()
        record = CoverageRenewalRecord(
            request_id=request_id if request_id is not None else uuid4(),
            state=CoverageRenewalState.CUSTOMER_REQUESTED,
            customer_id=customer_id,
            equipment_id=equipment_id,
            created_at=now,
            updated_at=now,
        )
        self.store.create(record)
        return record

    # -- evidence and eligibility ---------------------------------------------------

    def _advance(
        self,
        record: CoverageRenewalRecord,
        etag: str,
        target: CoverageRenewalState,
        event_type: str,
        **changes: object,
    ) -> CoverageRenewalRecord:
        assert_coverage_transition(record.state, target)
        updated = record.model_copy(
            update={
                "state": target,
                "revision": record.revision + 1,
                "updated_at": self.now(),
                **changes,
            }
        )
        self.store.commit(updated, event_type, etag)
        return updated

    def begin_investigation(self, request_id: UUID) -> CoverageRenewalRecord:
        record, etag = self.store.get(request_id)
        return self._advance(
            record, etag, CoverageRenewalState.EVIDENCE_ASSEMBLING, "coverage.evidence_assembling"
        )

    def hold_investigation(self, request_id: UUID) -> CoverageRenewalRecord:
        """Investigation could not complete; stop safely without drafting anything."""

        record, etag = self.store.get(request_id)
        return self._advance(
            record,
            etag,
            CoverageRenewalState.EVIDENCE_HOLD,
            "coverage.evidence_hold",
            hold_reasons=("missing_evidence",),
        )

    def verify_eligibility(
        self,
        request_id: UUID,
        source_facts: tuple[CoverageSourceFact, ...],
        tool_receipts: tuple[CoverageToolReceipt, ...],
        cited_base_amount: str | None,
    ) -> CoverageRenewalRecord:
        """Deterministic checks over trusted sources; agent output never decides."""

        record, etag = self.store.get(request_id)
        sources = self.reader.sources(record.customer_id, record.equipment_id)
        decision = evaluate_renewal_eligibility(
            record.customer_id, record.equipment_id, sources, self.now()
        )
        if decision.outcome != "eligible":
            reasons = tuple(check.reason for check in decision.checks if check.verdict != "pass")
            return self._advance(
                record,
                etag,
                CoverageRenewalState.EVIDENCE_HOLD,
                "coverage.evidence_hold",
                hold_reasons=reasons,
            )
        base_amount = self.reader.base_amount(record.customer_id, record.equipment_id)
        # A cited agent quote is evidence only; drift against the register holds safely.
        if cited_base_amount is not None and cited_base_amount != base_amount:
            return self._advance(
                record,
                etag,
                CoverageRenewalState.EVIDENCE_HOLD,
                "coverage.evidence_hold",
                hold_reasons=("conflicting_evidence",),
            )
        verified = self._advance(
            record, etag, CoverageRenewalState.ELIGIBILITY_VERIFIED, "coverage.eligibility_verified"
        )
        return self._draft_package(
            verified, decision, sources, source_facts, tool_receipts, base_amount
        )

    def _draft_package(
        self,
        record: CoverageRenewalRecord,
        decision: object,
        sources: CoverageEvidenceSources,
        source_facts: tuple[CoverageSourceFact, ...],
        tool_receipts: tuple[CoverageToolReceipt, ...],
        base_amount: str,
    ) -> CoverageRenewalRecord:
        from innexq_contracts.coverage_renewal import (
            CoverageExecutionAction,
            CoverageExecutionManifest,
            EligibilityDecision,
        )

        assert isinstance(decision, EligibilityDecision)  # noqa: S101 - internal invariant
        document = sources.document
        ownership = sources.ownership
        if document is None or ownership is None:
            raise CoverageAuthorizationError("verified sources required to draft a package")
        quote = calculate_renewal_quote(base_amount)
        preview = InvoicePreview(
            currency=quote.currency,
            line_items=(
                InvoiceLineItem(
                    description=(
                        f"Service coverage renewal, {COVERAGE_MONTHS} months, {record.equipment_id}"
                    ),
                    quantity=1,
                    unit_amount=quote.base_amount,
                    line_amount=quote.base_amount,
                ),
            ),
            subtotal=quote.base_amount,
            vat_rate_percent=quote.vat_rate_percent,
            vat_amount=quote.vat_amount,
            total_amount=quote.total_amount,
        )
        request_hex = record.request_id.hex
        manifest = CoverageExecutionManifest(
            manifest_id=uuid4(),
            request_id=record.request_id,
            package_version=1,
            actions=(
                CoverageExecutionAction(
                    action_id=uuid4(),
                    action_type="allocate_invoice_number",
                    parameters={"format": "SYN-INV-{year}-{sequence:05d}"},
                    idempotency_key=f"invoice-{request_hex}",
                ),
                CoverageExecutionAction(
                    action_id=uuid4(),
                    action_type="render_coverage_certificate",
                    parameters={"template_version": CERTIFICATE_TEMPLATE_VERSION},
                    idempotency_key=f"certificate-{request_hex}",
                ),
                CoverageExecutionAction(
                    action_id=uuid4(),
                    action_type="render_invoice",
                    parameters={"template_version": INVOICE_TEMPLATE_VERSION},
                    idempotency_key=f"invoice-pdf-{request_hex}",
                ),
                CoverageExecutionAction(
                    action_id=uuid4(),
                    action_type="store_artifacts",
                    parameters={"container": "issued-coverage"},
                    idempotency_key=f"store-{request_hex}",
                ),
                CoverageExecutionAction(
                    action_id=uuid4(),
                    action_type="publish_customer_download",
                    parameters={},
                    idempotency_key=f"publish-{request_hex}",
                ),
                CoverageExecutionAction(
                    action_id=uuid4(),
                    action_type="send_notification",
                    parameters={"channel": "customer_portal"},
                    idempotency_key=f"notify-{request_hex}",
                ),
            ),
        )
        package = RenewalPackage(
            request_id=record.request_id,
            package_version=1,
            customer_id=record.customer_id,
            equipment_id=record.equipment_id,
            serial_number=ownership.serial_number,
            previous_document=PreviousDocumentRef(
                document_id=document.document_id,
                document_version=document.document_version,
                sha256=document.sha256,
            ),
            source_facts=source_facts,
            eligibility=decision,
            coverage_months=COVERAGE_MONTHS,
            quote=quote,
            invoice_preview=preview,
            certificate_preview_sha256=document.sha256,
            invoice_preview_sha256=document.sha256,
            certificate_template_version=CERTIFICATE_TEMPLATE_VERSION,
            invoice_template_version=INVOICE_TEMPLATE_VERSION,
            execution_manifest=manifest,
            tool_receipts=tool_receipts,
        )
        current, etag = self.store.get(record.request_id)
        self._advance(
            current,
            etag,
            CoverageRenewalState.PACKAGE_DRAFTED,
            "coverage.package_drafted",
            package=package,
            package_hash=compute_package_hash(package),
        )
        current, etag = self.store.get(record.request_id)
        return self._advance(
            current,
            etag,
            CoverageRenewalState.AWAITING_OPERATIONS_APPROVAL,
            "coverage.awaiting_operations",
        )

    # -- two-person approval --------------------------------------------------------

    def operations_decide(
        self,
        request_id: UUID,
        actor_object_id: str,
        decision: Literal["approve", "reject"],
        *,
        note_sha256: str | None = None,
        reject_reason: str | None = None,
    ) -> CoverageRenewalRecord:
        record, etag = self.store.get(request_id)
        if actor_object_id.casefold() != self.operations_object_id.casefold():
            raise CoverageAuthorizationError("only the configured Operations identity may decide")
        if record.state != CoverageRenewalState.AWAITING_OPERATIONS_APPROVAL:
            raise CoverageAuthorizationError("no operations decision is awaited")
        if record.package is None or record.package_hash is None:
            raise CoverageAuthorizationError("a frozen package is required")
        recorded = OperationsDecision(
            decision_id=uuid4(),
            request_id=request_id,
            package_version=record.package.package_version,
            package_hash=record.package_hash,
            actor_object_id=actor_object_id,
            decision=decision,
            note_sha256=note_sha256,
            reject_reason=reject_reason,
            submitted_at=self.now(),
        )
        if decision == "reject":
            return self._advance(
                record,
                etag,
                CoverageRenewalState.OPERATIONS_REJECTED,
                "coverage.operations_rejected",
                operations_decision=recorded,
            )
        self._advance(
            record,
            etag,
            CoverageRenewalState.OPERATIONS_APPROVED,
            "coverage.operations_approved",
            operations_decision=recorded,
        )
        current, etag = self.store.get(request_id)
        return self._advance(
            current,
            etag,
            CoverageRenewalState.AWAITING_MANAGER_APPROVAL,
            "coverage.awaiting_manager",
        )

    def manager_decide(
        self,
        request_id: UUID,
        actor_object_id: str,
        decision: Literal["approve", "reject"],
        *,
        reject_reason: str | None = None,
    ) -> CoverageRenewalRecord:
        record, etag = self.store.get(request_id)
        if actor_object_id.casefold() != self.manager_object_id.casefold():
            raise CoverageAuthorizationError("only the configured Manager identity may decide")
        if record.state != CoverageRenewalState.AWAITING_MANAGER_APPROVAL:
            raise CoverageAuthorizationError("no manager decision is awaited")
        operations = record.operations_decision
        if record.package is None or record.package_hash is None or operations is None:
            raise CoverageAuthorizationError(
                "a frozen package and operations decision are required"
            )
        if actor_object_id.casefold() == operations.actor_object_id.casefold():
            raise CoverageAuthorizationError("self-approval is forbidden")
        recorded = ManagerDecision(
            decision_id=uuid4(),
            request_id=request_id,
            package_version=record.package.package_version,
            package_hash=record.package_hash,
            actor_object_id=actor_object_id,
            decision=decision,
            operations_decision_id=operations.decision_id,
            operations_note_sha256=operations.note_sha256,
            reject_reason=reject_reason,
            submitted_at=self.now(),
        )
        if decision == "reject":
            return self._advance(
                record,
                etag,
                CoverageRenewalState.MANAGER_REJECTED,
                "coverage.manager_rejected",
                manager_decision=recorded,
            )
        return self._advance(
            record,
            etag,
            CoverageRenewalState.MANAGER_APPROVED,
            "coverage.manager_approved",
            manager_decision=recorded,
        )

    def authorize_execution(self, request_id: UUID) -> CoverageRenewalRecord:
        """Final deterministic gate before the executor; fails closed on any drift."""

        record, etag = self.store.get(request_id)
        if (
            record.state != CoverageRenewalState.MANAGER_APPROVED
            or record.package is None
            or record.package_hash is None
            or record.operations_decision is None
            or record.manager_decision is None
            or record.package_hash != compute_package_hash(record.package)
            or not approvals_authorize_execution(
                record.package,
                record.package_hash,
                record.operations_decision,
                record.manager_decision,
            )
        ):
            raise CoverageAuthorizationError("execution is not authorized")
        return self._advance(record, etag, CoverageRenewalState.EXECUTING, "coverage.executing")

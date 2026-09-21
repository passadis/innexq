"""Controller-only certificate decisions; adapters are required, never auto-faked."""

import hashlib
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid5

from innexq_contracts.case_review import CaseReview
from innexq_contracts.certificates import (
    CertificateArtifact,
    CertificateAuditEvent,
    CertificateCheck,
    CertificateDecision,
    CertificateOperationsCase,
    CertificateRequestRecord,
    CertificateSources,
    HoldReason,
)
from innexq_contracts.customer_conversation import CustomerRequestContext
from innexq_contracts.customer_status import CustomerCertificateStatus
from innexq_contracts.hashing import canonical_json_bytes
from innexq_gateway.certificates import evaluate_certificate

from innexq_api.controller import Denied
from innexq_api.store import Conflict


class EvidenceUnavailable(RuntimeError):
    """Adapters normalize inaccessible, missing or failed evidence reads to this."""


class CertificateEvidenceReader(Protocol):
    def read(self, customer_id: str, equipment_id: str) -> CertificateSources: ...


class ExistingPdfReader(Protocol):
    def read(self, customer_id: str, artifact: CertificateArtifact) -> bytes: ...


class CertificateStore(Protocol):
    def get(self, request_id: UUID) -> CertificateRequestRecord: ...

    def get_review(self, request_id: UUID) -> CaseReview | None: ...

    def commit(self, record: CertificateRequestRecord, expected_events: int) -> None:
        """Atomically persist snapshot, new audit events and embedded Operations case.

        Raise Conflict if expected_events differs from stored event count (zero
        means create-only). No upsert or partial case/audit commit is acceptable.
        """
        ...


def decision_hash(
    request_id: UUID,
    tenant_id: UUID,
    actor_id: UUID,
    customer_id: str,
    equipment_id: str,
    decision: CertificateDecision,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "request_id": str(request_id),
                "tenant_id": str(tenant_id),
                "actor_id": str(actor_id),
                "customer_id": customer_id,
                "equipment_id": equipment_id,
                "decision": decision.model_dump(mode="json"),
            }
        )
    ).hexdigest()


class CertificateController:
    """Call only with tenant/actor claims already verified by the HTTP auth adapter."""

    def __init__(
        self,
        tenant_id: UUID,
        customer_bindings: Mapping[UUID, str],
        operations_user_id: UUID,
        evidence: CertificateEvidenceReader,
        pdfs: ExistingPdfReader,
        store: CertificateStore,
        now: Callable[[], datetime],
        request_context: CustomerRequestContext | None = None,
    ) -> None:
        if operations_user_id in customer_bindings:
            raise ValueError("Operations cannot be a customer identity")
        if any(not value.strip() for value in customer_bindings.values()):
            raise ValueError("customer bindings cannot be blank")
        self.tenant_id = tenant_id
        self.customer_bindings = dict(customer_bindings)
        self.operations_user_id = operations_user_id
        self.evidence = evidence
        self.pdfs = pdfs
        self.store = store
        self.now = now
        self.request_context = request_context

    def _customer(self, tenant_id: UUID, actor_id: UUID) -> str:
        if tenant_id != self.tenant_id or actor_id not in self.customer_bindings:
            raise Denied("customer is not assigned to this workflow")
        return self.customer_bindings[actor_id]

    def _existing(
        self, tenant_id: UUID, actor_id: UUID, customer_id: str, request_id: UUID
    ) -> CertificateRequestRecord:
        record = self.store.get(request_id)
        if (record.tenant_id, record.actor_user_id, record.customer_id) != (
            tenant_id,
            actor_id,
            customer_id,
        ):
            raise Denied("request is not available")
        expected = decision_hash(
            request_id, tenant_id, actor_id, customer_id, record.equipment_id, record.decision
        )
        if record.decision_hash != expected:
            raise Denied("stored certificate decision is inconsistent")
        return record

    def _evaluate(self, customer_id: str, equipment_id: str) -> CertificateDecision:
        try:
            sources = self.evidence.read(customer_id, equipment_id)
        except EvidenceUnavailable:
            sources = CertificateSources()
        return evaluate_certificate(customer_id, equipment_id, sources, self.now())

    def _record(
        self,
        request_id: UUID,
        actor_id: UUID,
        customer_id: str,
        equipment_id: str,
        decision: CertificateDecision,
        prior: CertificateRequestRecord | None = None,
        download_prepared: bool = False,
    ) -> CertificateRequestRecord:
        events = list(prior.events) if prior else []

        def event(kind: str) -> None:
            events.append(
                CertificateAuditEvent.model_validate(
                    {
                        "sequence": len(events) + 1,
                        "event_type": kind,
                        "occurred_at": decision.evaluated_at,
                    }
                )
            )

        if prior is None:
            event("certificate.requested")
        event("certificate.policy_checked")
        operations_case = None
        if decision.outcome == "operations_required":
            event("certificate.held")
            operations_case = CertificateOperationsCase(
                case_id=uuid5(request_id, "certificate-operations"),
                assigned_user_id=self.operations_user_id,
                reason_codes=tuple(
                    dict.fromkeys(item.reason for item in decision.checks if item.verdict != "pass")
                ),
            )
            event("operations.case_created")
        else:
            event(
                "certificate.download_prepared"
                if download_prepared
                else "certificate.release_ready"
            )
        return CertificateRequestRecord(
            request_id=request_id,
            tenant_id=self.tenant_id,
            actor_user_id=actor_id,
            customer_id=customer_id,
            equipment_id=equipment_id,
            request_context=prior.request_context if prior else self.request_context,
            decision=decision,
            decision_hash=decision_hash(
                request_id, self.tenant_id, actor_id, customer_id, equipment_id, decision
            ),
            operations_case=operations_case,
            events=tuple(events),
        )

    def request(
        self, tenant_id: UUID, actor_id: UUID, equipment_id: str, request_id: UUID
    ) -> CertificateRequestRecord:
        customer_id = self._customer(tenant_id, actor_id)
        if not equipment_id.strip():
            raise Denied("equipment target is required")
        try:
            existing = self._existing(tenant_id, actor_id, customer_id, request_id)
        except KeyError:
            existing = None
        if existing is not None:
            if (
                self.request_context is not None
                and existing.request_context != self.request_context
            ):
                raise Denied("request identifier already has different customer context")
            if existing.equipment_id != equipment_id:
                raise Denied("request identifier already has a different target")
            return existing
        record = self._record(
            request_id,
            actor_id,
            customer_id,
            equipment_id,
            self._evaluate(customer_id, equipment_id),
        )
        try:
            self.store.commit(record, expected_events=0)
        except Conflict:
            # A concurrent winner may only be returned for the identical request.
            winner = self._existing(tenant_id, actor_id, customer_id, request_id)
            if self.request_context is not None and winner.request_context != self.request_context:
                raise Denied("request identifier already has different customer context") from None
            if winner.equipment_id != equipment_id:
                raise Denied("request identifier already has a different target") from None
            return winner
        return record

    def download(self, tenant_id: UUID, actor_id: UUID, request_id: UUID) -> bytes:
        customer_id = self._customer(tenant_id, actor_id)
        record = self._existing(tenant_id, actor_id, customer_id, request_id)
        if record.decision.outcome != "release_ready":
            raise Denied("this request requires Operations review")
        decision = self._evaluate(customer_id, record.equipment_id)
        pdf = b""
        artifact_failure: HoldReason | None = None
        if decision.artifact is not None:
            if decision.artifact != record.decision.artifact:
                artifact_failure = "artifact_changed"
            else:
                try:
                    pdf = self.pdfs.read(customer_id, decision.artifact)
                except EvidenceUnavailable:
                    artifact_failure = "artifact_unavailable"
                else:
                    if (
                        not pdf.startswith(b"%PDF-")
                        or hashlib.sha256(pdf).hexdigest() != decision.artifact.sha256
                    ):
                        artifact_failure = "artifact_changed"
        if pdf and artifact_failure is None:
            # Fetching bytes can take time. Recheck policy/ownership after the read,
            # before committing the release audit or exposing bytes to transport.
            decision = self._evaluate(customer_id, record.equipment_id)
            if decision.artifact is not None and decision.artifact != record.decision.artifact:
                artifact_failure = "artifact_changed"
        if artifact_failure is not None:
            decision = CertificateDecision(
                evaluated_at=decision.evaluated_at,
                sources=decision.sources,
                outcome="operations_required",
                checks=(
                    decision.checks[0],
                    CertificateCheck(
                        name="certificate_validity",
                        verdict="fail",
                        reason=artifact_failure,
                    ),
                    decision.checks[2],
                ),
            )
        updated = self._record(
            request_id,
            actor_id,
            customer_id,
            record.equipment_id,
            decision,
            prior=record,
            download_prepared=True,
        )
        self.store.commit(updated, expected_events=len(record.events))
        if decision.outcome != "release_ready":
            raise Denied("this request requires Operations review")
        # The audit says prepared, not delivered: transport completion is not known here.
        return pdf

    def customer_status(self, tenant_id: UUID, actor_id: UUID, request_id: UUID) -> dict[str, str]:
        customer_id = self._customer(tenant_id, actor_id)
        record = self._existing(tenant_id, actor_id, customer_id, request_id)
        case_status = "not_required"
        updated_at = record.events[-1].occurred_at
        if record.decision.outcome == "operations_required":
            case = record.operations_case
            if case is None or case.assigned_user_id != self.operations_user_id:
                raise Conflict("case binding changed")
            case_status = "open"
            review = self.store.get_review(request_id)
            if review is not None:
                # Revalidate audit consistency before projecting, even for alternative stores.
                review = CaseReview.model_validate(review.model_dump())
                if (
                    review.request_id != request_id
                    or review.tenant_id != tenant_id
                    or review.case_id != case.case_id
                    or review.assigned_user_id != case.assigned_user_id
                    or review.decision_hash != record.decision_hash
                ):
                    raise Conflict("case review binding changed")
                case_status = review.state
                # Internal notes must not alter the customer-visible timestamp.
                transitions = [e for e in review.events if e.command.action != "add_note"]
                if transitions:
                    updated_at = max(updated_at, transitions[-1].occurred_at)
        messages = {
            "not_required": "Your certificate is ready for a checked download.",
            "open": "Your request needs Operations review. No certificate was released.",
            "acknowledged": "Operations is reviewing your request. No certificate was released.",
            "closed_without_release": (
                "Operations has closed your request. No certificate was released."
            ),
        }
        return CustomerCertificateStatus.model_validate(
            {
                "request_id": str(request_id),
                "status": record.decision.outcome,
                "case_status": case_status,
                "updated_at": updated_at,
                "message": messages[case_status],
            }
        ).model_dump(mode="json")

"""Customer-facing coverage renewal surface: coarse public progress, never internal notes."""

from typing import Any, Literal, Protocol
from uuid import UUID

from innexq_contracts.coverage_renewal import (
    CoverageRenewalRecord,
    CoverageRenewalState,
    CoverageSourceFact,
    CoverageToolReceipt,
)
from innexq_contracts.customer_status import CustomerCoverageProgress

from innexq_api.coverage_controller import CoverageController, public_progress
from innexq_api.coverage_executor import ArtifactKind, CoverageExecutor
from innexq_api.store import Conflict

PROGRESS_MESSAGES: dict[str, str] = {
    "Evidence review": (
        "We are reviewing the recorded evidence for your renewal request. "
        "Nothing has been charged or issued."
    ),
    "Awaiting Operations": (
        "Your renewal proposal is awaiting Operations review. Nothing has been charged or issued."
    ),
    "Awaiting Manager": (
        "Your renewal proposal is awaiting final Manager approval. "
        "Nothing has been charged or issued."
    ),
    "Issuing documents": "Your renewal was approved and the documents are being issued.",
    "Completed": ("Your renewal is complete. The new coverage document and invoice are available."),
    "Held or rejected": (
        "Your request could not be completed automatically and is with Operations. "
        "No documents were issued and nothing was charged."
    ),
}


class CoverageInvestigator(Protocol):
    """Agent-directed evidence gathering; citations only, never authority."""

    def investigate(
        self, record: CoverageRenewalRecord
    ) -> tuple[tuple[CoverageSourceFact, ...], tuple[CoverageToolReceipt, ...], str | None]: ...


class CoverageCustomerRuntime:
    """Runs the deterministic renewal pipeline; the controller owns every transition."""

    def __init__(
        self,
        controller: CoverageController,
        investigator: CoverageInvestigator,
        executor: CoverageExecutor | None = None,
    ) -> None:
        self.controller, self.investigator, self.executor = controller, investigator, executor

    def outcome(
        self, customer_id: str, equipment_id: str
    ) -> Literal["existing_pdf", "renewal_required", "unavailable"]:
        return self.controller.document_request_outcome(customer_id, equipment_id)

    def start(self, customer_id: str, equipment_id: str, request_id: UUID) -> dict[str, Any]:
        """Confirmed customer intent; the message identifier makes retries idempotent."""

        try:
            record = self.controller.start_renewal(customer_id, equipment_id, request_id=request_id)
        except Conflict:
            return self.progress(customer_id, request_id)
        self.controller.begin_investigation(record.request_id)
        try:
            facts, receipts, cited = self.investigator.investigate(record)
        except Exception:
            # No agent evidence means no package; hold safely with a generic reason.
            self.controller.hold_investigation(record.request_id)
        else:
            self.controller.verify_eligibility(record.request_id, facts, receipts, cited)
        return self.progress(customer_id, request_id)

    def progress(self, customer_id: str, request_id: UUID) -> dict[str, Any]:
        record, _ = self.controller.store.get(request_id)
        if record.customer_id != customer_id:
            # Same public response as an unknown identifier; never confirm existence.
            raise KeyError(str(request_id))
        progress = public_progress(record)
        return CustomerCoverageProgress(
            request_id=record.request_id,
            progress=progress,
            message=PROGRESS_MESSAGES[progress],
            updated_at=record.updated_at,
        ).model_dump(mode="json")

    def download(
        self, customer_id: str, request_id: UUID, kind: ArtifactKind = "certificate"
    ) -> bytes:
        record, _ = self.controller.store.get(request_id)
        if record.customer_id != customer_id or record.state != CoverageRenewalState.COMPLETED:
            # Same public response as an unknown identifier; never confirm existence.
            raise KeyError(str(request_id))
        if self.executor is None:
            raise KeyError(str(request_id))
        return self.executor.download(request_id, kind)

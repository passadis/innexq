"""Guarded Service Coverage Renewal executor (ADR-018, spec section: Controlled execution).

Runs only after the controller records EXECUTING behind both hash-bound
approvals, and re-verifies them itself. Idempotent: a retry or duplicate call
can never allocate a second invoice number, render different bytes or publish
a second artifact. Customer downloads re-verify the stored SHA-256.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol
from uuid import UUID

from innexq_contracts.coverage_renewal import (
    CoverageRenewalRecord,
    CoverageRenewalState,
    approvals_authorize_execution,
    compute_package_hash,
)
from innexq_gateway.coverage import coverage_period

from innexq_api.coverage_controller import CoverageAuthorizationError, CoverageSourceReader
from innexq_api.coverage_documents import (
    render_coverage_certificate,
    render_invoice,
    sha256_hex,
)
from innexq_api.coverage_store import CosmosCoverageStore
from innexq_api.store import Conflict

ArtifactKind = Literal["certificate", "invoice"]


class CoverageArtifactStorage(Protocol):
    """Private, authenticated artifact storage; never public URLs or SAS links."""

    def write(self, blob_name: str, content: bytes) -> None: ...

    def read(self, blob_name: str) -> bytes: ...


class CoverageExecutor:
    def __init__(
        self,
        store: CosmosCoverageStore,
        storage: CoverageArtifactStorage,
        reader: CoverageSourceReader,
    ) -> None:
        self.store, self.storage, self.reader = store, storage, reader

    def _authorized(self, record: CoverageRenewalRecord) -> None:
        if (
            record.package is None
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

    def execute(self, request_id: UUID) -> dict[str, Any]:
        record, etag = self.store.get(request_id)
        if record.state != CoverageRenewalState.EXECUTING:
            raise CoverageAuthorizationError("executor requires the EXECUTING state")
        self._authorized(record)
        existing = self.store.get_execution(request_id)
        if existing is not None:
            # Duplicate callback or retry after commit: exactly the same outcome.
            return existing
        package = record.package
        manager = record.manager_decision
        assert package is not None and manager is not None  # noqa: S101 - checked above
        try:
            approved_on = manager.submitted_at.date()
            coverage_start, coverage_end = coverage_period(approved_on, package.coverage_months)
            invoice_number = self.store.allocate_next_invoice(approved_on.year)
            document_id = f"{package.equipment_id}-COVERAGE-{invoice_number}"
            # The Manager approval timestamp fixes issuance, so retries render identical bytes.
            certificate = render_coverage_certificate(
                document_id=document_id,
                customer_id=package.customer_id,
                customer_name=self.reader.customer_name(package.customer_id),
                equipment_id=package.equipment_id,
                serial_number=package.serial_number,
                equipment_model=package.equipment_id,
                coverage_start=coverage_start,
                coverage_end=coverage_end,
                issued_at=manager.submitted_at,
                policy_version=package.quote.policy_version,
                previous_document=package.previous_document,
            )
            invoice = render_invoice(
                invoice_number=invoice_number,
                customer_id=package.customer_id,
                customer_name=self.reader.customer_name(package.customer_id),
                equipment_id=package.equipment_id,
                quote=package.quote,
                preview=package.invoice_preview,
                issued_at=manager.submitted_at,
            )
            payload: dict[str, Any] = {
                "invoice_number": invoice_number,
                "document_id": document_id,
                "coverage_start": coverage_start.isoformat(),
                "coverage_end": coverage_end.isoformat(),
                "previous_document_id": package.previous_document.document_id,
                "artifacts": {
                    "certificate": {
                        "blob_name": f"coverage/{request_id}/{document_id}.pdf",
                        "sha256": sha256_hex(certificate),
                    },
                    "invoice": {
                        "blob_name": f"coverage/{request_id}/{invoice_number}.pdf",
                        "sha256": sha256_hex(invoice),
                    },
                },
                "notification": {"channel": "customer_portal", "state": "pending"},
            }
            self.storage.write(payload["artifacts"]["certificate"]["blob_name"], certificate)
            self.storage.write(payload["artifacts"]["invoice"]["blob_name"], invoice)
            self.store.create_execution(request_id, payload)
        except Conflict:
            raise
        except Exception:
            self._fail(request_id)
            raise
        record, etag = self.store.get(request_id)
        completed = record.model_copy(
            update={
                "state": CoverageRenewalState.COMPLETED,
                "revision": record.revision + 1,
                "updated_at": record.updated_at,
            }
        )
        self.store.commit(completed, "coverage.completed", etag)
        return payload

    def _fail(self, request_id: UUID) -> None:
        try:
            record, etag = self.store.get(request_id)
            if record.state != CoverageRenewalState.EXECUTING:
                return
            failed = record.model_copy(
                update={
                    "state": CoverageRenewalState.EXECUTION_FAILED,
                    "revision": record.revision + 1,
                    "updated_at": record.updated_at,
                }
            )
            self.store.commit(failed, "coverage.execution_failed", etag)
        except Exception:  # noqa: S110 - the original execution error is the signal
            pass

    def retry(self, request_id: UUID) -> dict[str, Any]:
        """Re-verify both approvals before moving EXECUTION_FAILED back to EXECUTING."""

        record, etag = self.store.get(request_id)
        if record.state != CoverageRenewalState.EXECUTION_FAILED:
            raise CoverageAuthorizationError("only a failed execution may be retried")
        self._authorized(record)
        executing = record.model_copy(
            update={
                "state": CoverageRenewalState.EXECUTING,
                "revision": record.revision + 1,
                "updated_at": record.updated_at,
            }
        )
        self.store.commit(executing, "coverage.executing", etag)
        return self.execute(request_id)

    def download(self, request_id: UUID, kind: ArtifactKind) -> bytes:
        """Authenticated availability with a mandatory hash re-check; no public links."""

        record, _ = self.store.get(request_id)
        execution = self.store.get_execution(request_id)
        if record.state != CoverageRenewalState.COMPLETED or execution is None:
            raise CoverageAuthorizationError("no issued documents are available")
        artifact = execution["artifacts"][kind]
        content = self.storage.read(artifact["blob_name"])
        if sha256_hex(content) != artifact["sha256"]:
            raise CoverageAuthorizationError("stored artifact failed integrity verification")
        return content

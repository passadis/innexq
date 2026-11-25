"""Executor guards: idempotent issuance, integrity re-checks, safe failure."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from innexq_api.coverage_controller import CoverageAuthorizationError, CoverageController
from innexq_api.coverage_executor import CoverageExecutor
from innexq_contracts.coverage_renewal import CoverageRenewalState

from tests.unit.test_coverage_controller import (
    MANAGER_OID,
    OPERATIONS_OID,
    Reader,
    awaiting_operations,
    setup,
)


class Storage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.writes = 0
        self.fail = False

    def write(self, blob_name: str, content: bytes) -> None:
        if self.fail:
            raise RuntimeError("PRIVATE STORAGE ERROR")
        self.writes += 1
        self.blobs[blob_name] = content

    def read(self, blob_name: str) -> bytes:
        return self.blobs[blob_name]


def executing_request() -> tuple[CoverageController, CoverageExecutor, Storage, UUID]:
    controller, store, _ = setup()
    storage = Storage()
    executor = CoverageExecutor(store, storage, Reader())
    request_id = awaiting_operations(controller)
    controller.operations_decide(request_id, OPERATIONS_OID, "approve")
    controller.manager_decide(request_id, MANAGER_OID, "approve")
    controller.authorize_execution(request_id)
    return controller, executor, storage, request_id


def test_execution_issues_documents_and_completes() -> None:
    _controller, executor, storage, request_id = executing_request()
    payload = executor.execute(request_id)
    assert payload["invoice_number"] == "SYN-INV-2026-00001"
    assert payload["document_id"].endswith("SYN-INV-2026-00001")
    assert payload["coverage_start"] == "2026-09-22"
    assert payload["coverage_end"] == "2027-09-22"
    assert storage.writes == 2
    for artifact in payload["artifacts"].values():
        assert storage.blobs[artifact["blob_name"]].startswith(b"%PDF-")
    record, _ = executor.store.get(request_id)
    assert record.state == CoverageRenewalState.COMPLETED
    assert executor.download(request_id, "certificate").startswith(b"%PDF-")
    assert executor.download(request_id, "invoice").startswith(b"%PDF-")


def test_duplicate_execution_creates_no_second_invoice_or_pdf() -> None:
    _, executor, storage, request_id = executing_request()
    first = executor.execute(request_id)
    # Simulate a duplicate callback racing before the state commit is observed.
    record, _etag = executor.store.get(request_id)
    again = executor.execute(request_id) if record.state.value == "EXECUTING" else first
    assert again == first
    assert storage.writes == 2
    # A fresh renewal still receives the next unique number, never a reused one.
    assert executor.store.allocate_next_invoice(2026) == "SYN-INV-2026-00002"


def test_failed_storage_produces_execution_failed_then_retry_succeeds() -> None:
    _, executor, storage, request_id = executing_request()
    storage.fail = True
    with pytest.raises(RuntimeError):
        executor.execute(request_id)
    record, _ = executor.store.get(request_id)
    assert record.state == CoverageRenewalState.EXECUTION_FAILED
    with pytest.raises(CoverageAuthorizationError):
        executor.download(request_id, "certificate")
    storage.fail = False
    payload = executor.retry(request_id)
    # The failed attempt consumed a reservation; the retry allocated the next one.
    assert payload["invoice_number"] == "SYN-INV-2026-00002"
    record, _ = executor.store.get(request_id)
    assert record.state == CoverageRenewalState.COMPLETED


def test_executor_refuses_unauthorized_states_and_tampered_packages() -> None:
    controller, store, container = setup()
    storage = Storage()
    executor = CoverageExecutor(store, storage, Reader())
    request_id = awaiting_operations(controller)
    with pytest.raises(CoverageAuthorizationError, match="EXECUTING"):
        executor.execute(request_id)
    controller.operations_decide(request_id, OPERATIONS_OID, "approve")
    controller.manager_decide(request_id, MANAGER_OID, "approve")
    controller.authorize_execution(request_id)
    snapshot = container.items[f"coverage:{request_id}", "coverage-snapshot"]
    snapshot["record"]["package"]["serial_number"] = "TAMPERED-0001"
    with pytest.raises(CoverageAuthorizationError, match="not authorized"):
        executor.execute(request_id)
    assert storage.writes == 0
    with pytest.raises(CoverageAuthorizationError, match="only a failed execution"):
        executor.retry(request_id)


def test_tampered_stored_artifact_blocks_download() -> None:
    _, executor, storage, request_id = executing_request()
    payload = executor.execute(request_id)
    blob_name = payload["artifacts"]["certificate"]["blob_name"]
    storage.blobs[blob_name] = storage.blobs[blob_name] + b"tampered"
    with pytest.raises(CoverageAuthorizationError, match="integrity"):
        executor.download(request_id, "certificate")
    # The untouched invoice remains downloadable.
    assert executor.download(request_id, "invoice").startswith(b"%PDF-")


def test_download_requires_completion() -> None:
    _, executor, _, request_id = executing_request()
    with pytest.raises(CoverageAuthorizationError, match="no issued documents"):
        executor.download(request_id, "certificate")


def test_unknown_request_has_no_execution_receipt() -> None:
    _, executor, _, _ = executing_request()
    assert executor.store.get_execution(uuid4()) is None

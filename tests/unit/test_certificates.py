import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from innexq_api.certificates import CertificateController, EvidenceUnavailable
from innexq_api.controller import Denied
from innexq_api.store import Conflict
from innexq_contracts.certificates import (
    CertificateArtifact,
    CertificateCheck,
    CertificateDecision,
    CertificateRequestRecord,
    CertificateSources,
)
from innexq_gateway.certificates import evaluate_certificate
from pydantic import ValidationError

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
TENANT, CUSTOMER, OTHER, OPERATIONS, REQUEST = (UUID(int=n) for n in range(1, 6))
PDF = b"%PDF-1.7\nFictional unit fixture, never uploaded."


def sources() -> CertificateSources:
    stamp = {
        "source_version": "1",
        "observed_at": NOW - timedelta(minutes=1),
        "fresh_until": NOW + timedelta(minutes=5),
    }
    identity = {
        "customer_id": "DEMO-FAB",
        "equipment_id": "DEMO-PT-001",
        "serial_number": "DEMO-SERIAL-0001",
    }
    validity = {"valid_from": NOW - timedelta(days=30), "valid_until": NOW + timedelta(days=30)}
    return CertificateSources.model_validate(
        {
            "ownership": stamp | identity,
            "certificate": stamp
            | identity
            | validity
            | {
                "document_id": "DEMO-PT-001-CERT",
                "document_version": "1",
                "sha256": hashlib.sha256(PDF).hexdigest(),
                "accessible": True,
                "revoked": False,
            },
            "service": stamp | identity | validity | {"in_service": True},
        }
    )


def replace_source(part: str, **changes: object) -> CertificateSources:
    payload = sources().model_dump()
    payload[part].update(changes)
    return CertificateSources.model_validate(payload)


class Evidence:
    def __init__(self) -> None:
        self.value = sources()
        self.calls = 0
        self.fail = False

    def read(self, customer_id: str, equipment_id: str) -> CertificateSources:
        self.calls += 1
        if self.fail:
            raise EvidenceUnavailable("not available")
        return self.value


class Pdfs:
    def __init__(self) -> None:
        self.value = PDF
        self.calls = 0
        self.fail = False

    def read(self, customer_id: str, artifact: CertificateArtifact) -> bytes:
        self.calls += 1
        assert customer_id == "DEMO-FAB"
        if self.fail:
            raise EvidenceUnavailable("not available")
        return self.value


class Store:
    """Explicit unit-test fake, never imported or selected by the application."""

    def __init__(self) -> None:
        self.records: dict[UUID, CertificateRequestRecord] = {}
        self.commits = 0
        self.fail = False
        self.concurrent_winner: CertificateRequestRecord | None = None

    def get(self, request_id: UUID) -> CertificateRequestRecord:
        return self.records[request_id]

    def get_review(self, request_id: UUID):
        return None

    def commit(self, record: CertificateRequestRecord, expected_events: int) -> None:
        if self.fail:
            raise RuntimeError("store unavailable")
        if self.concurrent_winner is not None:
            self.records[record.request_id] = self.concurrent_winner
            raise Conflict("another request won")
        previous = self.records.get(record.request_id)
        if (len(previous.events) if previous else 0) != expected_events:
            raise Conflict("concurrent write")
        self.records[record.request_id] = record
        self.commits += 1


def controller() -> tuple[CertificateController, Evidence, Pdfs, Store]:
    evidence, pdfs, store = Evidence(), Pdfs(), Store()
    instance = CertificateController(
        TENANT,
        {CUSTOMER: "DEMO-FAB", OTHER: "DEMO-NW"},
        OPERATIONS,
        evidence,
        pdfs,
        store,
        lambda: NOW,
    )
    return instance, evidence, pdfs, store


def test_all_three_checks_pass_and_bind_exact_source_pdf() -> None:
    decision = evaluate_certificate("DEMO-FAB", "DEMO-PT-001", sources(), NOW)
    assert decision.outcome == "release_ready"
    assert all(check.verdict == "pass" for check in decision.checks)
    assert decision.artifact.sha256 == hashlib.sha256(PDF).hexdigest()
    assert decision.policy_id == "CERT-RELEASE-001" and decision.policy_version == 1


@pytest.mark.parametrize("part", ["ownership", "certificate", "service"])
@pytest.mark.parametrize("condition", ["missing", "stale", "future"])
def test_missing_stale_future_evidence_holds(part: str, condition: str) -> None:
    payload = sources().model_dump()
    if condition == "missing":
        payload[part] = None
    elif condition == "stale":
        payload[part]["fresh_until"] = NOW
    else:
        payload[part]["observed_at"] = NOW + timedelta(minutes=1)
    result = evaluate_certificate(
        "DEMO-FAB", "DEMO-PT-001", CertificateSources.model_validate(payload), NOW
    )
    assert result.outcome == "operations_required" and result.artifact is None
    assert any(item.verdict == "unknown" for item in result.checks)


@pytest.mark.parametrize(
    ("part", "field", "value"),
    [
        ("ownership", "customer_id", "DEMO-NW"),
        ("ownership", "equipment_id", "DEMO-OTHER"),
        ("certificate", "accessible", False),
        ("certificate", "accessible", None),
        ("certificate", "revoked", True),
        ("certificate", "revoked", None),
        ("certificate", "serial_number", "DEMO-WRONG"),
        ("certificate", "customer_id", "DEMO-NW"),
        ("certificate", "equipment_id", "DEMO-OTHER"),
        ("certificate", "valid_until", NOW),
        ("certificate", "valid_from", NOW + timedelta(seconds=1)),
        ("service", "in_service", False),
        ("service", "in_service", None),
        ("service", "serial_number", "DEMO-WRONG"),
        ("service", "customer_id", "DEMO-NW"),
        ("service", "equipment_id", "DEMO-OTHER"),
        ("service", "valid_until", NOW),
        ("service", "valid_from", NOW + timedelta(seconds=1)),
    ],
)
def test_policy_failures_never_produce_a_release_artifact(
    part: str, field: str, value: object
) -> None:
    result = evaluate_certificate(
        "DEMO-FAB", "DEMO-PT-001", replace_source(part, **{field: value}), NOW
    )
    assert result.outcome == "operations_required" and result.artifact is None


def test_invalid_clocks_stamps_booleans_and_forged_decisions_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_certificate("DEMO-FAB", "DEMO-PT-001", sources(), datetime(2026, 9, 10))
    with pytest.raises(ValidationError, match="freshness end"):
        replace_source("ownership", fresh_until=NOW - timedelta(days=1))
    with pytest.raises(ValidationError):
        replace_source("service", in_service="yes")
    with pytest.raises(ValidationError, match="agree with its reason"):
        CertificateCheck(name="ownership", verdict="pass", reason="ownership_mismatch")
    good = evaluate_certificate("DEMO-FAB", "DEMO-PT-001", sources(), NOW).model_dump()
    with pytest.raises(ValidationError, match="three ordered"):
        CertificateDecision.model_validate(good | {"checks": tuple(reversed(good["checks"]))})
    with pytest.raises(ValidationError, match="all checks"):
        CertificateDecision.model_validate(good | {"outcome": "operations_required"})
    with pytest.raises(ValidationError, match="release artifact"):
        CertificateDecision.model_validate(good | {"artifact": None})


def test_controller_audits_before_returning_exact_bytes_and_does_not_claim_delivery() -> None:
    app, evidence, pdfs, store = controller()
    record = app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    assert record.operations_case is None and pdfs.calls == 0 and store.commits == 1
    assert app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST) == record
    assert evidence.calls == 1 and store.commits == 1
    assert app.download(TENANT, CUSTOMER, REQUEST) == PDF
    assert evidence.calls == 3 and pdfs.calls == 1 and store.commits == 2
    assert store.get(REQUEST).events[-1].event_type == "certificate.download_prepared"
    assert "ready" in app.customer_status(TENANT, CUSTOMER, REQUEST)["message"]


def test_hold_creates_one_assigned_case_and_public_status_hides_private_evidence() -> None:
    app, evidence, pdfs, store = controller()
    evidence.value = replace_source("ownership", customer_id="DEMO-NW")
    record = app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    assert record.operations_case.assigned_user_id == OPERATIONS
    assert record.events[-1].event_type == "operations.case_created"
    again = app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    assert again.operations_case.case_id == record.operations_case.case_id and store.commits == 1
    public = app.customer_status(TENANT, CUSTOMER, REQUEST)
    assert set(public) == {"request_id", "status", "message", "case_status", "updated_at"}
    assert public["case_status"] == "open"
    assert "DEMO-NW" not in str(public) and "ownership_mismatch" not in str(public)
    with pytest.raises(Denied, match="Operations"):
        app.download(TENANT, CUSTOMER, REQUEST)
    assert pdfs.calls == 0


def test_unavailable_source_routes_to_operations_without_fetching_pdf() -> None:
    app, evidence, pdfs, _ = controller()
    evidence.fail = True
    record = app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    assert record.operations_case.reason_codes == ("missing_evidence",) and pdfs.calls == 0


@pytest.mark.parametrize(
    "condition", ["expired", "new_version", "new_hash", "bad_bytes", "unavailable"]
)
def test_download_rechecks_policy_and_source_identity(condition: str) -> None:
    app, evidence, pdfs, store = controller()
    app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    if condition == "expired":
        evidence.value = replace_source("service", valid_until=NOW)
    elif condition == "new_version":
        evidence.value = replace_source("certificate", document_version="2")
    elif condition == "new_hash":
        evidence.value = replace_source("certificate", sha256="a" * 64)
    elif condition == "bad_bytes":
        pdfs.value = b"%PDF-1.7\nChanged bytes"
    else:
        pdfs.fail = True
    with pytest.raises(Denied, match="Operations"):
        app.download(TENANT, CUSTOMER, REQUEST)
    assert store.get(REQUEST).operations_case.assigned_user_id == OPERATIONS
    assert store.get(REQUEST).decision.artifact is None


def test_non_pdf_even_with_matching_hash_is_never_released() -> None:
    app, evidence, pdfs, _ = controller()
    pdfs.value = b"not a PDF"
    evidence.value = replace_source("certificate", sha256=hashlib.sha256(pdfs.value).hexdigest())
    app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    with pytest.raises(Denied):
        app.download(TENANT, CUSTOMER, REQUEST)


@pytest.mark.parametrize("change", ["expired", "ownership", "version"])
def test_changes_while_reading_pdf_stop_release(
    change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, evidence, pdfs, store = controller()
    app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)

    def changing_reader(customer_id: str, artifact: CertificateArtifact) -> bytes:
        if change == "expired":
            evidence.value = replace_source("service", valid_until=NOW)
        elif change == "ownership":
            evidence.value = replace_source("ownership", customer_id="DEMO-NW")
        else:
            evidence.value = replace_source("certificate", document_version="2")
        return PDF

    monkeypatch.setattr(pdfs, "read", changing_reader)
    with pytest.raises(Denied, match="Operations"):
        app.download(TENANT, CUSTOMER, REQUEST)
    assert store.get(REQUEST).operations_case is not None


def test_identity_guards_and_request_id_binding() -> None:
    app, evidence, _, store = controller()
    for tenant, actor in [(UUID(int=99), CUSTOMER), (TENANT, OPERATIONS), (TENANT, UUID(int=99))]:
        with pytest.raises(Denied):
            app.request(tenant, actor, "DEMO-PT-001", REQUEST)
    assert evidence.calls == 0
    with pytest.raises(Denied, match="target"):
        app.request(TENANT, CUSTOMER, " ", REQUEST)
    record = app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    with pytest.raises(Denied, match="not available"):
        app.download(TENANT, OTHER, REQUEST)
    with pytest.raises(Denied, match="different target"):
        app.request(TENANT, CUSTOMER, "DEMO-PT-002", REQUEST)
    store.records[REQUEST] = record.model_copy(update={"decision_hash": "f" * 64})
    with pytest.raises(Denied, match="inconsistent"):
        app.download(TENANT, CUSTOMER, REQUEST)


def test_store_failure_never_acknowledges_case_or_releases_pdf() -> None:
    app, _, _, store = controller()
    store.fail = True
    with pytest.raises(RuntimeError, match="store unavailable"):
        app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    store.fail = False
    app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    store.fail = True
    with pytest.raises(RuntimeError, match="store unavailable"):
        app.download(TENANT, CUSTOMER, REQUEST)


def test_concurrent_create_returns_only_identical_winner() -> None:
    winner_app, _, _, _ = controller()
    winner = winner_app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    app, _, _, store = controller()
    store.concurrent_winner = winner
    assert app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST) == winner
    app, _, _, store = controller()
    store.concurrent_winner = winner
    with pytest.raises(Denied, match="different target"):
        app.request(TENANT, CUSTOMER, "DEMO-PT-002", REQUEST)


def test_configuration_and_record_consistency() -> None:
    app, evidence, pdfs, store = controller()
    with pytest.raises(ValueError, match="Operations"):
        CertificateController(
            TENANT, {CUSTOMER: "DEMO-FAB"}, CUSTOMER, evidence, pdfs, store, lambda: NOW
        )
    with pytest.raises(ValueError, match="blank"):
        CertificateController(
            TENANT, {CUSTOMER: " "}, OPERATIONS, evidence, pdfs, store, lambda: NOW
        )
    record = app.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    payload = record.model_dump()
    payload["events"][0]["sequence"] = 2
    with pytest.raises(ValidationError, match="contiguous"):
        CertificateRequestRecord.model_validate(payload)
    payload = record.model_dump()
    payload["events"][1]["occurred_at"] = NOW - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="ordered"):
        CertificateRequestRecord.model_validate(payload)
    evidence.value = CertificateSources()
    held = app.request(TENANT, CUSTOMER, "DEMO-PT-001", UUID(int=99))
    with pytest.raises(ValidationError, match="Operations case"):
        CertificateRequestRecord.model_validate(held.model_dump() | {"operations_case": None})

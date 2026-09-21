"""Unit-only OCR and specialist doubles; never proof of live extraction or agent calls."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from innexq_api.certificate_repository import CertificateRegistry
from innexq_api.certificate_runtime import (
    CertificateApplication,
    HostedCertificateTeam,
    InvestigatedEvidence,
)
from innexq_api.certificates import EvidenceUnavailable
from innexq_api.config import Settings
from innexq_api.controller import Denied
from innexq_api.customer_routes import CustomerRequest
from innexq_api.document_extraction import (
    DocumentExtraction,
    ExtractedField,
    ExtractedLine,
    ExtractedPage,
    PageCitation,
)
from innexq_contracts.certificates import CertificateArtifact, SpecialistProof
from innexq_gateway.demo_catalog import build_demo_catalog

from tests.unit.test_certificates import Store

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
ACTOR = UUID("b6491861-0f01-451a-aa40-fd1957c20747")
OTHER = UUID("89921dc2-cc4a-4e61-bfb5-c6ec807615a9")
TENANT = UUID("35de4c50-7dcd-4871-8685-61789c017da2")
PDF = b"%PDF-1.7\nunit-only runtime fixture\n%%EOF"
SHA = hashlib.sha256(PDF).hexdigest()


class Repository:
    def __init__(self) -> None:
        catalog = build_demo_catalog(NOW.date())
        self.value = CertificateRegistry(
            date_convention="UTC-inclusive-calendar-date",
            catalog=catalog,
            artifacts={
                d.document_id: CertificateArtifact(
                    document_id=d.document_id, document_version=SHA, sha256=SHA
                )
                for d in catalog.documents
            },
            revoked={d.document_id: False for d in catalog.documents if d.kind == "certificate"},
            in_service={e.equipment_id: True for e in catalog.equipment},
        )
        self.registry_reads = 0
        self.pdf_reads: list[str] = []
        self.change_version = False

    def registry(self) -> tuple[CertificateRegistry, str, datetime]:
        self.registry_reads += 1
        version = "v2" if self.change_version and self.registry_reads > 1 else "v1"
        return self.value, version, NOW

    def read(self, customer_id: str, artifact: CertificateArtifact) -> bytes:
        self.pdf_reads.append(artifact.document_id)
        return PDF


class Extractor:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.calls: list[str] = []
        self.mismatch = False
        self.service_due_mismatch = False

    def extract(
        self, pdf: bytes, *, document_id: str, document_version: str, expected_sha256: str
    ) -> DocumentExtraction:
        assert pdf == PDF
        self.calls.append(document_id)
        doc = next(
            d for d in self.repository.value.catalog.documents if d.document_id == document_id
        )
        values = {
            "Document ID": document_id,
            "Customer ID": doc.customer_id,
            "Equipment ID": doc.equipment_id or "none",
            "Recorded serial number": doc.recorded_serial_number or "none",
            "Issued on": doc.issued_on.isoformat(),
            "Valid until": doc.valid_until.isoformat(),
        }
        if doc.kind == "service_report":
            equipment = next(
                e
                for e in self.repository.value.catalog.equipment
                if e.equipment_id == doc.equipment_id
            )
            values["Next service due"] = equipment.service_valid_until.isoformat()
        if self.mismatch:
            values["Customer ID"] = "WRONG-CUSTOMER"
        if self.service_due_mismatch and doc.kind == "service_report":
            values["Next service due"] = "2000-01-01"
        citation = PageCitation(page_number=1, polygon=(0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0))
        return DocumentExtraction(
            document_id=document_id,
            document_version=document_version,
            sha256=expected_sha256,
            content="Unit-only OCR fixture",
            pages=(
                ExtractedPage(
                    page_number=1,
                    width=8.5,
                    height=11.0,
                    unit="inch",
                    lines=(ExtractedLine(content="Unit-only OCR fixture", citation=citation),),
                ),
            ),
            fields=tuple(
                ExtractedField(key=k, value=v, citations=(citation, citation))
                for k, v in values.items()
            ),
        )


class Team:
    def __init__(self) -> None:
        self.packets: list[dict[str, Any]] = []
        self.failure = False

    def investigate(self, packet: dict[str, Any]) -> tuple[SpecialistProof, ...]:
        self.packets.append(packet)
        if self.failure:
            raise EvidenceUnavailable("unit-only unavailable specialist")
        return tuple(
            SpecialistProof(specialist=name, response_id=f"unit-{name}", summary="Unit proof")
            for name in ("request_coordinator", "document_analyst", "equipment_service")
        )


def system() -> tuple[CertificateApplication, Repository, Extractor, Team, Store]:
    repository = Repository()
    extractor, team, store = Extractor(repository), Team(), Store()
    settings = Settings(
        _env_file=None, customer_bindings={str(ACTOR): "DEMO-FAB", str(OTHER): "DEMO-NW"}
    )
    app = CertificateApplication(settings, repository, extractor, team, store, now=lambda: NOW)  # type: ignore[arg-type]
    return app, repository, extractor, team, store


def evidence(repository: Repository, extractor: Extractor, team: Team) -> InvestigatedEvidence:
    return InvestigatedEvidence(repository, extractor, team, TENANT, uuid4(), "My certificate")  # type: ignore[arg-type]


def body(equipment: str = "DEMO-PT-001") -> CustomerRequest:
    return CustomerRequest(request_id=uuid4(), equipment_id=equipment, prompt="My certificate")


def test_complete_local_connection_preserves_real_adapter_contracts() -> None:
    app, repo, extractor, team, store = system()
    request = body()
    result = app.request(TENANT, ACTOR, request)
    assert result["status"] == "release_ready"
    record = store.get(request.request_id)
    assert record.decision.sources.investigation is not None
    assert len(record.decision.sources.investigation.specialists) == 3
    assert len(extractor.calls) == 2 and len(team.packets) == 1
    assert team.packets[0]["request_id"] == str(request.request_id)
    assert all("page 1:" in fact for fact in team.packets[0]["document_facts"])
    assert repo.registry_reads == 2
    assert app.download(TENANT, ACTOR, request.request_id) == PDF
    assert store.get(request.request_id).events[-1].event_type == "certificate.download_prepared"


def test_duplicate_request_reuses_persisted_result_without_more_ocr_or_agents() -> None:
    app, _, extractor, team, _ = system()
    request = body()
    first = app.request(TENANT, ACTOR, request)
    assert app.request(TENANT, ACTOR, request) == first
    assert len(extractor.calls) == 2 and len(team.packets) == 1


@pytest.mark.parametrize(
    "equipment,actor",
    [
        ("DEMO-PT-002", ACTOR),
        ("DEMO-PT-003", ACTOR),
        ("DEMO-PT-004", ACTOR),
        ("DEMO-PT-005", OTHER),
    ],
)
def test_source_failure_scenarios_hold_and_create_operations_case(
    equipment: str, actor: UUID
) -> None:
    app, _, _, _, store = system()
    request = body(equipment)
    assert app.request(TENANT, actor, request)["status"] == "operations_required"
    assert store.get(request.request_id).operations_case is not None
    with pytest.raises(Denied):
        app.download(TENANT, actor, request.request_id)


def test_ocr_mismatch_never_reaches_specialists_or_releases() -> None:
    app, _, extractor, team, _ = system()
    extractor.mismatch = True
    assert app.request(TENANT, ACTOR, body())["status"] == "operations_required"
    assert team.packets == []


def test_missing_artifact_is_not_filled_from_seed_catalog() -> None:
    app, repo, extractor, team, _ = system()
    repo.value = repo.value.model_copy(update={"artifacts": {}})
    assert app.request(TENANT, ACTOR, body())["status"] == "operations_required"
    assert extractor.calls == [] and team.packets == []


def test_specialist_failure_is_an_operations_hold() -> None:
    app, _, _, team, _ = system()
    team.failure = True
    assert app.request(TENANT, ACTOR, body())["status"] == "operations_required"


def test_conflicting_service_registry_dates_hold_before_pdf_or_agent_read() -> None:
    app, repo, extractor, team, _ = system()
    equipment = list(repo.value.catalog.equipment)
    equipment[0] = equipment[0].model_copy(
        update={"service_valid_until": NOW.date() - timedelta(days=1)}
    )
    catalog = repo.value.catalog.model_copy(update={"equipment": tuple(equipment)})
    repo.value = repo.value.model_copy(update={"catalog": catalog})
    assert app.request(TENANT, ACTOR, body())["status"] == "operations_required"
    assert repo.pdf_reads == [] and extractor.calls == [] and team.packets == []


def test_ocr_next_service_due_conflict_cannot_be_ignored() -> None:
    app, _, extractor, team, _ = system()
    extractor.service_due_mismatch = True
    assert app.request(TENANT, ACTOR, body())["status"] == "operations_required"
    assert team.packets == []


def test_registry_changed_during_ocr_is_not_refreshed_as_current() -> None:
    app, repo, _, _, store = system()
    repo.change_version = True
    request = body()
    assert app.request(TENANT, ACTOR, request)["status"] == "operations_required"
    assert store.get(request.request_id).decision.sources.ownership is None


def test_unchanged_pdf_cache_does_not_skip_authority_or_specialist_recheck() -> None:
    _, repo, extractor, team, _ = system()
    adapter = evidence(repo, extractor, team)
    first = adapter.read("DEMO-FAB", "DEMO-PT-001")
    second = adapter.read("DEMO-FAB", "DEMO-PT-001")
    assert first == second and len(extractor.calls) == 2
    assert repo.registry_reads == 4 and len(repo.pdf_reads) == 4 and len(team.packets) == 2


def test_date_only_source_uses_declared_inclusive_utc_convention() -> None:
    _, repo, extractor, team, _ = system()
    result = evidence(repo, extractor, team).read("DEMO-FAB", "DEMO-PT-001")
    assert result.certificate is not None and result.service is not None
    certificate = next(
        d for d in repo.value.catalog.documents if d.document_id == "DEMO-PT-001-CERT"
    )
    assert result.certificate.valid_until.date() == certificate.valid_until + timedelta(days=1)
    assert result.certificate.valid_until.hour == 0 and result.certificate.valid_until.tzinfo == UTC
    assert result.certificate.fresh_until - result.certificate.observed_at == timedelta(seconds=300)


def test_catalog_filters_customers_and_excludes_tier_presets() -> None:
    app, _, _, _, _ = system()
    fabrikam, northwind = app.catalog(TENANT, ACTOR), app.catalog(TENANT, OTHER)
    assert len(fabrikam["equipment"]) == 4 and len(northwind["equipment"]) == 3
    assert {e["equipment_id"] for e in fabrikam["equipment"]}.isdisjoint(
        e["equipment_id"] for e in northwind["equipment"]
    )
    assert all(p["equipment_id"] for p in fabrikam["presets"])
    assert "artifacts" not in fabrikam and "revoked" not in fabrikam


@pytest.mark.parametrize("tenant,actor", [(uuid4(), ACTOR), (TENANT, uuid4())])
def test_unassigned_identity_never_reads_private_registry(tenant: UUID, actor: UUID) -> None:
    app, repo, _, _, _ = system()
    with pytest.raises(Denied):
        app.catalog(tenant, actor)
    with pytest.raises(Denied):
        app.request(tenant, actor, body())
    assert repo.registry_reads == 0


def test_cross_customer_status_and_download_are_denied_without_source_read() -> None:
    app, repo, _, _, _ = system()
    request = body()
    app.request(TENANT, ACTOR, request)
    reads = repo.registry_reads
    with pytest.raises(Denied):
        app.status(TENANT, OTHER, request.request_id)
    with pytest.raises(Denied):
        app.download(TENANT, OTHER, request.request_id)
    assert repo.registry_reads == reads


def test_revocation_after_request_prevents_download() -> None:
    app, repo, _, _, store = system()
    request = body()
    app.request(TENANT, ACTOR, request)
    repo.value = repo.value.model_copy(update={"revoked": {"DEMO-PT-001-CERT": True}})
    with pytest.raises(Denied):
        app.download(TENANT, ACTOR, request.request_id)
    assert store.get(request.request_id).operations_case is not None


def test_operations_identity_cannot_be_bound_as_customer() -> None:
    app, repo, extractor, team, store = system()
    # Settings now rejects this at configuration time too. Deliberately bypass
    # construction here to preserve the independent runtime collision guard test.
    settings = Settings(_env_file=None).model_copy(
        update={"customer_bindings": {app.settings.approver_user_id: "DEMO-FAB"}}
    )
    with pytest.raises(ValueError):
        CertificateApplication(settings, repo, extractor, team, store)  # type: ignore[arg-type]


def team_packet() -> dict[str, Any]:
    return {
        "request_id": str(uuid4()),
        "document_facts": ["document evidence"],
        "equipment_facts": ["equipment evidence"],
    }


def team_response(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": packet["request_id"],
        "intent": "certificate_request",
        "specialists": [
            {
                "specialist": "document_analyst",
                "response_id": "doc-response",
                "summary": "document evidence",
            },
            {
                "specialist": "equipment_service",
                "response_id": "eq-response",
                "summary": "equipment evidence",
            },
        ],
    }


def hosted(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any], status: str = "completed"
) -> tuple[HostedCertificateTeam, MagicMock]:
    project = MagicMock()
    project.__enter__.return_value = project
    project.agents.create_session.return_value = SimpleNamespace(agent_session_id="unit-session")
    client = project.get_openai_client.return_value.__enter__.return_value
    client.responses.create.return_value = SimpleNamespace(
        status=status, id="coordinator-response", output_text=json.dumps(response)
    )
    monkeypatch.setattr("innexq_api.certificate_runtime.AIProjectClient", lambda **kwargs: project)
    settings = Settings(
        _env_file=None, certificate_agent_name="unit-team", certificate_agent_version="3"
    )
    return HostedCertificateTeam(settings, object()), project


def test_hosted_team_requires_exact_bound_citations_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = team_packet()
    team, project = hosted(monkeypatch, team_response(packet))
    proofs = team.investigate(packet)
    assert len(proofs) == 3 and proofs[0].response_id == "coordinator-response"
    assert project.agents.create_session.call_args.kwargs["version_indicator"].agent_version == "3"
    assert project.get_openai_client.call_args.kwargs["max_retries"] == 0


@pytest.mark.parametrize(
    "failure",
    [
        "wrong-request",
        "wrong-intent",
        "missing-specialist",
        "fabricated-summary",
        "extra-authority",
        "failed-status",
    ],
)
def test_hosted_team_invalid_proofs_fail_closed(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    packet = team_packet()
    response = team_response(packet)
    if failure == "wrong-request":
        response["request_id"] = str(uuid4())
    elif failure == "wrong-intent":
        response["intent"] = "tier_upgrade"
    elif failure == "missing-specialist":
        response["specialists"] = response["specialists"][:1]
    elif failure == "fabricated-summary":
        response["specialists"][0]["summary"] = "Invented policy approval"
    elif failure == "extra-authority":
        response["approved"] = True
    team, _ = hosted(monkeypatch, response, "failed" if failure == "failed-status" else "completed")
    with pytest.raises(EvidenceUnavailable):
        team.investigate(packet)


def test_hosted_team_requires_immutable_deployment() -> None:
    with pytest.raises(ValueError):
        HostedCertificateTeam(Settings(_env_file=None), object())


@pytest.mark.parametrize("failure", [None, "wrong-request", "foreign", "extra", "failed", "no-id"])
def test_hosted_interpretation_binding_and_private_errors(monkeypatch, failure):
    packet = {"request_id": str(uuid4()), "equipment_ids": ["DEMO-PT-001"]}
    result = {
        "request_id": packet["request_id"],
        "intent": "service_status",
        "equipment_id": "DEMO-PT-001",
    }
    if failure == "wrong-request":
        result["request_id"] = str(uuid4())
    elif failure == "foreign":
        result["equipment_id"] = "DEMO-PT-005"
    elif failure == "extra":
        result["unexpected_field"] = "private"
    team, project = hosted(monkeypatch, result, "failed" if failure == "failed" else "completed")
    if failure == "no-id":
        client = project.get_openai_client.return_value.__enter__.return_value
        client.responses.create.return_value.id = None
    if failure:
        with pytest.raises(EvidenceUnavailable, match="customer interpretation unavailable"):
            team.interpret(packet)
    else:
        proposal, response_id = team.interpret(packet)
        assert str(proposal.request_id) == packet["request_id"]
        assert response_id == "coordinator-response"
        assert (
            project.agents.create_session.call_args.kwargs["version_indicator"].agent_version == "3"
        )
        assert project.get_openai_client.call_args.kwargs["max_retries"] == 0


@pytest.mark.parametrize("intent", ["service_status", "certificate_status"])
def test_hosted_investigation_honors_read_only_packet_intent(monkeypatch, intent):
    packet = team_packet() | {"intent": intent}
    response = team_response(packet) | {"intent": intent}
    team, _ = hosted(monkeypatch, response)
    assert len(team.investigate(packet)) == 3

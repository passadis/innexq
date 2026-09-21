from typing import Any
from uuid import UUID, uuid4

import pytest
from innexq_api.certificates import EvidenceUnavailable
from innexq_api.evidence_broker import ROLES, EvidenceBinding, EvidenceBroker, EvidenceStore, Role
from innexq_api.evidence_runtime import BrokerInvestigatedEvidence, Report, TeamReport
from innexq_api.evidence_sources import CertificateEvidenceBackend
from pydantic import SecretStr

from tests.unit.test_certificate_runtime import NOW, TENANT, Extractor, Repository
from tests.unit.test_certificate_store import Container

AGENT = UUID(int=501)


class Team:
    def __init__(self, broker: EvidenceBroker) -> None:
        self.broker = broker
        self.binding: EvidenceBinding | None = None
        self.calls = 0
        self.fail = False
        self.skip = False
        self.forge = False

    def investigate(
        self, binding: EvidenceBinding, handles: dict[Role, SecretStr], prompt: str, intent: str
    ) -> tuple[TeamReport, str]:
        self.binding = binding
        self.calls += 1
        if self.fail:
            raise TimeoutError("private backend request")
        results = []
        for role in ROLES:
            calls: list[tuple[str, dict[str, str]]] = (
                [
                    ("list_equipment_documents", {}),
                    *[
                        ("analyze_document", {"document_id": doc})
                        for doc in binding.document_hashes
                    ],
                ]
                if role == "document_analyst"
                else [
                    ("get_equipment_record", {}),
                    ("retrieve_policy", {"query": "certificate policy"}),
                ]
            )
            if self.skip and role == "document_analyst":
                calls.pop()
            ids = [
                UUID(self.broker.call(TENANT, AGENT, handles[role], name, args)["receipt_id"])
                for name, args in calls
            ]
            if self.forge:
                ids[-1] = uuid4()
            results.append(
                Report(
                    specialist=role,
                    response_id=f"offline-{role}",
                    summary="Observed source evidence; not authorization.",
                    receipt_ids=ids,
                )
            )
        return TeamReport(
            request_id=binding.request_id, intent=intent, specialists=results
        ), "offline-coordinator"  # type: ignore[arg-type]


def system(
    intent: str = "certificate_request",
) -> tuple[BrokerInvestigatedEvidence, Team, Repository, Extractor]:
    repository = Repository()
    extractor = Extractor(repository)
    backend = CertificateEvidenceBackend(repository, extractor, "Offline policy")  # type: ignore[arg-type]
    broker = EvidenceBroker(EvidenceStore(Container()), backend, now=lambda: NOW)
    team = Team(broker)
    reader = BrokerInvestigatedEvidence(
        repository,
        backend,
        broker,
        team,
        TENANT,
        AGENT,
        uuid4(),  # type: ignore[arg-type]
        "Provide certificate",
        intent,
        now=lambda: NOW,
    )
    return reader, team, repository, extractor


def test_tools_drive_extraction_and_durable_receipts_build_controller_sources() -> None:
    reader, team, repo, extractor = system()
    sources = reader.read("DEMO-FAB", "DEMO-PT-001")
    assert sources.ownership and sources.ownership.customer_id == "DEMO-FAB"
    assert sources.certificate and sources.service and sources.investigation
    assert sources.investigation.request_id == reader.workflow_request_id
    assert len(sources.investigation.specialists) == 3
    assert len(extractor.calls) == 2
    assert sources.investigation.fields
    assert team.binding and team.binding.request_id != reader.workflow_request_id
    assert team.binding.workflow_request_id == reader.workflow_request_id
    assert all(
        reader.broker.store._read(team.binding.request_id, f"scope-{role}")["state"] == "closed"
        for role in ROLES
    )
    # Rechecks in the same download reuse validated evidence, never refresh its age.
    assert reader.read("DEMO-FAB", "DEMO-PT-001") == sources
    assert team.calls == 1 and len(repo.pdf_reads) == 2


@pytest.mark.parametrize("intent", ["service_status", "certificate_status"])
def test_status_intents_use_only_mandatory_documents(intent: str) -> None:
    reader, _, _, extractor = system(intent)
    sources = reader.read("DEMO-FAB", "DEMO-PT-001")
    assert len(extractor.calls) == (1 if intent == "service_status" else 2)
    assert (sources.certificate is None) == (intent == "service_status")


@pytest.mark.parametrize("failure", ["fail", "skip", "forge"])
def test_failed_partial_or_fabricated_team_result_revokes_scopes(failure: str) -> None:
    reader, team, _, _ = system()
    setattr(team, failure, True)
    with pytest.raises(EvidenceUnavailable, match=r"^scoped certificate evidence unavailable$"):
        reader.read("DEMO-FAB", "DEMO-PT-001")
    assert team.binding
    assert all(
        reader.broker.store._read(team.binding.request_id, f"scope-{role}")["state"] == "failed"
        for role in ROLES
    )
    assert reader.cached is None


@pytest.mark.parametrize(
    "customer,equipment", [("DEMO-NW", "DEMO-PT-001"), ("DEMO-FAB", "DEMO-PT-003")]
)
def test_foreign_equipment_or_missing_pdf_stops_before_agent(customer: str, equipment: str) -> None:
    reader, team, _, _ = system()
    with pytest.raises(EvidenceUnavailable):
        reader.read(customer, equipment)
    assert team.calls == 0


@pytest.mark.parametrize("change", ["version", "scope", "expiry", "policy"])
def test_cached_evidence_cannot_be_rebound_or_refreshed(change: str) -> None:
    reader, team, repo, _ = system()
    reader.read("DEMO-FAB", "DEMO-PT-001")
    customer = "DEMO-FAB"
    if change == "version":
        repo.change_version = True
    elif change == "scope":
        customer = "DEMO-NW"
    elif change == "expiry":
        assert team.binding
        reader.now = lambda: team.binding.expires_at  # type: ignore[union-attr]
    else:
        reader.backend.policy_sha256 = "0" * 64
    with pytest.raises(EvidenceUnavailable):
        reader.read(customer, "DEMO-PT-001")
    assert team.calls == 1


def test_revocation_while_backend_is_in_flight_prevents_late_receipt() -> None:
    reader, _, _, _ = system()
    broker = reader.broker

    class AbortDuringRead:
        def read(self, binding: EvidenceBinding, name: str, args: dict[str, str]) -> dict[str, Any]:
            broker.abort(binding)
            return {"evidence": "late result"}

    broker.backend = AbortDuringRead()
    with pytest.raises(EvidenceUnavailable):
        reader.read("DEMO-FAB", "DEMO-PT-001")
    assert reader.active_binding
    assert not broker.store._read(reader.active_binding.request_id, "scope-document_analyst")[
        "receipts"
    ]

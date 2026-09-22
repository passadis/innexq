"""Service Coverage Renewal broker scopes: role/tool matrix and finish guards (ADR-018)."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from innexq_api.evidence_broker import (
    PACK_ROLES,
    EvidenceBinding,
    EvidenceBroker,
    EvidenceDenied,
    EvidenceStore,
)
from pydantic import SecretStr

from tests.unit.test_certificate_store import Container
from tests.unit.test_certificates import NOW, TENANT
from tests.unit.test_evidence_broker import AGENT, Backend

DOCUMENT = "DEMO-COV-001-COVERAGE-PDF"
RENEWAL_ROLES = PACK_ROLES["service-coverage-renewal"]


def setup() -> tuple[EvidenceBroker, EvidenceBinding, Container, Backend, dict[str, SecretStr]]:
    container, backend = Container(), Backend()
    broker = EvidenceBroker(EvidenceStore(container), backend, now=lambda: NOW)
    binding = EvidenceBinding(
        request_id=uuid4(),
        workflow_request_id=uuid4(),
        tenant_id=TENANT,
        agent_principal_id=AGENT,
        customer_id="DEMO-FAB",
        equipment_id="DEMO-COV-001",
        source_version="coverage-registry-v1",
        policy_sha256="b" * 64,
        document_hashes={DOCUMENT: "a" * 64},
        expires_at=NOW + timedelta(minutes=5),
        workflow_pack="service-coverage-renewal",
    )
    handles = broker.issue(binding)
    return broker, binding, container, backend, dict(handles)


def complete_calls() -> dict[str, list[tuple[str, dict[str, str]]]]:
    return {
        "renewal_coordinator": [("get_equipment_record", {})],
        "coverage_billing": [
            ("list_service_coverage_documents", {}),
            ("analyze_service_coverage_document", {"document_id": DOCUMENT}),
            ("retrieve_renewal_policy", {"query": "renewal window"}),
            ("calculate_renewal_quote", {"base_amount": "8500.00"}),
        ],
    }


def test_renewal_pack_issues_exactly_its_two_role_scopes() -> None:
    _broker, binding, container, _, handles = setup()
    assert set(handles) == set(RENEWAL_ROLES)
    assert len(container.items) == 2
    assert all(key[0] == f"evidence:{binding.request_id}" for key in container.items)


def test_complete_renewal_investigation_finishes_with_five_receipts() -> None:
    broker, binding, _, backend, handles = setup()
    ids: dict[str, list[UUID]] = {}
    for role, calls in complete_calls().items():
        ids[role] = [
            UUID(broker.call(TENANT, AGENT, handles[role], name, args)["receipt_id"])
            for name, args in calls
        ]
    results = broker.finish(binding, ids)
    assert len(results) == 5
    assert {item["tool_name"] for item in results} == {
        "get_equipment_record",
        "list_service_coverage_documents",
        "analyze_service_coverage_document",
        "retrieve_renewal_policy",
        "calculate_renewal_quote",
    }
    assert len(backend.calls) == 5


@pytest.mark.parametrize(
    ("role", "name", "arguments"),
    [
        ("renewal_coordinator", "calculate_renewal_quote", {"base_amount": "8500.00"}),
        ("renewal_coordinator", "retrieve_renewal_policy", {"query": "window"}),
        ("coverage_billing", "get_equipment_record", {}),
        ("coverage_billing", "analyze_document", {"document_id": DOCUMENT}),
        ("coverage_billing", "retrieve_policy", {"query": "certificate policy"}),
    ],
)
def test_cross_role_and_cross_pack_tools_are_denied(
    role: str, name: str, arguments: dict[str, str]
) -> None:
    broker, _, _, backend, handles = setup()
    with pytest.raises(EvidenceDenied):
        broker.call(TENANT, AGENT, handles[role], name, arguments)
    assert backend.calls == []


@pytest.mark.parametrize(
    "base_amount",
    ["8500", "8500.5", "-100.00", "1e3", "8500.00 ", "NaN", "100.000"],
)
def test_quote_tool_refuses_non_decimal_inputs(base_amount: str) -> None:
    broker, _, _, backend, handles = setup()
    with pytest.raises(EvidenceDenied):
        broker.call(
            TENANT,
            AGENT,
            handles["coverage_billing"],
            "calculate_renewal_quote",
            {"base_amount": base_amount},
        )
    assert backend.calls == []


def test_finish_requires_analysis_of_every_scoped_document() -> None:
    broker, binding, _, _, handles = setup()
    calls = complete_calls()
    calls["coverage_billing"] = [
        item for item in calls["coverage_billing"] if item[0] != "analyze_service_coverage_document"
    ]
    ids: dict[str, list[UUID]] = {}
    for role, role_calls in calls.items():
        ids[role] = [
            UUID(broker.call(TENANT, AGENT, handles[role], name, args)["receipt_id"])
            for name, args in role_calls
        ]
    with pytest.raises(EvidenceDenied, match="mandatory"):
        broker.finish(binding, ids)


def test_finish_requires_both_renewal_roles() -> None:
    broker, binding, _, _, handles = setup()
    receipt = broker.call(TENANT, AGENT, handles["renewal_coordinator"], "get_equipment_record", {})
    with pytest.raises(EvidenceDenied, match="complete unexpired evidence"):
        broker.finish(binding, {"renewal_coordinator": [UUID(receipt["receipt_id"])]})


def test_certificate_handles_cannot_reach_renewal_scopes() -> None:
    from tests.unit.test_evidence_broker import setup as certificate_setup

    broker, _, _, _, cert_handles = certificate_setup()
    with pytest.raises(EvidenceDenied):
        broker.call(
            TENANT,
            AGENT,
            cert_handles["equipment_service"],
            "calculate_renewal_quote",
            {"base_amount": "8500.00"},
        )

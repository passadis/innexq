"""Fixture-backed trusted source reader and agent-directed citations for renewals."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from innexq_api.coverage_sources import (
    CoverageFixtureError,
    FixtureCoverageInvestigator,
    FixtureCoverageSourceReader,
)
from innexq_contracts.coverage_renewal import CoverageRenewalRecord, CoverageRenewalState
from innexq_gateway.coverage import evaluate_renewal_eligibility

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = str(ROOT / "corpus" / "fixtures" / "coverage-scenarios.json")
POLICY = str(ROOT / "corpus" / "fixtures" / "coverage-renewal-policy-v1.json")
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def reader() -> FixtureCoverageSourceReader:
    return FixtureCoverageSourceReader(SCENARIOS, POLICY)


def record(customer_id: str, equipment_id: str) -> CoverageRenewalRecord:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    return CoverageRenewalRecord(
        request_id=uuid4(),
        state=CoverageRenewalState.EVIDENCE_ASSEMBLING,
        customer_id=customer_id,
        equipment_id=equipment_id,
        created_at=now,
        updated_at=now,
    )


def test_eligible_scenario_sources_pass_every_policy_check() -> None:
    src = reader().sources("DEMO-FAB", "DEMO-COV-001")
    decision = evaluate_renewal_eligibility("DEMO-FAB", "DEMO-COV-001", src, NOW)
    assert decision.outcome == "eligible"
    assert all(check.verdict == "pass" for check in decision.checks)


def test_base_amount_and_customer_name_come_from_the_registry() -> None:
    r = reader()
    assert r.base_amount("DEMO-FAB", "DEMO-COV-001") == "8500.00"
    assert r.customer_name("DEMO-FAB") == "Fabrikam Industrial AB"


def test_unknown_equipment_yields_empty_sources_and_no_price() -> None:
    r = reader()
    empty = r.sources("DEMO-FAB", "DEMO-NOPE")
    assert empty.ownership is None and empty.document is None
    with pytest.raises(CoverageFixtureError):
        r.base_amount("DEMO-FAB", "DEMO-NOPE")


def test_unknown_customer_has_no_registered_name() -> None:
    with pytest.raises(CoverageFixtureError):
        reader().customer_name("DEMO-GHOST")


def test_missing_document_scenario_exposes_no_document_source() -> None:
    src = reader().sources("DEMO-NW", "DEMO-COV-004")
    assert src.document is None
    assert src.ownership is not None


def test_investigator_cites_the_registered_document_and_price() -> None:
    r = reader()
    facts, receipts, cited = FixtureCoverageInvestigator(r).investigate(
        record("DEMO-FAB", "DEMO-COV-001")
    )
    assert len(facts) == 1 and facts[0].label == "coverage_until"
    assert len(receipts) == 2
    assert cited == r.base_amount("DEMO-FAB", "DEMO-COV-001")


def test_investigator_holds_when_there_is_no_document_to_cite() -> None:
    facts, receipts, cited = FixtureCoverageInvestigator(reader()).investigate(
        record("DEMO-NW", "DEMO-COV-004")
    )
    assert facts == () and receipts == () and cited is None


def test_investigator_holds_for_unknown_equipment() -> None:
    facts, receipts, cited = FixtureCoverageInvestigator(reader()).investigate(
        record("DEMO-FAB", "DEMO-UNKNOWN")
    )
    assert facts == () and receipts == () and cited is None


def test_corrupt_corpus_paths_fail_fast() -> None:
    with pytest.raises(CoverageFixtureError):
        FixtureCoverageSourceReader("does-not-exist.json", POLICY)

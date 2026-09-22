"""Eligibility engine tests driven by the synthetic coverage scenario fixtures."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from innexq_contracts.certificates import OwnershipSource
from innexq_contracts.coverage_renewal import (
    BillingProfileSource,
    CoverageDocumentSource,
    CoverageEvidenceSources,
    EquipmentStatusSource,
    RenewalPolicySource,
)
from innexq_gateway.coverage import (
    COVERAGE_PRICE_RULE_ID,
    COVERAGE_PRICE_RULE_VERSION,
    coverage_is_current,
    coverage_period,
    evaluate_renewal_eligibility,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads(
    (ROOT / "corpus" / "fixtures" / "coverage-scenarios.json").read_text(encoding="utf-8")
)
NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
OBSERVED = datetime.fromisoformat(FIXTURE["as_of"])
FRESH_UNTIL = datetime.fromisoformat(FIXTURE["fresh_until"])
STAMP = {"source_version": "2026-09-22", "observed_at": OBSERVED, "fresh_until": FRESH_UNTIL}


def scenario(name: str) -> dict[str, Any]:
    return next(item for item in FIXTURE["scenarios"] if item["scenario"] == name)


def sources_for(data: dict[str, Any]) -> CoverageEvidenceSources:
    identity = {
        "customer_id": data["customer_id"],
        "equipment_id": data["equipment_id"],
        "serial_number": data["serial_number"],
    }
    document = None
    if data["document"] is not None:
        raw = data["document"]
        document = CoverageDocumentSource(
            **STAMP,
            **identity,
            document_id=raw["document_id"],
            document_version=raw["document_version"],
            sha256=raw["sha256"],
            document_type=raw["document_type"],
            coverage_from=datetime.fromisoformat(raw["coverage_from"]),
            coverage_until=datetime.fromisoformat(raw["coverage_until"]),
            accessible=raw["accessible"],
            registry_document_version=raw["document_version"],
            registry_sha256=raw["sha256"],
        )
    billing = data["billing_profile"]
    return CoverageEvidenceSources(
        ownership=OwnershipSource(**STAMP, **identity),
        document=document,
        equipment=EquipmentStatusSource(**STAMP, **identity, status=data["equipment_status"]),
        billing=BillingProfileSource(
            **STAMP,
            customer_id=data["customer_id"],
            legal_name=billing["legal_name"],
            address_line=billing["address_line"],
            city=billing["city"],
            country_code=billing["country_code"],
            vat_id=billing["vat_id"],
        ),
        policy=RenewalPolicySource(
            **STAMP,
            policy_id="COVERAGE-RENEWAL-001",
            policy_version=1,
            pricing_rule_id=COVERAGE_PRICE_RULE_ID,
            pricing_rule_version=COVERAGE_PRICE_RULE_VERSION,
        ),
    )


def evaluate(name: str) -> tuple[dict[str, Any], Any]:
    data = scenario(name)
    decision = evaluate_renewal_eligibility(
        data["customer_id"], data["equipment_id"], sources_for(data), NOW
    )
    return data, decision


def reasons(decision: Any) -> dict[str, str]:
    return {check.name: check.reason for check in decision.checks if check.verdict != "pass"}


def test_expired_eligible_coverage_is_eligible() -> None:
    _, decision = evaluate("expired_eligible")
    assert decision.outcome == "eligible"
    assert all(check.verdict == "pass" for check in decision.checks)


def test_current_coverage_is_outside_the_renewal_window() -> None:
    data, decision = evaluate("current_coverage")
    assert decision.outcome == "renewal_hold"
    assert reasons(decision) == {"renewal_window": "outside_renewal_window"}
    document = sources_for(data).document
    assert document is not None and coverage_is_current(document, NOW)


def test_safety_document_is_non_renewable() -> None:
    _, decision = evaluate("non_renewable_safety_document")
    assert decision.outcome == "renewal_hold"
    assert reasons(decision)["document_type"] == "non_renewable_document"


def test_missing_document_holds_safely() -> None:
    _, decision = evaluate("missing_evidence")
    assert decision.outcome == "renewal_hold"
    held = reasons(decision)
    assert held["document_type"] == "missing_evidence"
    assert held["evidence_quality"] == "missing_evidence"


def test_incomplete_billing_profile_holds() -> None:
    _, decision = evaluate("incomplete_billing_profile")
    assert reasons(decision)["billing_profile"] == "billing_profile_incomplete"


def test_inactive_equipment_is_not_eligible() -> None:
    _, decision = evaluate("inactive_equipment")
    assert reasons(decision)["equipment_eligibility"] == "equipment_not_eligible"


def test_wrong_customer_fails_ownership_before_anything_else() -> None:
    data = scenario("expired_eligible")
    decision = evaluate_renewal_eligibility(
        "CUS-SOMEONE-ELSE", data["equipment_id"], sources_for(data), NOW
    )
    assert decision.outcome == "renewal_hold"
    assert reasons(decision)["ownership"] == "ownership_mismatch"


def test_registry_mismatch_is_a_hard_fail() -> None:
    data = scenario("expired_eligible")
    sources = sources_for(data)
    assert sources.document is not None
    tampered = sources.document.model_copy(update={"registry_sha256": "f" * 64})
    decision = evaluate_renewal_eligibility(
        data["customer_id"],
        data["equipment_id"],
        sources.model_copy(update={"document": tampered}),
        NOW,
    )
    assert reasons(decision)["registry_integrity"] == "registry_mismatch"


def test_stale_evidence_is_unknown_not_pass() -> None:
    data = scenario("expired_eligible")
    sources = sources_for(data)
    stale_now = datetime(2028, 1, 1, tzinfo=UTC)
    decision = evaluate_renewal_eligibility(
        data["customer_id"], data["equipment_id"], sources, stale_now
    )
    assert decision.outcome == "renewal_hold"
    assert reasons(decision)["ownership"] == "stale_evidence"


def test_superseded_policy_holds() -> None:
    data = scenario("expired_eligible")
    sources = sources_for(data)
    assert sources.policy is not None
    old = sources.policy.model_copy(update={"pricing_rule_version": "2025-01-01"})
    decision = evaluate_renewal_eligibility(
        data["customer_id"],
        data["equipment_id"],
        sources.model_copy(update={"policy": old}),
        NOW,
    )
    assert reasons(decision)["policy_currency"] == "policy_superseded"


def test_conflicting_serials_are_flagged() -> None:
    data = scenario("expired_eligible")
    sources = sources_for(data)
    assert sources.equipment is not None
    other = sources.equipment.model_copy(update={"serial_number": "COV-SERIAL-9999"})
    decision = evaluate_renewal_eligibility(
        data["customer_id"],
        data["equipment_id"],
        sources.model_copy(update={"equipment": other}),
        NOW,
    )
    assert reasons(decision)["evidence_quality"] == "conflicting_evidence"


def test_document_source_rejects_inverted_coverage_dates() -> None:
    data = scenario("expired_eligible")
    raw = data["document"]
    with pytest.raises(ValidationError):
        CoverageDocumentSource(
            **STAMP,
            customer_id=data["customer_id"],
            equipment_id=data["equipment_id"],
            serial_number=data["serial_number"],
            document_id=raw["document_id"],
            document_version="1",
            sha256=raw["sha256"],
            document_type="service_coverage_certificate",
            coverage_from=datetime(2026, 8, 1, tzinfo=UTC),
            coverage_until=datetime(2025, 8, 1, tzinfo=UTC),
            accessible=True,
            registry_document_version="1",
            registry_sha256=raw["sha256"],
        )


def test_coverage_period_is_twelve_calendar_months_from_manager_approval() -> None:
    assert coverage_period(date(2026, 9, 22)) == (date(2026, 9, 22), date(2027, 9, 22))


def test_coverage_period_clamps_month_end() -> None:
    assert coverage_period(date(2026, 1, 31), months=1) == (date(2026, 1, 31), date(2026, 2, 28))
    assert coverage_period(date(2024, 1, 31), months=1) == (date(2024, 1, 31), date(2024, 2, 29))


def test_coverage_period_rejects_nonpositive_duration() -> None:
    with pytest.raises(ValueError, match="at least one month"):
        coverage_period(date(2026, 9, 22), months=0)

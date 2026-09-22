"""Service Coverage Renewal contract validation and package hashing tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from innexq_contracts.coverage_renewal import (
    SYNTHETIC_INVOICE_NOTICE,
    CoverageRenewalRecord,
    CoverageRenewalState,
    EligibilityCheck,
    InvoiceLineItem,
    compute_package_hash,
)
from pydantic import ValidationError

from tests.unit.coverage_factories import (
    HASH_B,
    NOW,
    invoice_preview,
    package,
    passing_eligibility,
    quote,
)


def test_eligibility_check_reason_must_match_verdict() -> None:
    with pytest.raises(ValidationError):
        EligibilityCheck(name="ownership", verdict="pass", reason="missing_evidence")
    with pytest.raises(ValidationError):
        EligibilityCheck(name="ownership", verdict="fail", reason="passed")


def test_eligibility_requires_all_nine_ordered_checks() -> None:
    decision = passing_eligibility()
    checks = (
        *decision.checks[:8],
        EligibilityCheck(name="billing_profile", verdict="unknown", reason="missing_evidence"),
    )
    with pytest.raises(ValidationError):
        passing_eligibility(checks=checks)  # unknown check cannot stay eligible
    held = passing_eligibility(checks=checks, outcome="renewal_hold")
    assert held.outcome == "renewal_hold"
    with pytest.raises(ValidationError):
        passing_eligibility(checks=decision.checks[::-1])  # order is part of the contract


def test_quote_totals_are_checked_deterministically() -> None:
    with pytest.raises(ValidationError):
        quote(total_amount="1240.01")
    with pytest.raises(ValidationError):
        quote(base_amount="1000")  # two decimal places are mandatory


def test_invoice_preview_enforces_notice_and_arithmetic() -> None:
    preview = invoice_preview()
    assert preview.notice == SYNTHETIC_INVOICE_NOTICE
    with pytest.raises(ValidationError):
        invoice_preview(subtotal="999.00")
    with pytest.raises(ValidationError):
        invoice_preview(
            line_items=(
                InvoiceLineItem(
                    description="x", quantity=2, unit_amount="1000.00", line_amount="1000.00"
                ),
            )
        )


def test_package_requires_eligible_decision() -> None:
    checks = (
        *passing_eligibility().checks[:8],
        EligibilityCheck(
            name="billing_profile", verdict="fail", reason="billing_profile_incomplete"
        ),
    )
    held = passing_eligibility(checks=checks, outcome="renewal_hold")
    with pytest.raises(ValidationError):
        package(eligibility=held)


def test_package_manifest_binding_is_enforced() -> None:
    pkg = package()
    foreign_manifest = pkg.execution_manifest.model_copy(update={"request_id": uuid4()})
    with pytest.raises(ValidationError):
        package(execution_manifest=foreign_manifest)


def test_package_hash_is_deterministic_and_change_sensitive() -> None:
    request_id = uuid4()
    manifest_id = uuid4()
    action_id = uuid4()

    def build() -> object:
        pkg = package(request_id=request_id)
        manifest = pkg.execution_manifest.model_copy(update={"manifest_id": manifest_id})
        action = manifest.actions[0].model_copy(update={"action_id": action_id})
        manifest = manifest.model_copy(update={"actions": (action,)})
        return pkg.model_copy(update={"execution_manifest": manifest})

    first, second = build(), build()
    assert compute_package_hash(first) == compute_package_hash(second)

    changed_price = first.model_copy(
        update={"quote": quote(base_amount="1100.00", vat_amount="264.00", total_amount="1364.00")}
    )
    assert compute_package_hash(changed_price) != compute_package_hash(first)
    changed_preview = first.model_copy(update={"invoice_preview_sha256": HASH_B[:-1] + "c"})
    assert compute_package_hash(changed_preview) != compute_package_hash(first)


def test_record_consistency_rules() -> None:
    base = {
        "request_id": uuid4(),
        "state": CoverageRenewalState.CUSTOMER_REQUESTED,
        "customer_id": "CUS-FABRIKAM-SE",
        "equipment_id": "PT-001",
        "created_at": NOW,
        "updated_at": NOW,
    }
    record = CoverageRenewalRecord(**base)
    assert record.workflow_pack == "service-coverage-renewal"

    with pytest.raises(ValidationError):
        CoverageRenewalRecord(**base, package=package())  # hash must accompany package
    with pytest.raises(ValidationError):
        CoverageRenewalRecord(**{**base, "updated_at": datetime(2026, 9, 21, tzinfo=UTC)})

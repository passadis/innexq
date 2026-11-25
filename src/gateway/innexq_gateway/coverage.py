"""Deterministic Service Coverage Renewal eligibility, pricing and dates (ADR-018).

Policy source: docs/security/service-coverage-renewal-policy-v1.md and
corpus/fixtures/coverage-renewal-policy-v1.json. Callers must never accept
these verdicts or amounts from model output; the controller recomputes here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

from innexq_contracts.coverage_renewal import (
    COVERAGE_POLICY_ID,
    COVERAGE_POLICY_VERSION,
    ELIGIBILITY_CHECK_ORDER,
    BillingProfileSource,
    CoverageDocumentSource,
    CoverageEvidenceSources,
    EligibilityCheck,
    EligibilityCheckName,
    EligibilityDecision,
    EligibilityHoldReason,
    EligibilityVerdict,
    EquipmentStatusSource,
    RenewalPolicySource,
    RenewalQuote,
)

from innexq_gateway.pricing import PricingInputError, _decimal

COVERAGE_TOOL_VERSION = "1.0.0"
COVERAGE_PRICE_RULE_ID = "coverage-renewal-price"
COVERAGE_PRICE_RULE_VERSION = "2026-09-22"
RENEWAL_WINDOW_DAYS = 60
COVERAGE_MONTHS = 12
VAT_RATE_PERCENT = Decimal("24.00")
_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")

_Verdict = tuple[EligibilityVerdict, EligibilityHoldReason]
_PASS: _Verdict = ("pass", "passed")


def _fresh(stamp: object, now: datetime) -> bool:
    observed_at = getattr(stamp, "observed_at", None)
    fresh_until = getattr(stamp, "fresh_until", None)
    return (
        isinstance(observed_at, datetime)
        and isinstance(fresh_until, datetime)
        and observed_at <= now < fresh_until
    )


def _check_ownership(
    customer_id: str, equipment_id: str, sources: CoverageEvidenceSources, now: datetime
) -> _Verdict:
    ownership = sources.ownership
    if ownership is None:
        return "unknown", "missing_evidence"
    if not _fresh(ownership, now):
        return "unknown", "stale_evidence"
    if ownership.customer_id != customer_id or ownership.equipment_id != equipment_id:
        return "fail", "ownership_mismatch"
    return _PASS


def _check_document_type(document: CoverageDocumentSource | None, now: datetime) -> _Verdict:
    if document is None:
        return "unknown", "missing_evidence"
    if not _fresh(document, now):
        return "unknown", "stale_evidence"
    if document.document_type != "service_coverage_certificate":
        return "fail", "non_renewable_document"
    return _PASS


def _check_document_identity(
    customer_id: str,
    equipment_id: str,
    sources: CoverageEvidenceSources,
) -> _Verdict:
    document, ownership = sources.document, sources.ownership
    if document is None or ownership is None:
        return "unknown", "missing_evidence"
    if (
        document.customer_id != customer_id
        or document.equipment_id != equipment_id
        or document.serial_number != ownership.serial_number
    ):
        return "fail", "document_identity_mismatch"
    return _PASS


def _check_registry_integrity(document: CoverageDocumentSource | None) -> _Verdict:
    if document is None:
        return "unknown", "missing_evidence"
    if document.accessible is not True:
        return "unknown", "inaccessible_evidence"
    if document.registry_document_version is None or document.registry_sha256 is None:
        return "unknown", "missing_evidence"
    if (
        document.document_version != document.registry_document_version
        or document.sha256 != document.registry_sha256
    ):
        return "fail", "registry_mismatch"
    return _PASS


def _check_renewal_window(document: CoverageDocumentSource | None, now: datetime) -> _Verdict:
    if document is None:
        return "unknown", "missing_evidence"
    window_end = now + timedelta(days=RENEWAL_WINDOW_DAYS)
    if document.coverage_until > window_end:
        return "fail", "outside_renewal_window"
    return _PASS


def _check_equipment(
    customer_id: str, equipment_id: str, equipment: EquipmentStatusSource | None, now: datetime
) -> _Verdict:
    if equipment is None:
        return "unknown", "missing_evidence"
    if not _fresh(equipment, now):
        return "unknown", "stale_evidence"
    if equipment.customer_id != customer_id or equipment.equipment_id != equipment_id:
        return "fail", "conflicting_evidence"
    if equipment.status != "active":
        return "fail", "equipment_not_eligible"
    return _PASS


def _check_evidence_quality(sources: CoverageEvidenceSources, now: datetime) -> _Verdict:
    stamps = (
        sources.ownership,
        sources.document,
        sources.equipment,
        sources.billing,
        sources.policy,
    )
    if any(stamp is None for stamp in stamps):
        return "unknown", "missing_evidence"
    if not all(_fresh(stamp, now) for stamp in stamps):
        return "unknown", "stale_evidence"
    assert sources.ownership is not None and sources.document is not None  # noqa: S101
    assert sources.equipment is not None  # noqa: S101
    serials = {
        sources.ownership.serial_number,
        sources.document.serial_number,
        sources.equipment.serial_number,
    }
    if len(serials) != 1:
        return "unknown", "conflicting_evidence"
    return _PASS


def _check_policy_currency(policy: RenewalPolicySource | None, now: datetime) -> _Verdict:
    if policy is None:
        return "unknown", "missing_evidence"
    if not _fresh(policy, now):
        return "unknown", "stale_evidence"
    if (
        policy.policy_id != COVERAGE_POLICY_ID
        or policy.policy_version != COVERAGE_POLICY_VERSION
        or policy.pricing_rule_id != COVERAGE_PRICE_RULE_ID
        or policy.pricing_rule_version != COVERAGE_PRICE_RULE_VERSION
    ):
        return "fail", "policy_superseded"
    return _PASS


def _check_billing(billing: BillingProfileSource | None, now: datetime) -> _Verdict:
    if billing is None:
        return "unknown", "missing_evidence"
    if not _fresh(billing, now):
        return "unknown", "stale_evidence"
    required = (billing.legal_name, billing.address_line, billing.city, billing.country_code)
    if any(value is None or not value.strip() for value in required):
        return "fail", "billing_profile_incomplete"
    return _PASS


def evaluate_renewal_eligibility(
    customer_id: str,
    equipment_id: str,
    sources: CoverageEvidenceSources,
    now: datetime,
) -> EligibilityDecision:
    """Evaluate the nine ordered policy checks; any non-pass verdict holds the renewal."""

    verdicts: dict[EligibilityCheckName, _Verdict] = {
        "ownership": _check_ownership(customer_id, equipment_id, sources, now),
        "document_type": _check_document_type(sources.document, now),
        "document_identity": _check_document_identity(customer_id, equipment_id, sources),
        "registry_integrity": _check_registry_integrity(sources.document),
        "renewal_window": _check_renewal_window(sources.document, now),
        "equipment_eligibility": _check_equipment(
            customer_id, equipment_id, sources.equipment, now
        ),
        "evidence_quality": _check_evidence_quality(sources, now),
        "policy_currency": _check_policy_currency(sources.policy, now),
        "billing_profile": _check_billing(sources.billing, now),
    }
    checks = tuple(
        EligibilityCheck(name=name, verdict=verdicts[name][0], reason=verdicts[name][1])
        for name in ELIGIBILITY_CHECK_ORDER
    )
    outcome: Literal["eligible", "renewal_hold"] = (
        "eligible" if all(check.verdict == "pass" for check in checks) else "renewal_hold"
    )
    return EligibilityDecision(evaluated_at=now, checks=checks, outcome=outcome)


def coverage_is_current(document: CoverageDocumentSource, now: datetime) -> bool:
    """Current coverage returns the existing PDF; renewal is not offered."""

    return document.coverage_until > now + timedelta(days=RENEWAL_WINDOW_DAYS)


def calculate_renewal_quote(
    base_amount: Decimal | str,
    *,
    currency: str = "EUR",
) -> RenewalQuote:
    """Quote one renewal with explicit, reproducible cent rounding.

    VAT rounds half up to cents; the total is base plus VAT so the reported
    amounts always reconcile. Synthetic demo VAT, not fiscal guidance.
    """

    if currency != "EUR":
        raise PricingInputError("coverage renewal policy v1 supports EUR only")
    base = _decimal(base_amount, "base_amount")
    if base == 0:
        raise PricingInputError("base_amount must be positive")
    with localcontext() as context:
        context.prec = 64
        vat = (base * VAT_RATE_PERCENT / _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)
        total = base + vat
    return RenewalQuote(
        pricing_rule_id=COVERAGE_PRICE_RULE_ID,
        pricing_rule_version=COVERAGE_PRICE_RULE_VERSION,
        currency=currency,
        coverage_months=COVERAGE_MONTHS,
        base_amount=str(base),
        vat_rate_percent=str(VAT_RATE_PERCENT),
        vat_amount=str(vat),
        total_amount=str(total),
    )


def coverage_period(manager_approved_on: date, months: int = COVERAGE_MONTHS) -> tuple[date, date]:
    """Coverage starts on the Manager approval date; never backdated (policy v1)."""

    if months < 1:
        raise ValueError("coverage duration must be at least one month")
    month_index = manager_approved_on.month - 1 + months
    year = manager_approved_on.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp to the last day of the target month (e.g. Jan 31 + 1 month -> Feb 28/29).
    day = manager_approved_on.day
    while True:
        try:
            end = date(year, month, day)
            break
        except ValueError:
            day -= 1
    return manager_approved_on, end

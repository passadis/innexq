"""Shared builders for Service Coverage Renewal contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from innexq_contracts.coverage_renewal import (
    ELIGIBILITY_CHECK_ORDER,
    CoverageExecutionAction,
    CoverageExecutionManifest,
    CoverageSourceFact,
    EligibilityCheck,
    EligibilityDecision,
    InvoiceLineItem,
    InvoicePreview,
    ManagerDecision,
    OperationsDecision,
    PreviousDocumentRef,
    RenewalPackage,
    RenewalQuote,
    compute_package_hash,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
OPERATIONS_OID = "11111111-1111-1111-1111-111111111111"
MANAGER_OID = "22222222-2222-2222-2222-222222222222"


def passing_eligibility(**overrides: Any) -> EligibilityDecision:
    checks = tuple(
        EligibilityCheck(name=name, verdict="pass", reason="passed")
        for name in ELIGIBILITY_CHECK_ORDER
    )
    values: dict[str, Any] = {"evaluated_at": NOW, "checks": checks, "outcome": "eligible"}
    values.update(overrides)
    return EligibilityDecision(**values)


def quote(**overrides: Any) -> RenewalQuote:
    values: dict[str, Any] = {
        "pricing_rule_id": "coverage-renewal-price",
        "pricing_rule_version": "2026-09-22",
        "currency": "EUR",
        "coverage_months": 12,
        "base_amount": "1000.00",
        "vat_rate_percent": "24.00",
        "vat_amount": "240.00",
        "total_amount": "1240.00",
    }
    values.update(overrides)
    return RenewalQuote(**values)


def invoice_preview(**overrides: Any) -> InvoicePreview:
    values: dict[str, Any] = {
        "currency": "EUR",
        "line_items": (
            InvoiceLineItem(
                description="Service coverage renewal, 12 months",
                quantity=1,
                unit_amount="1000.00",
                line_amount="1000.00",
            ),
        ),
        "subtotal": "1000.00",
        "vat_rate_percent": "24.00",
        "vat_amount": "240.00",
        "total_amount": "1240.00",
    }
    values.update(overrides)
    return InvoicePreview(**values)


def package(**overrides: Any) -> RenewalPackage:
    request_id = overrides.pop("request_id", uuid4())
    package_version = overrides.pop("package_version", 1)
    values: dict[str, Any] = {
        "request_id": request_id,
        "package_version": package_version,
        "customer_id": "CUS-FABRIKAM-SE",
        "equipment_id": "PT-001",
        "serial_number": "SN-0001",
        "previous_document": PreviousDocumentRef(
            document_id="DOC-COV-0001", document_version="1", sha256=HASH_A
        ),
        "source_facts": (
            CoverageSourceFact(
                document_id="DOC-COV-0001",
                document_version="1",
                sha256=HASH_A,
                label="coverage_end",
                value="2026-08-31",
                page=1,
            ),
        ),
        "eligibility": passing_eligibility(),
        "coverage_months": 12,
        "quote": quote(),
        "invoice_preview": invoice_preview(),
        "certificate_preview_sha256": HASH_A,
        "invoice_preview_sha256": HASH_B,
        "certificate_template_version": "coverage-cert-v1",
        "invoice_template_version": "coverage-invoice-v1",
        "execution_manifest": CoverageExecutionManifest(
            manifest_id=uuid4(),
            request_id=request_id,
            package_version=package_version,
            actions=(
                CoverageExecutionAction(
                    action_id=uuid4(),
                    action_type="allocate_invoice_number",
                    parameters={"format": "SYN-INV-{year}-{sequence:05d}"},
                    idempotency_key=f"invoice-{request_id}",
                ),
            ),
        ),
    }
    values.update(overrides)
    return RenewalPackage(**values)


def operations_decision(pkg: RenewalPackage, **overrides: Any) -> OperationsDecision:
    values: dict[str, Any] = {
        "decision_id": uuid4(),
        "request_id": pkg.request_id,
        "package_version": pkg.package_version,
        "package_hash": compute_package_hash(pkg),
        "actor_object_id": OPERATIONS_OID,
        "decision": "approve",
        "submitted_at": NOW,
    }
    values.update(overrides)
    return OperationsDecision(**values)


def manager_decision(
    pkg: RenewalPackage, operations: OperationsDecision, **overrides: Any
) -> ManagerDecision:
    values: dict[str, Any] = {
        "decision_id": uuid4(),
        "request_id": pkg.request_id,
        "package_version": pkg.package_version,
        "package_hash": compute_package_hash(pkg),
        "actor_object_id": MANAGER_OID,
        "decision": "approve",
        "operations_decision_id": operations.decision_id,
        "operations_note_sha256": operations.note_sha256,
        "submitted_at": NOW,
    }
    values.update(overrides)
    return ManagerDecision(**values)

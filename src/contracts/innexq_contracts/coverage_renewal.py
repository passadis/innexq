"""Service Coverage Renewal contracts and state guards (ADR-018).

Separate from the legacy Run state machine and from Certificate Fulfilment.
Only the controller performs transitions; models never derive dates or money.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from innexq_contracts.certificates import OwnershipSource, SourceStamp
from innexq_contracts.hashing import canonical_json_bytes
from innexq_contracts.models import NonEmptyText, PositiveVersion, Sha256Hex, StrictContract

COVERAGE_POLICY_ID: Literal["COVERAGE-RENEWAL-001"] = "COVERAGE-RENEWAL-001"
COVERAGE_POLICY_VERSION: Literal[1] = 1
SYNTHETIC_INVOICE_NOTICE: Literal["SYNTHETIC DEMO — NOT A FISCAL OR TAX DOCUMENT"] = (
    "SYNTHETIC DEMO — NOT A FISCAL OR TAX DOCUMENT"
)

MoneyText = Annotated[str, Field(pattern=r"^\d+\.\d{2}$")]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class CoverageRenewalState(StrEnum):
    CUSTOMER_REQUESTED = "CUSTOMER_REQUESTED"
    EVIDENCE_ASSEMBLING = "EVIDENCE_ASSEMBLING"
    ELIGIBILITY_VERIFIED = "ELIGIBILITY_VERIFIED"
    PACKAGE_DRAFTED = "PACKAGE_DRAFTED"
    AWAITING_OPERATIONS_APPROVAL = "AWAITING_OPERATIONS_APPROVAL"
    OPERATIONS_APPROVED = "OPERATIONS_APPROVED"
    AWAITING_MANAGER_APPROVAL = "AWAITING_MANAGER_APPROVAL"
    MANAGER_APPROVED = "MANAGER_APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    EVIDENCE_HOLD = "EVIDENCE_HOLD"
    OPERATIONS_REJECTED = "OPERATIONS_REJECTED"
    MANAGER_REJECTED = "MANAGER_REJECTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    CANCELLED = "CANCELLED"


_PRE_APPROVAL_STATES = frozenset(
    {
        CoverageRenewalState.CUSTOMER_REQUESTED,
        CoverageRenewalState.EVIDENCE_ASSEMBLING,
        CoverageRenewalState.ELIGIBILITY_VERIFIED,
        CoverageRenewalState.PACKAGE_DRAFTED,
        CoverageRenewalState.EVIDENCE_HOLD,
    }
)

_COVERAGE_TRANSITIONS: dict[CoverageRenewalState, frozenset[CoverageRenewalState]] = {
    CoverageRenewalState.CUSTOMER_REQUESTED: frozenset({CoverageRenewalState.EVIDENCE_ASSEMBLING}),
    CoverageRenewalState.EVIDENCE_ASSEMBLING: frozenset(
        {CoverageRenewalState.ELIGIBILITY_VERIFIED, CoverageRenewalState.EVIDENCE_HOLD}
    ),
    CoverageRenewalState.ELIGIBILITY_VERIFIED: frozenset(
        {CoverageRenewalState.PACKAGE_DRAFTED, CoverageRenewalState.EVIDENCE_HOLD}
    ),
    CoverageRenewalState.PACKAGE_DRAFTED: frozenset(
        {CoverageRenewalState.AWAITING_OPERATIONS_APPROVAL, CoverageRenewalState.EVIDENCE_HOLD}
    ),
    CoverageRenewalState.AWAITING_OPERATIONS_APPROVAL: frozenset(
        {CoverageRenewalState.OPERATIONS_APPROVED, CoverageRenewalState.OPERATIONS_REJECTED}
    ),
    CoverageRenewalState.OPERATIONS_APPROVED: frozenset(
        {CoverageRenewalState.AWAITING_MANAGER_APPROVAL}
    ),
    CoverageRenewalState.AWAITING_MANAGER_APPROVAL: frozenset(
        {CoverageRenewalState.MANAGER_APPROVED, CoverageRenewalState.MANAGER_REJECTED}
    ),
    CoverageRenewalState.MANAGER_APPROVED: frozenset({CoverageRenewalState.EXECUTING}),
    CoverageRenewalState.EXECUTING: frozenset(
        {CoverageRenewalState.COMPLETED, CoverageRenewalState.EXECUTION_FAILED}
    ),
    CoverageRenewalState.EXECUTION_FAILED: frozenset({CoverageRenewalState.EXECUTING}),
    CoverageRenewalState.EVIDENCE_HOLD: frozenset({CoverageRenewalState.EVIDENCE_ASSEMBLING}),
    CoverageRenewalState.COMPLETED: frozenset(),
    CoverageRenewalState.OPERATIONS_REJECTED: frozenset(),
    CoverageRenewalState.MANAGER_REJECTED: frozenset(),
    CoverageRenewalState.CANCELLED: frozenset(),
}


class InvalidCoverageTransition(ValueError):
    """Raised when a caller requests an unlisted renewal state transition."""


def allowed_coverage_targets(current: CoverageRenewalState) -> frozenset[CoverageRenewalState]:
    """Return all states reachable in one controller-owned transition."""

    targets = _COVERAGE_TRANSITIONS[current]
    if current in _PRE_APPROVAL_STATES:
        targets = targets | {CoverageRenewalState.CANCELLED}
    return targets


def can_coverage_transition(current: CoverageRenewalState, target: CoverageRenewalState) -> bool:
    """Return whether a one-step renewal state transition is explicitly allowed."""

    return target in allowed_coverage_targets(current)


def assert_coverage_transition(current: CoverageRenewalState, target: CoverageRenewalState) -> None:
    """Fail closed when a renewal state transition is not explicitly allowed."""

    if not can_coverage_transition(current, target):
        raise InvalidCoverageTransition(
            f"transition from {current.value} to {target.value} is not allowed"
        )


EligibilityCheckName = Literal[
    "ownership",
    "document_type",
    "document_identity",
    "registry_integrity",
    "renewal_window",
    "equipment_eligibility",
    "evidence_quality",
    "policy_currency",
    "billing_profile",
]
ELIGIBILITY_CHECK_ORDER: tuple[EligibilityCheckName, ...] = (
    "ownership",
    "document_type",
    "document_identity",
    "registry_integrity",
    "renewal_window",
    "equipment_eligibility",
    "evidence_quality",
    "policy_currency",
    "billing_profile",
)
EligibilityVerdict = Literal["pass", "fail", "unknown"]
EligibilityHoldReason = Literal[
    "passed",
    "ownership_mismatch",
    "non_renewable_document",
    "document_identity_mismatch",
    "registry_mismatch",
    "outside_renewal_window",
    "equipment_not_eligible",
    "missing_evidence",
    "stale_evidence",
    "conflicting_evidence",
    "inaccessible_evidence",
    "policy_superseded",
    "billing_profile_incomplete",
]


class EligibilityCheck(StrictContract):
    name: EligibilityCheckName
    verdict: EligibilityVerdict
    reason: EligibilityHoldReason

    @model_validator(mode="after")
    def consistent_reason(self) -> Self:
        if (self.verdict == "pass") != (self.reason == "passed"):
            raise ValueError("check verdict must agree with its reason")
        return self


class EligibilityDecision(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    policy_id: Literal["COVERAGE-RENEWAL-001"] = COVERAGE_POLICY_ID
    policy_version: Literal[1] = COVERAGE_POLICY_VERSION
    evaluated_at: AwareDatetime
    checks: Annotated[tuple[EligibilityCheck, ...], Field(min_length=9, max_length=9)]
    outcome: Literal["eligible", "renewal_hold"]

    @model_validator(mode="after")
    def consistent_outcome(self) -> Self:
        if tuple(item.name for item in self.checks) != ELIGIBILITY_CHECK_ORDER:
            raise ValueError("exactly the nine ordered eligibility checks are required")
        passed = all(item.verdict == "pass" for item in self.checks)
        if (self.outcome == "eligible") != passed:
            raise ValueError("eligibility requires all checks to pass")
        return self


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as error:  # pragma: no cover - pattern already constrains
        raise ValueError(f"invalid money value: {value}") from error


class RenewalQuote(StrictContract):
    policy_id: Literal["COVERAGE-RENEWAL-001"] = COVERAGE_POLICY_ID
    policy_version: Literal[1] = COVERAGE_POLICY_VERSION
    pricing_rule_id: NonEmptyText
    pricing_rule_version: NonEmptyText
    currency: CurrencyCode
    coverage_months: Annotated[int, Field(ge=1, le=60)]
    base_amount: MoneyText
    vat_rate_percent: MoneyText
    vat_amount: MoneyText
    total_amount: MoneyText

    @model_validator(mode="after")
    def consistent_totals(self) -> Self:
        if _decimal(self.base_amount) + _decimal(self.vat_amount) != _decimal(self.total_amount):
            raise ValueError("total must equal base plus VAT")
        return self


class InvoiceLineItem(StrictContract):
    description: NonEmptyText
    quantity: Annotated[int, Field(ge=1)]
    unit_amount: MoneyText
    line_amount: MoneyText

    @model_validator(mode="after")
    def consistent_line(self) -> Self:
        if _decimal(self.unit_amount) * self.quantity != _decimal(self.line_amount):
            raise ValueError("line amount must equal quantity times unit amount")
        return self


class InvoicePreview(StrictContract):
    currency: CurrencyCode
    line_items: Annotated[tuple[InvoiceLineItem, ...], Field(min_length=1)]
    subtotal: MoneyText
    vat_rate_percent: MoneyText
    vat_amount: MoneyText
    total_amount: MoneyText
    notice: Literal["SYNTHETIC DEMO — NOT A FISCAL OR TAX DOCUMENT"] = SYNTHETIC_INVOICE_NOTICE

    @model_validator(mode="after")
    def consistent_totals(self) -> Self:
        lines = sum((_decimal(item.line_amount) for item in self.line_items), Decimal("0"))
        if lines != _decimal(self.subtotal):
            raise ValueError("subtotal must equal the sum of line amounts")
        if _decimal(self.subtotal) + _decimal(self.vat_amount) != _decimal(self.total_amount):
            raise ValueError("total must equal subtotal plus VAT")
        return self


class PreviousDocumentRef(StrictContract):
    document_id: NonEmptyText
    document_version: NonEmptyText
    sha256: Sha256Hex


class CoverageSourceFact(StrictContract):
    document_id: NonEmptyText
    document_version: NonEmptyText
    sha256: Sha256Hex
    label: NonEmptyText
    value: NonEmptyText
    page: Annotated[int, Field(ge=1)]


CoverageSpecialist = Literal["renewal_coordinator", "coverage_billing"]
CoverageToolName = Literal[
    "get_equipment_record",
    "list_service_coverage_documents",
    "analyze_service_coverage_document",
    "retrieve_renewal_policy",
    "calculate_renewal_quote",
]


class CoverageToolReceipt(StrictContract):
    attempt_id: UUID
    receipt_id: UUID
    specialist: CoverageSpecialist
    tool_name: CoverageToolName
    source_version: NonEmptyText
    document_id: NonEmptyText | None = None
    completed_at: AwareDatetime


CoverageActionType = Literal[
    "allocate_invoice_number",
    "render_coverage_certificate",
    "render_invoice",
    "store_artifacts",
    "archive_sharepoint_copy",
    "publish_customer_download",
    "send_notification",
]


class CoverageExecutionAction(StrictContract):
    action_id: UUID
    action_type: CoverageActionType
    parameters: dict[str, JsonValue]
    artifact_hash: Sha256Hex | None = None
    idempotency_key: Annotated[str, Field(min_length=16, max_length=200)]


class CoverageExecutionManifest(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    manifest_id: UUID
    request_id: UUID
    package_version: PositiveVersion
    actions: Annotated[tuple[CoverageExecutionAction, ...], Field(min_length=1)]


class RenewalPackage(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    package_version: PositiveVersion
    customer_id: NonEmptyText
    equipment_id: NonEmptyText
    serial_number: NonEmptyText
    previous_document: PreviousDocumentRef
    source_facts: Annotated[tuple[CoverageSourceFact, ...], Field(min_length=1)]
    eligibility: EligibilityDecision
    coverage_start_rule: Literal["manager_approval_date"] = "manager_approval_date"
    coverage_months: Annotated[int, Field(ge=1, le=60)]
    quote: RenewalQuote
    invoice_preview: InvoicePreview
    certificate_preview_sha256: Sha256Hex
    invoice_preview_sha256: Sha256Hex
    certificate_template_version: NonEmptyText
    invoice_template_version: NonEmptyText
    execution_manifest: CoverageExecutionManifest
    tool_receipts: tuple[CoverageToolReceipt, ...] = ()

    @model_validator(mode="after")
    def consistent_package(self) -> Self:
        if self.eligibility.outcome != "eligible":
            raise ValueError("only an eligible decision may be packaged for approval")
        if self.execution_manifest.request_id != self.request_id:
            raise ValueError("execution manifest must reference the same renewal request")
        if self.execution_manifest.package_version != self.package_version:
            raise ValueError("execution manifest must reference the same package version")
        if self.quote.coverage_months != self.coverage_months:
            raise ValueError("quote and package coverage duration must match")
        return self


def compute_package_hash(package: RenewalPackage) -> str:
    """Hash the complete immutable approval package deterministically."""

    envelope: JsonValue = {
        "schema_version": "1.0",
        "renewal_package": package.model_dump(mode="json", exclude_none=False),
    }
    return hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


class OperationsDecision(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID
    request_id: UUID
    package_version: PositiveVersion
    package_hash: Sha256Hex
    actor_object_id: NonEmptyText
    decision: Literal["approve", "reject"]
    note_sha256: Sha256Hex | None = None
    reject_reason: NonEmptyText | None = None
    submitted_at: AwareDatetime

    @model_validator(mode="after")
    def consistent_decision(self) -> Self:
        if (self.decision == "reject") != (self.reject_reason is not None):
            raise ValueError("rejection requires a reason; approval forbids one")
        return self


class ManagerDecision(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID
    request_id: UUID
    package_version: PositiveVersion
    package_hash: Sha256Hex
    actor_object_id: NonEmptyText
    decision: Literal["approve", "reject"]
    operations_decision_id: UUID
    operations_note_sha256: Sha256Hex | None = None
    reject_reason: NonEmptyText | None = None
    submitted_at: AwareDatetime

    @model_validator(mode="after")
    def consistent_decision(self) -> Self:
        if (self.decision == "reject") != (self.reject_reason is not None):
            raise ValueError("rejection requires a reason; approval forbids one")
        return self


def approvals_authorize_execution(
    package: RenewalPackage,
    package_hash: Sha256Hex,
    operations: OperationsDecision,
    manager: ManagerDecision,
) -> bool:
    """Return whether both approvals authorize this exact frozen package.

    Fails closed: any identity overlap, hash or version mismatch, sequence
    violation, or note substitution refuses authorization.
    """

    return (
        operations.decision == "approve"
        and manager.decision == "approve"
        and operations.request_id == package.request_id
        and manager.request_id == package.request_id
        and operations.package_version == package.package_version
        and manager.package_version == package.package_version
        and operations.package_hash == package_hash
        and manager.package_hash == package_hash
        and manager.operations_decision_id == operations.decision_id
        and manager.operations_note_sha256 == operations.note_sha256
        and operations.actor_object_id.casefold() != manager.actor_object_id.casefold()
        and manager.submitted_at >= operations.submitted_at
    )


class CoverageRenewalRecord(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    workflow_pack: Literal["service-coverage-renewal"] = "service-coverage-renewal"
    request_id: UUID
    revision: Annotated[int, Field(ge=0)] = 0
    state: CoverageRenewalState
    customer_id: NonEmptyText
    equipment_id: NonEmptyText
    package: RenewalPackage | None = None
    package_hash: Sha256Hex | None = None
    operations_decision: OperationsDecision | None = None
    manager_decision: ManagerDecision | None = None
    hold_reasons: tuple[EligibilityHoldReason, ...] = ()
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def consistent_record(self) -> Self:
        if (self.package is None) != (self.package_hash is None):
            raise ValueError("a package and its hash must be recorded together")
        if self.package is None and (
            self.operations_decision is not None or self.manager_decision is not None
        ):
            raise ValueError("decisions require a frozen package")
        if self.manager_decision is not None and self.operations_decision is None:
            raise ValueError("a manager decision requires a prior operations decision")
        if self.updated_at < self.created_at:
            raise ValueError("updates cannot precede creation")
        return self


CoverageDocumentType = Literal[
    "service_coverage_certificate",
    "statutory",
    "inspection",
    "conformity",
    "safety",
    "other",
]


class CoverageDocumentSource(SourceStamp):
    customer_id: NonEmptyText
    equipment_id: NonEmptyText
    serial_number: NonEmptyText
    document_id: NonEmptyText
    document_version: NonEmptyText
    sha256: Sha256Hex
    document_type: CoverageDocumentType
    coverage_from: AwareDatetime
    coverage_until: AwareDatetime
    accessible: bool | None
    registry_document_version: NonEmptyText | None
    registry_sha256: Sha256Hex | None

    @model_validator(mode="after")
    def ordered_coverage(self) -> Self:
        if self.coverage_until <= self.coverage_from:
            raise ValueError("coverage end must follow coverage start")
        return self


class EquipmentStatusSource(SourceStamp):
    customer_id: NonEmptyText
    equipment_id: NonEmptyText
    serial_number: NonEmptyText
    status: Literal["active", "inactive", "decommissioned", "uncovered"]


class BillingProfileSource(SourceStamp):
    customer_id: NonEmptyText
    legal_name: str | None
    address_line: str | None
    city: str | None
    country_code: str | None
    vat_id: str | None


class RenewalPolicySource(SourceStamp):
    policy_id: NonEmptyText
    policy_version: Annotated[int, Field(ge=1)]
    pricing_rule_id: NonEmptyText
    pricing_rule_version: NonEmptyText


class CoverageEvidenceSources(StrictContract):
    """Trusted adapters supply facts; agents do not supply executable verdicts."""

    ownership: OwnershipSource | None = None
    document: CoverageDocumentSource | None = None
    equipment: EquipmentStatusSource | None = None
    billing: BillingProfileSource | None = None
    policy: RenewalPolicySource | None = None

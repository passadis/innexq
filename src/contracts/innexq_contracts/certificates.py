"""Certificate source/decision contracts, separate from legacy renewal approvals."""

from decimal import Decimal
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    model_serializer,
    model_validator,
)

from innexq_contracts.customer_conversation import CustomerRequestContext
from innexq_contracts.models import NonEmptyText, Sha256Hex, StrictContract

POLICY_ID: Literal["CERT-RELEASE-001"] = "CERT-RELEASE-001"
POLICY_VERSION: Literal[1] = 1
CheckName = Literal["ownership", "certificate_validity", "service_status"]
CheckVerdict = Literal["pass", "fail", "unknown"]
HoldReason = Literal[
    "passed",
    "missing_evidence",
    "stale_evidence",
    "ownership_mismatch",
    "document_unavailable",
    "document_mismatch",
    "certificate_outside_validity",
    "revoked_or_unknown",
    "service_mismatch",
    "service_not_current",
    "artifact_changed",
    "artifact_unavailable",
]


class SourceStamp(StrictContract):
    source_version: NonEmptyText
    observed_at: AwareDatetime
    fresh_until: AwareDatetime

    @model_validator(mode="after")
    def ordered_freshness(self) -> Self:
        if self.fresh_until <= self.observed_at:
            raise ValueError("freshness end must follow observation")
        return self


class OwnershipSource(SourceStamp):
    customer_id: NonEmptyText
    equipment_id: NonEmptyText
    serial_number: NonEmptyText


class CertificateSource(SourceStamp):
    customer_id: NonEmptyText
    equipment_id: NonEmptyText
    serial_number: NonEmptyText
    document_id: NonEmptyText
    document_version: NonEmptyText
    sha256: Sha256Hex
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    accessible: StrictBool | None
    revoked: StrictBool | None


class ServiceSource(SourceStamp):
    customer_id: NonEmptyText
    equipment_id: NonEmptyText
    serial_number: NonEmptyText
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    in_service: StrictBool | None


class DocumentFieldProof(StrictContract):
    document_id: NonEmptyText
    document_version: NonEmptyText
    sha256: Sha256Hex
    label: NonEmptyText
    value: NonEmptyText
    page: Annotated[int, Field(ge=1)]
    polygon: Annotated[
        tuple[Annotated[Decimal, Field(ge=0, allow_inf_nan=False)], ...],
        Field(min_length=8, max_length=64),
    ]


class SpecialistProof(StrictContract):
    specialist: Literal["request_coordinator", "document_analyst", "equipment_service"]
    response_id: NonEmptyText
    summary: Annotated[str, Field(min_length=1, max_length=2000)]


class EvidenceToolActivity(StrictContract):
    attempt_id: UUID
    receipt_id: UUID
    specialist: Literal["document_analyst", "equipment_service"]
    tool_name: Literal[
        "get_equipment_record", "list_equipment_documents", "analyze_document", "retrieve_policy"
    ]
    source_version: NonEmptyText
    document_id: NonEmptyText | None = None
    completed_at: AwareDatetime


class CertificateInvestigation(StrictContract):
    request_id: UUID
    extraction_api: Literal["2024-11-30"] = "2024-11-30"
    extraction_model: Literal["prebuilt-layout"] = "prebuilt-layout"
    fields: tuple[DocumentFieldProof, ...]
    specialists: tuple[SpecialistProof, ...]
    tool_activity: tuple[EvidenceToolActivity, ...] = ()

    @model_serializer(mode="wrap")
    def preserve_legacy_hashes(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        serialized: dict[str, Any] = handler(self)
        # Legacy decision hashes were computed before this optional field existed.
        # Empty activity must not alter their canonical serialized evidence.
        if not self.tool_activity:
            serialized.pop("tool_activity", None)
        return serialized


class CertificateSources(StrictContract):
    """Trusted adapters supply facts; agents do not supply executable verdicts."""

    ownership: OwnershipSource | None = None
    certificate: CertificateSource | None = None
    service: ServiceSource | None = None
    investigation: CertificateInvestigation | None = None


class CertificateCheck(StrictContract):
    name: CheckName
    verdict: CheckVerdict
    reason: HoldReason

    @model_validator(mode="after")
    def consistent_reason(self) -> Self:
        if (self.verdict == "pass") != (self.reason == "passed"):
            raise ValueError("check verdict must agree with its reason")
        return self


class CertificateArtifact(StrictContract):
    document_id: NonEmptyText
    document_version: NonEmptyText
    sha256: Sha256Hex


class CertificateDecision(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    policy_id: Literal["CERT-RELEASE-001"] = POLICY_ID
    policy_version: Literal[1] = POLICY_VERSION
    evaluated_at: AwareDatetime
    sources: CertificateSources
    checks: tuple[CertificateCheck, CertificateCheck, CertificateCheck]
    outcome: Literal["release_ready", "operations_required"]
    artifact: CertificateArtifact | None = None

    @model_validator(mode="after")
    def consistent_decision(self) -> Self:
        if tuple(item.name for item in self.checks) != (
            "ownership",
            "certificate_validity",
            "service_status",
        ):
            raise ValueError("exactly the three ordered policy checks are required")
        passed = all(item.verdict == "pass" for item in self.checks)
        if (self.outcome == "release_ready") != passed:
            raise ValueError("release requires all checks to pass")
        if (self.artifact is not None) != passed:
            raise ValueError("only a passing decision may carry a release artifact")
        return self


class CertificateAuditEvent(StrictContract):
    sequence: Annotated[int, Field(ge=1)]
    event_type: Literal[
        "certificate.requested",
        "certificate.policy_checked",
        "certificate.release_ready",
        "certificate.held",
        "operations.case_created",
        "certificate.download_prepared",
    ]
    occurred_at: AwareDatetime


class CertificateOperationsCase(StrictContract):
    case_id: UUID
    assigned_user_id: UUID
    reason_codes: Annotated[tuple[HoldReason, ...], Field(min_length=1)]
    state: Literal["open"] = "open"


class CertificateRequestRecord(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    workflow_pack: Literal["certificate_fulfilment"] = "certificate_fulfilment"
    request_id: UUID
    tenant_id: UUID
    actor_user_id: UUID
    customer_id: NonEmptyText
    equipment_id: NonEmptyText
    request_context: CustomerRequestContext | None = None
    decision: CertificateDecision
    decision_hash: Sha256Hex
    operations_case: CertificateOperationsCase | None
    events: Annotated[tuple[CertificateAuditEvent, ...], Field(min_length=3)]

    @model_validator(mode="after")
    def consistent_routing(self) -> Self:
        if (
            self.request_context is not None
            and self.request_context.equipment_id != self.equipment_id
        ):
            raise ValueError("customer context must match the certificate target")
        if (self.operations_case is not None) != (self.decision.outcome == "operations_required"):
            raise ValueError("every held request requires an Operations case")
        if tuple(event.sequence for event in self.events) != tuple(range(1, len(self.events) + 1)):
            raise ValueError("audit sequences must be contiguous")
        if any(
            right.occurred_at < left.occurred_at
            for left, right in zip(self.events, self.events[1:], strict=False)
        ):
            raise ValueError("audit times must be ordered")
        return self

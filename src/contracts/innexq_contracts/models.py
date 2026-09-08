"""InnexQ v1 domain models.

These models deliberately contain no FastAPI, Azure, persistence, or agent-runtime code.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

SCHEMA_VERSION = "1.0"
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmptyText = Annotated[str, Field(min_length=1)]
PositiveVersion = Annotated[int, Field(ge=1)]


class StrictContract(BaseModel):
    """Base behavior shared by all immutable v1 contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RunState(StrEnum):
    DETECTED = "DETECTED"
    CONTEXT_ASSEMBLING = "CONTEXT_ASSEMBLING"
    CONTEXT_ASSEMBLED = "CONTEXT_ASSEMBLED"
    POLICY_VERIFIED = "POLICY_VERIFIED"
    EVIDENCE_HOLD = "EVIDENCE_HOLD"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    ESCALATED = "ESCALATED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTED = "EXECUTED"
    CLOSED_REJECTED = "CLOSED_REJECTED"


class SourceKind(StrEnum):
    FOUNDRY_IQ = "foundry_iq"
    WORK_IQ = "work_iq"
    TOOL = "tool"


class Classification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class AuthorizationMode(StrEnum):
    DELEGATED = "delegated"
    WORKLOAD_IDENTITY = "workload_identity"


class EvidenceGapKind(StrEnum):
    MISSING = "missing"
    STALE = "stale"
    CONFLICTING = "conflicting"
    INACCESSIBLE = "inaccessible"


class PolicyVerdict(StrEnum):
    PASS = "pass"  # noqa: S105 - policy verdict, not a credential
    FAIL = "fail"
    REQUIRES_APPROVAL = "requires_approval"


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"
    ESCALATE = "escalate"


class AuthorityVerdict(StrEnum):
    AUTHORIZED = "authorized"
    UNAUTHORIZED = "unauthorized"
    ESCALATION_REQUIRED = "escalation_required"


class ActionType(StrEnum):
    SHAREPOINT_CREATE_FILE = "sharepoint.create_file"
    GRAPH_SEND_MAIL = "graph.send_mail"
    TEAMS_SEND_STATUS = "teams.send_status"


class ActorContext(StrictContract):
    actor_user_id: NonEmptyText
    tenant_id: NonEmptyText
    authorization_mode: AuthorizationMode


class Run(StrictContract):
    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^1\.0$")
    run_id: UUID
    contract_id: NonEmptyText
    state: RunState
    owner_user_id: str | None = None
    current_brief_version: int = Field(default=0, ge=0)
    current_brief_hash: Sha256Hex | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    correlation_id: UUID

    @model_validator(mode="after")
    def brief_pointer_is_consistent(self) -> Run:
        if self.current_brief_version == 0 and self.current_brief_hash is not None:
            raise ValueError("an unversioned Run cannot have a current brief hash")
        if self.current_brief_version > 0 and self.current_brief_hash is None:
            raise ValueError("a versioned Run requires a current brief hash")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self


class EvidenceItem(StrictContract):
    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^1\.0$")
    evidence_id: UUID
    source_kind: SourceKind
    source_name: NonEmptyText
    source_locator: NonEmptyText
    excerpt: NonEmptyText
    retrieved_at: AwareDatetime
    actor_context: ActorContext
    supports_claim_ids: Annotated[list[UUID], Field(min_length=1)]
    classification: Classification


class Recommendation(StrictContract):
    option_id: NonEmptyText
    term_months: int = Field(gt=0)
    service_level: NonEmptyText
    summary: NonEmptyText


class Alternative(StrictContract):
    option_id: NonEmptyText
    description: NonEmptyText
    required_scenario_role: NonEmptyText


class MaterialClaim(StrictContract):
    claim_id: UUID
    text: NonEmptyText
    evidence_ids: Annotated[list[UUID], Field(min_length=1)]


class CalculationRecord(StrictContract):
    calculation_id: UUID
    tool_name: NonEmptyText
    tool_version: NonEmptyText
    inputs: dict[str, JsonValue]
    outputs: dict[str, JsonValue]


class PolicyCheck(StrictContract):
    check_id: UUID
    rule_id: NonEmptyText
    rule_version: NonEmptyText
    verdict: PolicyVerdict
    evidence_ids: Annotated[list[UUID], Field(min_length=1)]
    required_scenario_role: str | None = None
    explanation: NonEmptyText


class EvidenceGap(StrictContract):
    gap_id: UUID
    kind: EvidenceGapKind
    description: NonEmptyText
    required_resolution: NonEmptyText


class Presentation(StrictContract):
    plain_language_summary: NonEmptyText
    detailed_summary: NonEmptyText
    customer_language_drafts: dict[str, NonEmptyText]


class DecisionBrief(StrictContract):
    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^1\.0$")
    run_id: UUID
    brief_version: PositiveVersion
    recommendation: Recommendation
    alternatives: list[Alternative]
    material_claims: Annotated[list[MaterialClaim], Field(min_length=1)]
    calculations: Annotated[list[CalculationRecord], Field(min_length=1)]
    policy_checks: Annotated[list[PolicyCheck], Field(min_length=1)]
    evidence_gaps: list[EvidenceGap]
    action_manifest_id: UUID
    presentation: Presentation


class Action(StrictContract):
    action_id: UUID
    action_type: ActionType
    parameters: dict[str, JsonValue]
    artifact_hash: Sha256Hex
    idempotency_key: Annotated[str, Field(min_length=16, max_length=200)]


class ActionManifest(StrictContract):
    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^1\.0$")
    manifest_id: UUID
    run_id: UUID
    brief_version: PositiveVersion
    actions: Annotated[list[Action], Field(min_length=1)]


class AuthorityResult(StrictContract):
    verdict: AuthorityVerdict
    actor_scenario_role: NonEmptyText
    required_scenario_role: NonEmptyText
    rule_id: NonEmptyText
    rule_version: NonEmptyText


class ApprovalDecision(StrictContract):
    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^1\.0$")
    decision_id: UUID
    run_id: UUID
    brief_version: PositiveVersion
    brief_hash: Sha256Hex
    actor_user_id: NonEmptyText
    decision: Decision
    authority_result: AuthorityResult
    submitted_at: AwareDatetime
    comment: str | None = None


class VersionedBrief(StrictContract):
    brief: DecisionBrief
    action_manifest: ActionManifest
    brief_hash: Sha256Hex

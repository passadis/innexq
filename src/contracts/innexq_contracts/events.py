"""Versioned persistence and proposal contracts for the first Workflow Pack."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from innexq_contracts.models import (
    ApprovalDecision,
    EvidenceItem,
    Run,
    RunState,
    StrictContract,
    VersionedBrief,
)


class Citation(StrictContract):
    source_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    excerpt: str = Field(min_length=1, max_length=8000)
    url: str = Field(min_length=1, max_length=2000)


class AgentProposal(StrictContract):
    summary: str = Field(min_length=1, max_length=8000)
    citations: list[Citation] = Field(min_length=1, max_length=30)


class RunEvent(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    event_id: UUID
    run_id: UUID
    correlation_id: UUID
    sequence: int = Field(ge=1)
    event_type: str
    state: RunState
    occurred_at: AwareDatetime
    actor_user_id: str
    details: dict[str, str] = Field(default_factory=dict)


class RunRecord(StrictContract):
    run: Run
    workflow_pack: Literal["contract-renewal"] = "contract-renewal"
    revision: int = Field(ge=1)
    envelope: VersionedBrief | None = None
    proposal: AgentProposal | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    facts: dict[str, str] = Field(default_factory=dict)
    approval: ApprovalDecision | None = None
    action_status: dict[str, Literal["started", "completed", "unknown"]] = Field(
        default_factory=dict
    )
    receipts: dict[str, str] = Field(default_factory=dict)
    approval_requested_at: AwareDatetime | None = None

"""Generate committed JSON Schema documents from v1 contract models."""

from __future__ import annotations

from pydantic import BaseModel

from innexq_contracts.events import AgentProposal, RunEvent, RunRecord
from innexq_contracts.models import (
    ActionManifest,
    ApprovalDecision,
    DecisionBrief,
    EvidenceItem,
    Run,
)

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "run-event.schema.json": RunEvent,
    "run-record.schema.json": RunRecord,
    "agent-proposal.schema.json": AgentProposal,
    "action-manifest.schema.json": ActionManifest,
    "approval-decision.schema.json": ApprovalDecision,
    "decision-brief.schema.json": DecisionBrief,
    "evidence-item.schema.json": EvidenceItem,
    "run.schema.json": Run,
}


def schema_documents() -> dict[str, dict[str, object]]:
    """Return stable v1 JSON Schema documents keyed by committed filename."""

    documents: dict[str, dict[str, object]] = {}
    for filename, model in SCHEMA_MODELS.items():
        schema = model.model_json_schema(mode="validation")
        schema["$id"] = f"https://schemas.innexq.invalid/v1/{filename}"
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        documents[filename] = schema
    return documents

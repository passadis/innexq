"""Fixed diagnostic labels only: never export model, tool or exception payloads."""

import re

_REASONS = {
    "Hosted Agent response did not complete": "hosted_response_incomplete",
    "Required read-only tool evidence is missing or failed": "hosted_tool_evidence_failed",
    "Missing proposal": "hosted_proposal_missing",
    "Proposal does not cite every required evidence category": "hosted_categories_mismatch",
    "Proposal citation does not match retrieved evidence": "hosted_citation_mismatch",
    "Proposal summary must be an exact cited excerpt": "hosted_summary_mismatch",
    "Agent exceeded proposal output limit": "hosted_output_limit",
    "Agent returned no response": "hosted_response_missing",
    "conflicting corpus source versions": "corpus_version_conflict",
    "duplicate source citation": "citation_duplicate",
    "citation is not grounded in the approved corpus": "citation_ungrounded",
    "citation locator/version conflict": "citation_locator_conflict",
    "evidence expired": "evidence_expired",
    "material evidence missing": "evidence_missing",
    "Phase 1 summary must be an exact cited excerpt": "summary_mismatch",
}


def reason_code(message: object) -> str:
    # Exact match only. A message containing extra payload text remains unknown.
    return _REASONS.get(message, "unclassified") if isinstance(message, str) else "unclassified"


def opaque_id(value: object) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        return value
    return "unavailable"


def response_status(value: object) -> str:
    known = ("completed", "failed", "incomplete", "cancelled", "queued", "in_progress")
    return value if isinstance(value, str) and value in known else "unknown"

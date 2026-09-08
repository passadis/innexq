"""Deterministic contract factories used by unit tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from innexq_contracts import (
    Action,
    ActionManifest,
    ActionType,
    Alternative,
    ApprovalDecision,
    AuthorityResult,
    AuthorityVerdict,
    CalculationRecord,
    Decision,
    DecisionBrief,
    MaterialClaim,
    PolicyCheck,
    PolicyVerdict,
    Presentation,
    Recommendation,
    VersionedBrief,
)

RUN_ID = UUID("10000000-0000-4000-8000-000000000001")
MANIFEST_ID = UUID("20000000-0000-4000-8000-000000000001")
CLAIM_ID = UUID("30000000-0000-4000-8000-000000000001")
EVIDENCE_ID = UUID("40000000-0000-4000-8000-000000000001")


def brief(summary: str = "Renew for three years at the compliant option") -> DecisionBrief:
    return DecisionBrief(
        run_id=RUN_ID,
        brief_version=1,
        recommendation=Recommendation(
            option_id="option-8-percent",
            term_months=36,
            service_level="Gold Plus",
            summary=summary,
        ),
        alternatives=[
            Alternative(
                option_id="option-12-percent",
                description="Requested discount requiring exception approval",
                required_scenario_role="operations_manager",
            )
        ],
        material_claims=[
            MaterialClaim(
                claim_id=CLAIM_ID,
                text="The contract covers 18 compressors.",
                evidence_ids=[EVIDENCE_ID],
            )
        ],
        calculations=[
            CalculationRecord(
                calculation_id=UUID("50000000-0000-4000-8000-000000000001"),
                tool_name="pricing-calculator",
                tool_version="1.0.0",
                inputs={"annual_value": "180000.00", "discount_percent": "8.00"},
                outputs={"discounted_annual_value": "165600.00", "currency": "EUR"},
            )
        ],
        policy_checks=[
            PolicyCheck(
                check_id=UUID("60000000-0000-4000-8000-000000000001"),
                rule_id="discount-authority",
                rule_version="2026-08-15",
                verdict=PolicyVerdict.PASS,
                evidence_ids=[EVIDENCE_ID],
                required_scenario_role="account_manager",
                explanation="The 8% option is within Elena's authority.",
            )
        ],
        evidence_gaps=[],
        action_manifest_id=MANIFEST_ID,
        presentation=Presentation(
            plain_language_summary="A compliant renewal is ready for review.",
            detailed_summary="Evidence and deterministic checks support the proposed option.",
            customer_language_drafts={
                "en-GB": "Draft English renewal message",
                "sv-SE": "Utkast till svenskt förnyelsemeddelande",
            },
        ),
    )


def manifest(recipient: str = "customer@example.invalid") -> ActionManifest:
    return ActionManifest(
        manifest_id=MANIFEST_ID,
        run_id=RUN_ID,
        brief_version=1,
        actions=[
            Action(
                action_id=UUID("70000000-0000-4000-8000-000000000001"),
                action_type=ActionType.GRAPH_SEND_MAIL,
                parameters={"recipient": recipient, "draft_language": "sv-SE"},
                artifact_hash=hashlib.sha256(b"synthetic-approved-email").hexdigest(),
                idempotency_key="run-1-send-mail-v1",
            )
        ],
    )


def approval(current: VersionedBrief) -> ApprovalDecision:
    return ApprovalDecision(
        decision_id=UUID("80000000-0000-4000-8000-000000000001"),
        run_id=RUN_ID,
        brief_version=current.brief.brief_version,
        brief_hash=current.brief_hash,
        actor_user_id="elena.synthetic",
        decision=Decision.APPROVE,
        authority_result=AuthorityResult(
            verdict=AuthorityVerdict.AUTHORIZED,
            actor_scenario_role="account_manager",
            required_scenario_role="account_manager",
            rule_id="discount-authority",
            rule_version="2026-08-15",
        ),
        submitted_at=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
    )

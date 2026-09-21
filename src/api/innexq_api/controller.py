"""Controller-owned transitions, authorization and recoverable action boundaries."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from innexq_contracts.events import AgentProposal, RunEvent, RunRecord
from innexq_contracts.hashing import (
    approval_matches_current_version,
    canonical_json_bytes,
    compute_brief_hash,
    version_brief,
)
from innexq_contracts.models import (
    Action,
    ActionManifest,
    ActionType,
    ActorContext,
    ApprovalDecision,
    AuthorityVerdict,
    AuthorizationMode,
    CalculationRecord,
    Classification,
    Decision,
    DecisionBrief,
    EvidenceItem,
    MaterialClaim,
    PolicyCheck,
    PolicyVerdict,
    Presentation,
    Recommendation,
    Run,
    RunState,
    SourceKind,
    VersionedBrief,
)
from innexq_contracts.transitions import assert_transition
from innexq_gateway import calculate_pricing, check_authority

from innexq_api.assembly_diagnostics import reason_code
from innexq_api.config import Settings
from innexq_api.presentation import renewal_email
from innexq_api.store import Conflict, Store

CONTRACT_ID = "CON-FAB-2025-001"


class Denied(ValueError):
    """A required security or evidence condition is absent."""


class Agent(Protocol):
    async def propose(self, run: Run) -> AgentProposal: ...


class Executor(Protocol):
    async def execute(self, action: Action) -> str: ...


class Approvals(Protocol):
    async def request(self, record: RunRecord) -> str: ...


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Controller:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        agent: Agent,
        executor: Executor,
        approvals: Approvals,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings, self.store, self.agent = settings, store, agent
        self.executor, self.approvals, self.now = executor, approvals, now

    def authorize(self, tenant: str, actor: str) -> None:
        if tenant != self.settings.tenant_id or actor != self.settings.approver_user_id:
            raise Denied("actor has no Phase 1 authority")

    def facts(self) -> dict[str, str]:
        contract = json.loads(Path(self.settings.contract_path).read_text(encoding="utf-8"))
        policy = json.loads(Path(self.settings.policy_path).read_text(encoding="utf-8"))
        corpus = json.loads(Path(self.settings.corpus_path).read_text(encoding="utf-8"))
        if contract["synthetic"] is not True or policy["synthetic"] is not True:
            raise Denied("Phase 1 accepts synthetic fixtures only")
        if contract["contract_id"] != CONTRACT_ID or policy["workflow_pack"] != "contract-renewal":
            raise Denied("unknown contract or Workflow Pack")
        today = self.now().date()
        if (
            not date.fromisoformat(policy["valid_from"])
            <= today
            <= date.fromisoformat(policy["valid_until"])
        ):
            raise Denied("policy expired or not yet effective")
        price = calculate_pricing(
            contract["annual_value"]["amount"],
            policy["discount_percent"],
            currency=contract["annual_value"]["currency"],
        )
        if (policy["rule_id"], policy["rule_version"], policy["required_scenario_role"]) != (
            price.rule_id,
            price.rule_version,
            price.required_scenario_role,
        ) or policy["required_scenario_role"] != "account_manager":
            raise Denied("policy conflicts with deterministic tool")
        if policy["term_months"] != 12 or contract["service_tier"] != "Gold":
            raise Denied("term or service-level change outside Phase 1")
        return {
            **price.as_dict(),
            "contract_id": CONTRACT_ID,
            "customer_name": contract["customer_name"],
            "service_level": contract["service_tier"],
            "term_months": str(policy["term_months"]),
            "expires_on": contract["expires_on"],
            "renewal_window_days": str(policy["renewal_window_days"]),
            "fixture_hash": hashlib.sha256(canonical_json_bytes(contract)).hexdigest(),
            "policy_hash": hashlib.sha256(canonical_json_bytes(policy)).hexdigest(),
            "corpus_hash": hashlib.sha256(canonical_json_bytes(corpus)).hexdigest(),
        }

    def current_facts(self, record: RunRecord) -> dict[str, str]:
        facts = self.facts()
        if facts != record.facts:
            raise Denied("transaction facts or policy changed; new Run required")
        return facts

    def pricing(self, run_id: UUID, correlation_id: UUID, contract_id: str) -> dict[str, str]:
        record = self.store.get(run_id)
        if (
            record.run.correlation_id != correlation_id
            or record.run.contract_id != contract_id
            or record.run.state != RunState.CONTEXT_ASSEMBLING
        ):
            raise Denied("pricing request is not bound to an assembling Run")
        facts = self.current_facts(record)
        self.record(
            record,
            "tool.pricing_completed",
            self.settings.agent_principal_id,
            details={"tool_version": facts["tool_version"], "rule_id": facts["rule_id"]},
        )
        return calculate_pricing(
            facts["annual_value"], facts["discount_percent"], currency=facts["currency"]
        ).as_dict()

    def record(
        self,
        old: RunRecord,
        event_type: str,
        actor: str,
        *,
        target: RunState | None = None,
        details: dict[str, str] | None = None,
        **updates: Any,
    ) -> RunRecord:
        state = target or old.run.state
        if target is not None:
            assert_transition(old.run.state, target)
        run = old.run.model_copy(update={"state": state, "updated_at": self.now()})
        record = old.model_copy(update={"run": run, "revision": old.revision + 1, **updates})
        self.store.commit(
            record,
            RunEvent(
                event_id=uuid4(),
                run_id=run.run_id,
                correlation_id=run.correlation_id,
                sequence=record.revision,
                event_type=event_type,
                state=state,
                occurred_at=self.now(),
                actor_user_id=actor,
                details=details or {},
            ),
            old.revision,
        )
        logging.getLogger("innexq.audit").info(
            "run_event",
            extra={
                "run_id": str(run.run_id),
                "correlation_id": str(run.correlation_id),
                "event_type": event_type,
                "state": state.value,
                "sequence": record.revision,
            },
        )
        return record

    def detect(self, tenant: str, actor: str, key: str) -> RunRecord:
        self.authorize(tenant, actor)
        if not 16 <= len(key) <= 200:
            raise Denied("idempotency key must be 16-200 characters")
        run_id = uuid5(NAMESPACE_URL, f"innexq:{tenant}:{actor}:{key}")
        try:
            return self.store.get(run_id)
        except KeyError:
            pass
        facts = self.facts()
        days = (date.fromisoformat(facts["expires_on"]) - self.now().date()).days
        if not 0 <= days <= int(facts["renewal_window_days"]):
            raise Denied("contract is not eligible for renewal")
        run = Run(
            run_id=run_id,
            contract_id=CONTRACT_ID,
            state=RunState.DETECTED,
            owner_user_id=actor,
            created_at=self.now(),
            updated_at=self.now(),
            correlation_id=uuid4(),
        )
        record = RunRecord(run=run, revision=1, facts=facts)
        event = RunEvent(
            event_id=uuid4(),
            run_id=run_id,
            correlation_id=run.correlation_id,
            sequence=1,
            event_type="run.detected",
            state=run.state,
            occurred_at=self.now(),
            actor_user_id=actor,
            details={"workflow_pack": "contract-renewal"},
        )
        try:
            self.store.commit(record, event, 0)
        except Conflict:
            return self.store.get(run_id)
        return record

    def validate_evidence(self, proposal: AgentProposal) -> None:
        documents = json.loads(Path(self.settings.corpus_path).read_text(encoding="utf-8"))
        sources = {d["id"]: d for d in documents["documents"]}
        if len(sources) != len(documents["documents"]):
            raise Denied("conflicting corpus source versions")
        seen: set[str] = set()
        for citation in proposal.citations:
            if citation.source_id in seen:
                raise Denied("duplicate source citation")
            source = sources.get(citation.source_id)
            if source is None or citation.excerpt not in source["content"]:
                raise Denied("citation is not grounded in the approved corpus")
            if citation.url != source["url"] or citation.title != source["title"]:
                raise Denied("citation locator/version conflict")
            if self.now() >= datetime.fromisoformat(source["valid_until"].replace("Z", "+00:00")):
                raise Denied("evidence expired")
            seen.add(citation.source_id)
        if seen != {"contract", "pricing", "authority", "sla", "playbook", "template"}:
            raise Denied("material evidence missing")
        if proposal.summary not in {c.excerpt for c in proposal.citations}:
            raise Denied("Phase 1 summary must be an exact cited excerpt")

    def command_replayed(
        self, record: RunRecord, event_type: str, revision: int, key: str | None
    ) -> bool:
        """A claimed command is never reissued, including after an ambiguous timeout."""
        if key is None:
            return False  # Internal calls still require optimistic concurrency.
        if not 16 <= len(key) <= 200:
            raise Denied("idempotency key must be 16-200 characters")
        for event in self.store.events(record.run.run_id):
            if event.event_type == event_type and event.details.get("command_key") == digest(key):
                if event.details.get("request_revision") != str(revision):
                    raise Conflict("idempotency key reused for a different request")
                return True
        return False

    async def assemble(
        self, run_id: UUID, tenant: str, actor: str, revision: int, key: str | None = None
    ) -> RunRecord:
        self.authorize(tenant, actor)
        record = self.store.get(run_id)
        if self.command_replayed(record, "agent.started", revision, key):
            return record
        if record.revision != revision:
            raise Conflict("revision changed")
        record = self.record(
            record,
            "agent.started",
            actor,
            target=RunState.CONTEXT_ASSEMBLING,
            details={"command_key": digest(key) if key else "", "request_revision": str(revision)},
        )
        stage = "initial_facts"
        try:
            self.current_facts(record)
            stage = "agent_proposal"
            proposal = await self.agent.propose(record.run)
            stage = "reload_run"
            # The read-only pricing callback commits its own audit event while the agent runs.
            record = self.store.get(run_id)
            if record.run.state != RunState.CONTEXT_ASSEMBLING:
                raise Conflict("assembly state changed")
            stage = "validate_evidence"
            self.validate_evidence(proposal)
            stage = "recheck_facts"
            self.current_facts(record)
            evidence = [
                EvidenceItem(
                    evidence_id=uuid5(run_id, c.source_id),
                    source_kind=SourceKind.FOUNDRY_IQ,
                    source_name=c.title,
                    source_locator=c.url,
                    excerpt=c.excerpt,
                    retrieved_at=self.now(),
                    actor_context=ActorContext(
                        actor_user_id=self.settings.agent_principal_id or "unconfigured-agent",
                        tenant_id=self.settings.tenant_id,
                        authorization_mode=AuthorizationMode.WORKLOAD_IDENTITY,
                    ),
                    supports_claim_ids=[uuid5(run_id, f"claim:{c.source_id}")],
                    classification=Classification.INTERNAL,
                )
                for c in proposal.citations
            ]
            stage = "persist_evidence"
            record = self.record(
                record,
                "evidence.validated",
                actor,
                target=RunState.CONTEXT_ASSEMBLED,
                proposal=proposal,
                evidence=evidence,
            )
            stage = "build_brief"
            envelope = self.build_brief(record, proposal)
            stage = "persist_policy"
            record = self.record(
                record, "policy.verified", actor, target=RunState.POLICY_VERIFIED, envelope=envelope
            )
            # The brief pointer and its event are committed atomically together.
            stage = "persist_brief"
            record = self.record(
                record,
                "brief.versioned",
                actor,
                run=record.run.model_copy(
                    update={
                        "current_brief_version": envelope.brief.brief_version,
                        "current_brief_hash": envelope.brief_hash,
                        "updated_at": self.now(),
                    }
                ),
                details={"brief_hash": envelope.brief_hash},
            )
            return record
        except Conflict:
            raise
        except Exception as exc:
            current = self.store.get(run_id)
            self.record(
                current,
                "evidence.hold",
                actor,
                target=RunState.EVIDENCE_HOLD,
                details={
                    "error_type": type(exc).__name__,
                    "failed_stage": stage,
                    "reason_code": reason_code(str(exc))
                    if isinstance(exc, Denied)
                    else "unclassified",
                },
            )
            raise Denied("assembly failed safely; inspect Run Events") from exc

    def build_brief(self, record: RunRecord, proposal: AgentProposal) -> VersionedBrief:
        facts = self.current_facts(record)
        price = calculate_pricing(
            facts["annual_value"], facts["discount_percent"], currency=facts["currency"]
        )
        rid = record.run.run_id
        version = 1 if record.envelope is None else record.envelope.brief.brief_version + 1
        filename = f"innexq-{rid}-v{version}.txt"
        content = (
            (
                f"SYNTHETIC INNEXQ DEMO — Run {rid}\n{facts['customer_name']}\n"
                f"Contract {facts['contract_id']}; {facts['service_level']} service; "
                f"{facts['term_months']}-month renewal. Brief version {version}.\n"
                f"Annual list value EUR {price.annual_value}; discount {price.discount_percent}%; "
                f"discount EUR {price.discount_amount}; "
                f"net annual EUR {price.discounted_annual_value}.\n"
                "This is a test document, not a commercial offer.\n"
            )
            + "Evidence (synthetic corpus locators):\n"
            + "\n".join(f"{c.title}: {c.url}\n{c.excerpt}" for c in proposal.citations)
        )
        subject = f"[InnexQ Demo] {facts['customer_name']} | Renewal summary v{version}"
        email_content = renewal_email(
            facts, price, rid, version, filename, self.settings.graph_output_folder_url
        )
        actions = [
            Action(
                action_id=uuid4(),
                action_type=ActionType.SHAREPOINT_CREATE_FILE,
                parameters={
                    "drive_id": self.settings.graph_drive_id,
                    "folder_id": self.settings.graph_folder_id,
                    "filename": filename,
                    "content": content,
                },
                artifact_hash=digest(content),
                idempotency_key=f"{rid}:file:v{version}",
            ),
            Action(
                action_id=uuid4(),
                action_type=ActionType.GRAPH_SEND_MAIL,
                parameters={
                    "sender": self.settings.sender_mailbox,
                    "recipient": self.settings.test_recipient,
                    "subject": subject,
                    "content": email_content,
                    "content_type": "HTML",
                },
                artifact_hash=digest(email_content),
                idempotency_key=f"{rid}:mail:v{version}",
            ),
        ]
        manifest = ActionManifest(
            manifest_id=uuid4(), run_id=rid, brief_version=version, actions=actions
        )
        evidence_ids = [uuid5(rid, c.source_id) for c in proposal.citations]
        brief = DecisionBrief(
            run_id=rid,
            brief_version=version,
            recommendation=Recommendation(
                option_id="renewal-8",
                term_months=12,
                service_level="Gold",
                summary=proposal.summary,
            ),
            alternatives=[],
            material_claims=[
                MaterialClaim(
                    claim_id=uuid5(rid, f"claim:{c.source_id}"), text=c.excerpt, evidence_ids=[eid]
                )
                for c, eid in zip(proposal.citations, evidence_ids, strict=True)
            ],
            calculations=[
                CalculationRecord(
                    calculation_id=uuid4(),
                    tool_name="pricing-authority",
                    tool_version=price.tool_version,
                    inputs={
                        "annual_value": facts["annual_value"],
                        "discount_percent": facts["discount_percent"],
                        "fixture_hash": facts["fixture_hash"],
                        "policy_hash": facts["policy_hash"],
                        "corpus_hash": facts["corpus_hash"],
                        "evidence_hash": hashlib.sha256(
                            canonical_json_bytes(
                                [e.model_dump(mode="json") for e in record.evidence]
                            )
                        ).hexdigest(),
                    },
                    outputs=dict(price.as_dict()),
                )
            ],
            policy_checks=[
                PolicyCheck(
                    check_id=uuid4(),
                    rule_id=price.rule_id,
                    rule_version=price.rule_version,
                    verdict=PolicyVerdict.PASS,
                    evidence_ids=evidence_ids,
                    required_scenario_role="account_manager",
                    explanation=(
                        "8% within account-manager authority; verified human still required"
                    ),
                )
            ],
            evidence_gaps=[],
            action_manifest_id=manifest.manifest_id,
            presentation=Presentation(
                plain_language_summary=proposal.summary,
                detailed_summary=content,
                customer_language_drafts={"en-GB": email_content},
            ),
        )
        return version_brief(brief, manifest, previous=record.envelope)

    async def request_approval(
        self,
        run_id: UUID,
        tenant: str,
        actor: str,
        revision: int,
        key: str | None = None,
    ) -> RunRecord:
        self.authorize(tenant, actor)
        record = self.store.get(run_id)
        if self.command_replayed(record, "approval.requested", revision, key):
            return record
        if record.revision != revision or record.envelope is None:
            raise Conflict("revision changed or brief absent")
        self.verify_package(record)
        if not self.settings.graph_drive_id or not self.settings.graph_folder_id:
            raise Denied("SharePoint destination has not been verified/configured")
        record = self.record(
            record,
            "approval.requested",
            actor,
            target=RunState.AWAITING_APPROVAL,
            approval_requested_at=self.now(),
            details={"command_key": digest(key) if key else "", "request_revision": str(revision)},
        )
        try:
            receipt = await self.approvals.request(record)
        except Exception as exc:
            self.record(
                record,
                "approval.delivery_failed",
                actor,
                target=RunState.EVIDENCE_HOLD,
                details={"error_type": type(exc).__name__},
            )
            raise Denied("approval card delivery failed; stale card cannot authorize") from exc
        return self.record(record, "approval.card_sent", actor, details={"message_id": receipt})

    def decide(
        self,
        run_id: UUID,
        tenant: str,
        actor: str,
        brief_hash: str,
        decision: Decision,
        brief_version: int | None = None,
    ) -> RunRecord:
        record = self.store.get(run_id)
        try:
            self.authorize(tenant, actor)
            self.verify_package(record)
            current = record.envelope
            if (
                current is None
                or brief_hash != compute_brief_hash(current.brief, current.action_manifest)
                or brief_hash != record.run.current_brief_hash
            ):
                raise Denied("approval hash mismatch")
            if brief_version is not None and brief_version != current.brief.brief_version:
                raise Denied("approval version mismatch")
            if record.approval is not None:
                return self.record(record, "approval.duplicate_ignored", actor)
            if record.run.state != RunState.AWAITING_APPROVAL:
                raise Denied("Run is not awaiting approval")
            if record.approval_requested_at is None or (
                self.now() - record.approval_requested_at > timedelta(hours=1)
            ):
                raise Denied("approval expired")
            if decision not in (Decision.APPROVE, Decision.REJECT):
                raise Denied("unsupported Phase 1 decision")
            authority = check_authority(record.facts["discount_percent"], "account_manager")
            if authority.verdict != AuthorityVerdict.AUTHORIZED:
                raise Denied("authority rejected")
            approval = ApprovalDecision(
                decision_id=uuid4(),
                run_id=run_id,
                brief_version=current.brief.brief_version,
                brief_hash=brief_hash,
                actor_user_id=actor,
                decision=decision,
                authority_result=authority,
                submitted_at=self.now(),
            )
            target = RunState.APPROVED if decision == Decision.APPROVE else RunState.CLOSED_REJECTED
            return self.record(record, "approval.recorded", actor, target=target, approval=approval)
        except Denied:
            self.record(record, "approval.denied", actor)
            raise

    def verify_package(self, record: RunRecord) -> None:
        self.current_facts(record)
        if record.proposal is None or record.envelope is None:
            raise Denied("complete proposal and versioned brief required")
        self.validate_evidence(record.proposal)
        current = record.envelope
        if (
            compute_brief_hash(current.brief, current.action_manifest) != current.brief_hash
            or current.brief_hash != record.run.current_brief_hash
            or current.brief.brief_version != record.run.current_brief_version
        ):
            raise Denied("current artifact pointer/hash mismatch")
        evidence_hash = hashlib.sha256(
            canonical_json_bytes([e.model_dump(mode="json") for e in record.evidence])
        ).hexdigest()
        if current.brief.calculations[0].inputs.get("evidence_hash") != evidence_hash:
            raise Denied("approved evidence changed")

    def execution_event(
        self,
        run_id: UUID,
        event_type: str,
        actor: str,
        *,
        key: str | None = None,
        status: Literal["started", "completed", "unknown"] | None = None,
        receipt: str | None = None,
        target: RunState | None = None,
        details: dict[str, str] | None = None,
    ) -> RunRecord:
        """Retry only audit commits, never an external operation.

        A duplicate callback may append a denial while an outbound call is in flight.
        Reload its revision so that denial cannot discard the outbound receipt.
        """
        for _ in range(5):
            latest = self.store.get(run_id)
            if latest.run.state != RunState.EXECUTING:
                raise Denied("execution state changed before receipt commit")
            statuses, receipts = dict(latest.action_status), dict(latest.receipts)
            if key is not None and status is not None:
                statuses[key] = status
                if receipt is not None:
                    receipts[key] = receipt
            try:
                return self.record(
                    latest,
                    event_type,
                    actor,
                    target=target,
                    details=details,
                    action_status=statuses,
                    receipts=receipts,
                )
            except Conflict:
                continue
        raise Conflict("receipt commit contention; external operation must not be repeated")

    async def execute(self, run_id: UUID) -> RunRecord:
        """Internal method only: deliberately no HTTP execution route is mounted."""
        record = self.store.get(run_id)
        if record.run.state == RunState.EXECUTED:
            return record
        approval, current = record.approval, record.envelope
        try:
            if (
                approval is None
                or current is None
                or not approval_matches_current_version(approval, current)
            ):
                raise Denied("stored matching approval required")
            self.authorize(self.settings.tenant_id, approval.actor_user_id)
            self.verify_package(record)
            if check_authority(record.facts["discount_percent"], "account_manager").verdict != (
                AuthorityVerdict.AUTHORIZED
            ):
                raise Denied("authority no longer valid")
            if record.run.state not in (RunState.APPROVED, RunState.EXECUTION_FAILED):
                raise Denied("execution already in progress or state invalid")
            if any(v in ("started", "unknown") for v in record.action_status.values()):
                raise Denied("external outcome unknown; automatic resend is prohibited")
        except Denied:
            self.record(record, "execution.denied", "controller")
            raise
        record = self.record(
            record, "execution.started", approval.actor_user_id, target=RunState.EXECUTING
        )
        for action in current.action_manifest.actions:
            key = action.idempotency_key
            if record.action_status.get(key) == "completed":
                continue
            record = self.execution_event(
                run_id,
                "action.started",
                approval.actor_user_id,
                key=key,
                status="started",
                details={"action": action.action_type.value},
            )
            try:
                receipt = await self.executor.execute(action)
            except Exception as exc:
                self.execution_event(
                    run_id,
                    "execution.failed",
                    approval.actor_user_id,
                    target=RunState.EXECUTION_FAILED,
                    key=key,
                    status="unknown",
                    details={"error_type": type(exc).__name__},
                )
                raise Denied("external outcome may be unknown; no automatic resend") from exc
            record = self.execution_event(
                run_id,
                "action.completed",
                approval.actor_user_id,
                key=key,
                status="completed",
                receipt=receipt,
            )
        return self.execution_event(
            run_id, "execution.completed", approval.actor_user_id, target=RunState.EXECUTED
        )

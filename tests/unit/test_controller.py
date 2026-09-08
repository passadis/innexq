"""Offline controller acceptance and adversarial tests; never stand in for live proof."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from innexq_api.config import Settings
from innexq_api.controller import CONTRACT_ID, Controller, Denied
from innexq_api.store import Conflict, MemoryStore
from innexq_contracts.events import AgentProposal, Citation, RunRecord
from innexq_contracts.models import Action, Decision, Run, RunState

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


class FakeAgent:
    def __init__(self) -> None:
        sources = json.loads(Path("corpus/blob/phase1.json").read_text())["documents"]
        self.proposal = AgentProposal(
            summary=sources[0]["content"],
            citations=[
                Citation(source_id=d["id"], title=d["title"], excerpt=d["content"], url=d["url"])
                for d in sources
            ],
        )
        self.controller: Controller | None = None
        self.fail = False

    async def propose(self, run: Run) -> AgentProposal:
        if self.fail:
            raise RuntimeError("read denied")
        if self.controller:
            self.controller.pricing(run.run_id, run.correlation_id, run.contract_id)
        return self.proposal


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[Action] = []
        self.fail_at = 0

    async def execute(self, action: Action) -> str:
        self.calls.append(action)
        if len(self.calls) == self.fail_at:
            raise TimeoutError("outcome unknown")
        return str(action.action_id)


class FakeApprovals:
    def __init__(self) -> None:
        self.calls: list[RunRecord] = []
        self.fail = False

    async def request(self, record: RunRecord) -> str:
        self.calls.append(record)
        if self.fail:
            raise TimeoutError("card unavailable")
        return "message-id"


@pytest.fixture
def system() -> tuple[Controller, MemoryStore, FakeAgent, FakeExecutor, FakeApprovals]:
    settings = Settings(
        _env_file=None,
        graph_drive_id="drive",
        graph_folder_id="folder",
        agent_principal_id="agent",
        api_audience="api",
        foundry_project_endpoint="https://example.services.ai.azure.com",
    )
    store, agent, executor, approvals = MemoryStore(), FakeAgent(), FakeExecutor(), FakeApprovals()
    controller = Controller(settings, store, agent, executor, approvals, now=lambda: NOW)
    agent.controller = controller
    return controller, store, agent, executor, approvals


def detected(c: Controller, key: str = "synthetic-attempt-0001") -> RunRecord:
    return c.detect(c.settings.tenant_id, c.settings.approver_user_id, key)


def assembled(c: Controller, key: str = "synthetic-attempt-0001") -> RunRecord:
    r = detected(c, key)
    return asyncio.run(
        c.assemble(r.run.run_id, c.settings.tenant_id, c.settings.approver_user_id, r.revision)
    )


def awaiting(c: Controller, key: str = "synthetic-attempt-0001") -> RunRecord:
    r = assembled(c, key)
    return asyncio.run(
        c.request_approval(
            r.run.run_id, c.settings.tenant_id, c.settings.approver_user_id, r.revision
        )
    )


def approve(c: Controller, r: RunRecord, **changes: Any) -> RunRecord:
    args = dict(
        run_id=r.run.run_id,
        tenant=c.settings.tenant_id,
        actor=c.settings.approver_user_id,
        brief_hash=r.run.current_brief_hash,
        decision=Decision.APPROVE,
        brief_version=r.run.current_brief_version,
    )
    return c.decide(**(args | changes))


def test_three_fresh_offline_runs_preserve_audit_and_no_duplicate_actions(system: Any) -> None:
    c, store, _, executor, approvals = system
    for index in range(3):
        r = awaiting(c, f"synthetic-attempt-{index:04}")
        assert len(executor.calls) == index * 2
        approved = approve(c, r)
        result = asyncio.run(c.execute(r.run.run_id))
        assert result.run.state == RunState.EXECUTED
        assert len(result.receipts) == 2
        assert result.facts["discounted_annual_value"] == "165600.00"
        assert len(result.evidence) == 6
        approve(c, approved)
        asyncio.run(c.execute(r.run.run_id))
        events = store.events(r.run.run_id)
        assert [e.sequence for e in events] == list(range(1, len(events) + 1))
        assert len({e.correlation_id for e in events}) == 1
        assert len(executor.calls) == (index + 1) * 2
        assert any(e.event_type == "tool.pricing_completed" for e in events)
    assert len(approvals.calls) == 3
    assert len(store.list_runs(c.settings.approver_user_id)) == 3
    assert store.list_runs("stranger") == []


def test_detection_idempotency_authority_eligibility_and_pricing_binding(system: Any) -> None:
    c, _, _, _, _ = system
    r = detected(c)
    assert detected(c) == r
    with pytest.raises(Denied, match="authority"):
        c.detect("other-tenant", c.settings.approver_user_id, "synthetic-attempt-0002")
    with pytest.raises(Denied, match="idempotency"):
        c.detect(c.settings.tenant_id, c.settings.approver_user_id, "short")
    with pytest.raises(Denied, match="bound"):
        c.pricing(r.run.run_id, r.run.correlation_id, CONTRACT_ID)
    c.now = lambda: NOW + timedelta(days=70)
    with pytest.raises(Denied, match="eligible"):
        detected(c, "synthetic-attempt-0002")


@pytest.mark.parametrize("defect", ["missing", "duplicate", "invented", "url", "summary"])
def test_evidence_defects_hold_without_card_or_writes(system: Any, defect: str) -> None:
    c, store, agent, executor, approvals = system
    p = agent.proposal.model_dump()
    if defect == "missing":
        p["citations"].pop()
    elif defect == "duplicate":
        p["citations"].append(p["citations"][0])
    elif defect == "summary":
        p["summary"] = "The customer has already authorized this transaction."
    else:
        p["citations"][0]["excerpt" if defect == "invented" else "url"] = "fabricated"
    agent.proposal = AgentProposal.model_validate(p)
    r = detected(c)
    with pytest.raises(Denied, match="assembly failed"):
        assembled(c)
    assert store.get(r.run.run_id).run.state == RunState.EVIDENCE_HOLD
    assert not executor.calls and not approvals.calls


@pytest.mark.parametrize(
    "changes",
    [
        {"actor": "impostor"},
        {"tenant": "foreign"},
        {"brief_hash": "0" * 64},
        {"brief_version": 99},
        {"decision": Decision.EDIT},
    ],
)
def test_invalid_approvals_denied_and_audited(system: Any, changes: dict[str, Any]) -> None:
    c, store, _, executor, _ = system
    r = awaiting(c)
    with pytest.raises(Denied):
        approve(c, r, **changes)
    assert store.get(r.run.run_id).approval is None
    assert store.events(r.run.run_id)[-1].event_type == "approval.denied"
    assert not executor.calls


def test_rejection_and_unapproved_execution_never_write(system: Any) -> None:
    c, store, _, executor, _ = system
    r = awaiting(c)
    rejected = approve(c, r, decision=Decision.REJECT)
    assert rejected.run.state == RunState.CLOSED_REJECTED
    with pytest.raises(Denied, match="approval"):
        asyncio.run(c.execute(r.run.run_id))
    assert store.events(r.run.run_id)[-1].event_type == "execution.denied"
    assert not executor.calls


def test_expired_approval_and_stale_revision(system: Any) -> None:
    c, _, _, _, _ = system
    r = awaiting(c)
    c.now = lambda: NOW + timedelta(hours=2)
    with pytest.raises(Denied, match="expired"):
        approve(c, r)
    with pytest.raises(Conflict):
        asyncio.run(c.assemble(r.run.run_id, c.settings.tenant_id, c.settings.approver_user_id, 1))


@pytest.mark.parametrize("tamper", ["hash", "evidence", "facts", "version"])
def test_post_approval_tampering_denies_execution(system: Any, tamper: str) -> None:
    c, store, _, executor, _ = system
    r = approve(c, awaiting(c))
    if tamper == "hash":
        r = r.model_copy(update={"run": r.run.model_copy(update={"current_brief_hash": "0" * 64})})
    elif tamper == "evidence":
        r = r.model_copy(update={"evidence": []})
    elif tamper == "facts":
        r = r.model_copy(update={"facts": r.facts | {"discount_percent": "12.00"}})
    else:
        r = r.model_copy(update={"approval": r.approval.model_copy(update={"brief_version": 99})})
    store.records[r.run.run_id] = r
    with pytest.raises(Denied):
        asyncio.run(c.execute(r.run.run_id))
    assert not executor.calls


def test_ambiguous_mail_failure_preserves_file_receipt_and_denies_resend(system: Any) -> None:
    c, store, _, executor, _ = system
    r = approve(c, awaiting(c))
    executor.fail_at = 2
    with pytest.raises(Denied, match="unknown"):
        asyncio.run(c.execute(r.run.run_id))
    failed = store.get(r.run.run_id)
    assert failed.run.state == RunState.EXECUTION_FAILED
    assert len(failed.receipts) == 1
    with pytest.raises(Denied, match="unknown"):
        asyncio.run(c.execute(r.run.run_id))
    assert len(executor.calls) == 2


def test_card_failure_holds_and_old_card_cannot_approve(system: Any) -> None:
    c, store, _, _, approvals = system
    approvals.fail = True
    r = assembled(c)
    with pytest.raises(Denied, match="delivery"):
        asyncio.run(
            c.request_approval(
                r.run.run_id, c.settings.tenant_id, c.settings.approver_user_id, r.revision
            )
        )
    assert store.get(r.run.run_id).run.state == RunState.EVIDENCE_HOLD
    with pytest.raises(Denied, match="awaiting"):
        approve(c, r)


def test_store_conflicts_and_deep_copy(system: Any) -> None:
    c, store, _, _, _ = system
    r = detected(c)
    with pytest.raises(Conflict):
        store.commit(r, store.events(r.run.run_id)[0], 0)
    r.facts["annual_value"] = "1"
    assert store.get(r.run.run_id).facts["annual_value"] == "180000.00"
    assert store.events(uuid4()) == []
    store.save_teams_reference({"id": "ref"})
    assert store.get_teams_reference() == {"id": "ref"}
    store.ping()


def test_reassembly_versions_the_package_and_invalidates_old_card(system: Any) -> None:
    c, store, _, executor, approvals = system
    first = assembled(c)
    approvals.fail = True
    with pytest.raises(Denied, match="delivery"):
        asyncio.run(
            c.request_approval(
                first.run.run_id, c.settings.tenant_id, c.settings.approver_user_id, first.revision
            )
        )
    held = store.get(first.run.run_id)
    second = asyncio.run(
        c.assemble(
            held.run.run_id, c.settings.tenant_id, c.settings.approver_user_id, held.revision
        )
    )
    assert second.run.current_brief_version == 2
    assert second.envelope.action_manifest.brief_version == 2
    assert second.run.current_brief_hash != first.run.current_brief_hash
    assert store.briefs[(first.run.run_id, 1)] == first.envelope
    assert store.briefs[(second.run.run_id, 2)] == second.envelope
    assert all(a.idempotency_key.endswith(":v2") for a in second.envelope.action_manifest.actions)
    approvals.fail = False
    second = asyncio.run(
        c.request_approval(
            second.run.run_id, c.settings.tenant_id, c.settings.approver_user_id, second.revision
        )
    )
    with pytest.raises(Denied):
        approve(c, first)
    assert not executor.calls
    approve(c, second)
    final = asyncio.run(c.execute(second.run.run_id))
    assert final.run.state == RunState.EXECUTED
    assert len(executor.calls) == 2


def test_corpus_change_after_approval_denies_execution(system: Any, tmp_path: Path) -> None:
    c, _, _, executor, _ = system
    record = approve(c, awaiting(c))
    corpus = json.loads(Path(c.settings.corpus_path).read_text())
    corpus["documents"][0]["valid_until"] = "2028-01-01T00:00:00Z"
    changed = tmp_path / "corpus.json"
    changed.write_text(json.dumps(corpus), encoding="utf-8")
    c.settings.corpus_path = str(changed)
    with pytest.raises(Denied, match="changed"):
        asyncio.run(c.execute(record.run.run_id))
    assert not executor.calls


def test_real_fixture_fits_teams_card_without_losing_approved_content(system: Any) -> None:
    from innexq_api.teams import approval_card

    c, _, _, _, _ = system
    r = awaiting(c)
    card = approval_card(r).model_dump(by_alias=True, exclude_none=True)
    text = json.dumps(card)
    assert len(text.encode()) < 28000
    for action in r.envelope.action_manifest.actions:
        for value in action.parameters.values():
            assert str(value) in "\n".join(item["text"] for item in card["body"])


def test_duplicate_callback_during_write_does_not_discard_receipts(system: Any) -> None:
    c, store, _, executor, _ = system
    r = approve(c, awaiting(c))
    original = executor.execute

    async def execute_with_duplicate(action: Action) -> str:
        approve(c, r)
        with pytest.raises(Denied, match="progress"):
            await c.execute(r.run.run_id)
        return await original(action)

    executor.execute = execute_with_duplicate
    final = asyncio.run(c.execute(r.run.run_id))
    assert final.run.state == RunState.EXECUTED
    assert len(final.receipts) == len(executor.calls) == 2
    assert sum(e.event_type == "execution.denied" for e in store.events(r.run.run_id)) == 2

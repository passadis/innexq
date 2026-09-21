"""Diagnostic precision must not expose input or change fail-closed behavior."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from innexq_api.adapters import FoundryAgent
from innexq_api.assembly_diagnostics import opaque_id, reason_code, response_status
from innexq_api.controller import Denied
from innexq_contracts.models import RunState

from tests.unit.test_controller import detected


@pytest.mark.parametrize("value", [None, {}, "private\ncontent", "x" * 129, "https://private"])
def test_opaque_id_rejects_unbounded_or_structured_values(value):
    assert opaque_id(value) == "unavailable"


def test_reason_and_status_only_emit_fixed_labels():
    assert opaque_id("caresp_123-abc") == "caresp_123-abc"
    assert (
        reason_code("Proposal summary must be an exact cited excerpt") == "hosted_summary_mismatch"
    )
    assert reason_code("Proposal summary must be an exact cited excerpt: PRIVATE") == "unclassified"
    assert reason_code({"private": "payload"}) == "unclassified"
    assert response_status("PRIVATE") == "unknown"
    assert response_status(None) == "unknown"
    assert response_status("failed") == "failed"


def test_failed_response_preserves_only_ids_status_and_fixed_reason(system, monkeypatch, caplog):
    controller, _, fake, executor, approvals = system
    current = detected(controller)
    project = MagicMock()
    project.__enter__.return_value = project
    project.agents.create_session.return_value.agent_session_id = "session-123"
    client = project.get_openai_client.return_value.__enter__.return_value
    client.responses.create.return_value = SimpleNamespace(
        id="caresp_123",
        status="failed",
        error=SimpleNamespace(message="Proposal summary must be an exact cited excerpt"),
        output_text="PRIVATE-CONTENT",
    )
    monkeypatch.setattr("azure.ai.projects.AIProjectClient", MagicMock(return_value=project))
    with caplog.at_level(logging.INFO, logger="innexq.audit"):
        with pytest.raises(Denied, match="did not complete"):
            asyncio.run(FoundryAgent(controller.settings, MagicMock()).propose(current.run))
    result = next(r for r in caplog.records if r.msg == "foundry_response_received")
    assert result.reason_code == "hosted_summary_mismatch"
    assert result.agent_session_id == "session-123" and result.response_id == "caresp_123"
    assert result.run_id == str(current.run.run_id)
    assert result.correlation_id == str(current.run.correlation_id)
    assert result.response_status == "failed"
    assert "PRIVATE-CONTENT" not in repr([r.__dict__ for r in caplog.records])
    assert not executor.calls and not approvals.calls
    assert fake.proposal is not None


@pytest.mark.parametrize("failure", ["agent", "duplicate", "private_exception"])
def test_hold_records_stage_without_changing_outcome(system, failure):
    controller, store, agent, executor, approvals = system
    current = detected(controller)
    if failure == "duplicate":
        agent.proposal.citations.append(agent.proposal.citations[0])
    else:

        async def fail(run):
            if failure == "agent":
                raise Denied("Hosted Agent response did not complete")
            raise ValueError("PRIVATE-CONTENT")

        agent.propose = fail
    with pytest.raises(Denied, match="assembly failed safely"):
        asyncio.run(
            controller.assemble(
                current.run.run_id,
                controller.settings.tenant_id,
                controller.settings.approver_user_id,
                current.revision,
            )
        )
    event = store.events(current.run.run_id)[-1]
    assert event.state == RunState.EVIDENCE_HOLD
    assert event.details["failed_stage"] == (
        "validate_evidence" if failure == "duplicate" else "agent_proposal"
    )
    assert (
        event.details["reason_code"]
        == {
            "agent": "hosted_response_incomplete",
            "duplicate": "citation_duplicate",
            "private_exception": "unclassified",
        }[failure]
    )
    assert "PRIVATE-CONTENT" not in repr(event)
    assert not executor.calls and not approvals.calls

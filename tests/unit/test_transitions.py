from __future__ import annotations

import pytest
from innexq_contracts import (
    InvalidTransition,
    RunState,
    allowed_targets,
    assert_transition,
    can_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunState.DETECTED, RunState.CONTEXT_ASSEMBLING),
        (RunState.CONTEXT_ASSEMBLING, RunState.CONTEXT_ASSEMBLED),
        (RunState.CONTEXT_ASSEMBLED, RunState.POLICY_VERIFIED),
        (RunState.POLICY_VERIFIED, RunState.AWAITING_APPROVAL),
        (RunState.AWAITING_APPROVAL, RunState.ESCALATED),
        (RunState.ESCALATED, RunState.AWAITING_APPROVAL),
        (RunState.AWAITING_APPROVAL, RunState.APPROVED),
        (RunState.APPROVED, RunState.EXECUTING),
        (RunState.EXECUTING, RunState.EXECUTION_FAILED),
        (RunState.EXECUTION_FAILED, RunState.EXECUTING),
        (RunState.EXECUTING, RunState.EXECUTED),
        (RunState.AWAITING_APPROVAL, RunState.CLOSED_REJECTED),
        (RunState.ESCALATED, RunState.CLOSED_REJECTED),
        (RunState.EVIDENCE_HOLD, RunState.CONTEXT_ASSEMBLING),
    ],
)
def test_valid_transitions(current: RunState, target: RunState) -> None:
    assert can_transition(current, target)
    assert_transition(current, target)


@pytest.mark.parametrize(
    "current",
    [
        RunState.DETECTED,
        RunState.CONTEXT_ASSEMBLING,
        RunState.CONTEXT_ASSEMBLED,
        RunState.POLICY_VERIFIED,
        RunState.AWAITING_APPROVAL,
        RunState.ESCALATED,
    ],
)
def test_every_preapproval_state_can_enter_evidence_hold(current: RunState) -> None:
    assert RunState.EVIDENCE_HOLD in allowed_targets(current)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunState.DETECTED, RunState.EXECUTED),
        (RunState.DETECTED, RunState.DETECTED),
        (RunState.EVIDENCE_HOLD, RunState.AWAITING_APPROVAL),
        (RunState.ESCALATED, RunState.APPROVED),
        (RunState.EXECUTED, RunState.EXECUTING),
        (RunState.CLOSED_REJECTED, RunState.DETECTED),
        (RunState.APPROVED, RunState.EVIDENCE_HOLD),
    ],
)
def test_invalid_transitions_fail_closed(current: RunState, target: RunState) -> None:
    assert not can_transition(current, target)
    with pytest.raises(InvalidTransition, match="is not allowed"):
        assert_transition(current, target)

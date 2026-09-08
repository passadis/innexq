"""Deny-by-default controller state-transition rules."""

from __future__ import annotations

from innexq_contracts.models import RunState

_PRE_APPROVAL_STATES = frozenset(
    {
        RunState.DETECTED,
        RunState.CONTEXT_ASSEMBLING,
        RunState.CONTEXT_ASSEMBLED,
        RunState.POLICY_VERIFIED,
        RunState.AWAITING_APPROVAL,
        RunState.ESCALATED,
    }
)

_BASE_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.DETECTED: frozenset({RunState.CONTEXT_ASSEMBLING}),
    RunState.CONTEXT_ASSEMBLING: frozenset({RunState.CONTEXT_ASSEMBLED}),
    RunState.CONTEXT_ASSEMBLED: frozenset({RunState.POLICY_VERIFIED}),
    RunState.POLICY_VERIFIED: frozenset({RunState.AWAITING_APPROVAL}),
    RunState.EVIDENCE_HOLD: frozenset({RunState.CONTEXT_ASSEMBLING}),
    RunState.AWAITING_APPROVAL: frozenset(
        {RunState.APPROVED, RunState.ESCALATED, RunState.CLOSED_REJECTED}
    ),
    RunState.ESCALATED: frozenset({RunState.AWAITING_APPROVAL, RunState.CLOSED_REJECTED}),
    RunState.APPROVED: frozenset({RunState.EXECUTING}),
    RunState.EXECUTING: frozenset({RunState.EXECUTED, RunState.EXECUTION_FAILED}),
    RunState.EXECUTION_FAILED: frozenset({RunState.EXECUTING}),
    RunState.EXECUTED: frozenset(),
    RunState.CLOSED_REJECTED: frozenset(),
}


class InvalidTransition(ValueError):
    """Raised when a caller requests an unlisted Run state transition."""


def allowed_targets(current: RunState) -> frozenset[RunState]:
    """Return all states reachable in one controller-owned transition."""

    targets = _BASE_TRANSITIONS[current]
    if current in _PRE_APPROVAL_STATES:
        targets = targets | {RunState.EVIDENCE_HOLD}
    return targets


def can_transition(current: RunState, target: RunState) -> bool:
    """Return whether a one-step state transition is explicitly allowed."""

    return target in allowed_targets(current)


def assert_transition(current: RunState, target: RunState) -> None:
    """Fail closed when a state transition is not explicitly allowed."""

    if not can_transition(current, target):
        raise InvalidTransition(f"transition from {current.value} to {target.value} is not allowed")

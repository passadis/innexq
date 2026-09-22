"""Deny-by-default coverage renewal transition matrix tests."""

from __future__ import annotations

import pytest
from innexq_contracts.coverage_renewal import (
    CoverageRenewalState,
    InvalidCoverageTransition,
    allowed_coverage_targets,
    assert_coverage_transition,
    can_coverage_transition,
)

S = CoverageRenewalState

EXPECTED: dict[CoverageRenewalState, frozenset[CoverageRenewalState]] = {
    S.CUSTOMER_REQUESTED: frozenset({S.EVIDENCE_ASSEMBLING, S.CANCELLED}),
    S.EVIDENCE_ASSEMBLING: frozenset({S.ELIGIBILITY_VERIFIED, S.EVIDENCE_HOLD, S.CANCELLED}),
    S.ELIGIBILITY_VERIFIED: frozenset({S.PACKAGE_DRAFTED, S.EVIDENCE_HOLD, S.CANCELLED}),
    S.PACKAGE_DRAFTED: frozenset({S.AWAITING_OPERATIONS_APPROVAL, S.EVIDENCE_HOLD, S.CANCELLED}),
    S.AWAITING_OPERATIONS_APPROVAL: frozenset({S.OPERATIONS_APPROVED, S.OPERATIONS_REJECTED}),
    S.OPERATIONS_APPROVED: frozenset({S.AWAITING_MANAGER_APPROVAL}),
    S.AWAITING_MANAGER_APPROVAL: frozenset({S.MANAGER_APPROVED, S.MANAGER_REJECTED}),
    S.MANAGER_APPROVED: frozenset({S.EXECUTING}),
    S.EXECUTING: frozenset({S.COMPLETED, S.EXECUTION_FAILED}),
    S.EXECUTION_FAILED: frozenset({S.EXECUTING}),
    S.EVIDENCE_HOLD: frozenset({S.EVIDENCE_ASSEMBLING, S.CANCELLED}),
    S.COMPLETED: frozenset(),
    S.OPERATIONS_REJECTED: frozenset(),
    S.MANAGER_REJECTED: frozenset(),
    S.CANCELLED: frozenset(),
}


def test_every_state_has_an_explicit_transition_policy() -> None:
    assert set(EXPECTED) == set(CoverageRenewalState)


@pytest.mark.parametrize("current", list(CoverageRenewalState))
def test_exact_targets_per_state(current: CoverageRenewalState) -> None:
    assert allowed_coverage_targets(current) == EXPECTED[current]


@pytest.mark.parametrize("current", list(CoverageRenewalState))
@pytest.mark.parametrize("target", list(CoverageRenewalState))
def test_full_matrix_denies_everything_not_listed(
    current: CoverageRenewalState, target: CoverageRenewalState
) -> None:
    allowed = target in EXPECTED[current]
    assert can_coverage_transition(current, target) is allowed
    if allowed:
        assert_coverage_transition(current, target)
    else:
        with pytest.raises(InvalidCoverageTransition):
            assert_coverage_transition(current, target)


def test_no_approval_state_is_cancellable() -> None:
    for state in (
        S.AWAITING_OPERATIONS_APPROVAL,
        S.OPERATIONS_APPROVED,
        S.AWAITING_MANAGER_APPROVAL,
        S.MANAGER_APPROVED,
        S.EXECUTING,
    ):
        assert not can_coverage_transition(state, S.CANCELLED)


def test_execution_cannot_be_reached_without_manager_approval() -> None:
    for state in CoverageRenewalState:
        if state is S.MANAGER_APPROVED or state is S.EXECUTION_FAILED:
            continue
        assert not can_coverage_transition(state, S.EXECUTING)

"""Two-person approval guard: negative security tests (ADR-018 D8)."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from innexq_contracts.coverage_renewal import (
    approvals_authorize_execution,
    compute_package_hash,
)

from tests.unit.coverage_factories import (
    MANAGER_OID,
    NOW,
    OPERATIONS_OID,
    manager_decision,
    operations_decision,
    package,
    quote,
)


def _authorized_setup() -> tuple:
    pkg = package()
    ops = operations_decision(pkg)
    mgr = manager_decision(pkg, ops)
    return pkg, compute_package_hash(pkg), ops, mgr


def test_both_valid_approvals_authorize() -> None:
    pkg, pkg_hash, ops, mgr = _authorized_setup()
    assert approvals_authorize_execution(pkg, pkg_hash, ops, mgr)


def test_same_person_cannot_perform_both_approvals() -> None:
    pkg, pkg_hash, ops, mgr = _authorized_setup()
    same = mgr.model_copy(update={"actor_object_id": OPERATIONS_OID})
    assert not approvals_authorize_execution(pkg, pkg_hash, ops, same)
    cased = mgr.model_copy(update={"actor_object_id": OPERATIONS_OID.upper()})
    assert not approvals_authorize_execution(pkg, pkg_hash, ops, cased)


def test_rejection_by_either_party_refuses_execution() -> None:
    pkg, pkg_hash, ops, mgr = _authorized_setup()
    ops_reject = ops.model_copy(update={"decision": "reject", "reject_reason": "pricing doubt"})
    assert not approvals_authorize_execution(pkg, pkg_hash, ops_reject, mgr)
    mgr_reject = mgr.model_copy(update={"decision": "reject", "reject_reason": "hold for audit"})
    assert not approvals_authorize_execution(pkg, pkg_hash, ops, mgr_reject)


def test_changed_package_invalidates_both_approvals() -> None:
    pkg, _, ops, mgr = _authorized_setup()
    changed = pkg.model_copy(
        update={"quote": quote(base_amount="1100.00", vat_amount="264.00", total_amount="1364.00")}
    )
    changed_hash = compute_package_hash(changed)
    assert not approvals_authorize_execution(changed, changed_hash, ops, mgr)


def test_manager_cannot_approve_a_different_package_version() -> None:
    pkg, pkg_hash, ops, mgr = _authorized_setup()
    stale_manager = mgr.model_copy(update={"package_version": 2})
    assert not approvals_authorize_execution(pkg, pkg_hash, ops, stale_manager)
    stale_hash = mgr.model_copy(update={"package_hash": "f" * 64})
    assert not approvals_authorize_execution(pkg, pkg_hash, ops, stale_hash)


def test_operations_note_change_invalidates_manager_approval() -> None:
    pkg, pkg_hash, ops, mgr = _authorized_setup()
    noted_ops = ops.model_copy(update={"note_sha256": "d" * 64})
    assert not approvals_authorize_execution(pkg, pkg_hash, noted_ops, mgr)


def test_manager_approval_must_follow_operations_approval() -> None:
    pkg, pkg_hash, ops, mgr = _authorized_setup()
    early = mgr.model_copy(update={"submitted_at": NOW - timedelta(minutes=5)})
    assert not approvals_authorize_execution(pkg, pkg_hash, ops, early)


def test_manager_approval_binds_the_exact_operations_decision() -> None:
    pkg, pkg_hash, ops, mgr = _authorized_setup()
    substituted = mgr.model_copy(update={"operations_decision_id": uuid4()})
    assert not approvals_authorize_execution(pkg, pkg_hash, ops, substituted)


def test_foreign_request_decisions_are_refused() -> None:
    pkg, pkg_hash, _ops, _mgr = _authorized_setup()
    other = package()
    foreign_ops = operations_decision(other, actor_object_id=OPERATIONS_OID)
    foreign_mgr = manager_decision(other, foreign_ops, actor_object_id=MANAGER_OID)
    assert not approvals_authorize_execution(pkg, pkg_hash, foreign_ops, foreign_mgr)

"""Staff approval surface: package-bound decisions, idempotent callbacks, scoped cards."""

import time
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from innexq_api.coverage_controller import CoverageAuthorizationError, CoverageController
from innexq_api.coverage_review import CoverageDecisionCommand, CoverageReviewService
from innexq_api.coverage_store import CosmosCoverageStore
from innexq_api.coverage_teams import CoverageCardDecision, manager_card, operations_card
from innexq_contracts.coverage_renewal import CoverageRenewalRecord, CoverageRenewalState
from pydantic import ValidationError

from tests.unit.test_coverage_controller import (
    MANAGER_OID,
    OPERATIONS_OID,
    Reader,
    awaiting_operations,
    setup,
)
from tests.unit.test_coverage_eligibility import NOW
from tests.unit.test_http_security import signed_api  # noqa: F401


def service_with_package() -> tuple[CoverageReviewService, CosmosCoverageStore, UUID]:
    controller, store, _ = setup()
    request_id = awaiting_operations(controller)
    return CoverageReviewService(controller), store, request_id


def command(record: CoverageRenewalRecord, decision: str = "approve", **changes: Any):
    assert record.package is not None and record.package_hash is not None
    return CoverageDecisionCommand.model_validate(
        {
            "decision": decision,
            "package_version": record.package.package_version,
            "package_hash": record.package_hash,
        }
        | changes
    )


def test_list_and_read_expose_progress_and_audit_events() -> None:
    service, _store, request_id = service_with_package()
    queue = service.list()
    assert len(queue) == 1
    assert queue[0]["public_progress"] == "Awaiting Operations"
    detail = service.read(request_id)
    assert detail["record"]["request_id"] == str(request_id)
    first = next(event["event_type"] for event in detail["events"])
    assert first == "coverage.customer_requested"


def test_decision_must_restate_the_stored_package_exactly() -> None:
    service, store, request_id = service_with_package()
    record, _ = store.get(request_id)
    for changes in [{"package_hash": "f" * 64}, {"package_version": 2}]:
        with pytest.raises(CoverageAuthorizationError):
            service.operations(request_id, OPERATIONS_OID, command(record, **changes))
    assert store.get(request_id)[0].state == CoverageRenewalState.AWAITING_OPERATIONS_APPROVAL


def test_operations_approval_advances_and_duplicate_callbacks_are_idempotent() -> None:
    service, store, request_id = service_with_package()
    record, _ = store.get(request_id)
    body = command(record, note_sha256="a" * 64)
    approved = service.operations(request_id, OPERATIONS_OID, body)
    assert approved.state == CoverageRenewalState.AWAITING_MANAGER_APPROVAL
    revision = approved.revision
    again = service.operations(request_id, OPERATIONS_OID.upper(), body)
    assert again.revision == revision
    assert again.state == CoverageRenewalState.AWAITING_MANAGER_APPROVAL


def test_manager_approval_requires_the_distinct_configured_identity() -> None:
    service, store, request_id = service_with_package()
    record, _ = store.get(request_id)
    body = command(record)
    service.operations(request_id, OPERATIONS_OID, body)
    with pytest.raises(CoverageAuthorizationError):
        service.manager(request_id, OPERATIONS_OID, body)
    final = service.manager(request_id, MANAGER_OID, body)
    assert final.state == CoverageRenewalState.MANAGER_APPROVED
    duplicate = service.manager(request_id, MANAGER_OID, body)
    assert duplicate.revision == final.revision


def test_manager_rejection_keeps_reason_internal() -> None:
    service, store, request_id = service_with_package()
    record, _ = store.get(request_id)
    service.operations(request_id, OPERATIONS_OID, command(record))
    rejected = service.manager(
        request_id, MANAGER_OID, command(record, decision="reject", reject_reason="pricing query")
    )
    assert rejected.state == CoverageRenewalState.MANAGER_REJECTED
    assert service.read(request_id)["public_progress"] == "Held or rejected"


def test_cards_bind_stage_version_and_hash() -> None:
    service, store, request_id = service_with_package()
    record, _ = store.get(request_id)
    ops = operations_card(record)
    assert any("Acknowledge and Approve" == action["title"] for action in ops["actions"])
    data = ops["actions"][0]["data"]
    assert data == {
        "request_id": str(request_id),
        "stage": "operations",
        "package_version": 1,
        "package_hash": record.package_hash,
    }
    assert CoverageCardDecision.model_validate(data).request_uuid() == request_id
    with pytest.raises(CoverageAuthorizationError):
        manager_card(record)  # no operations approval recorded yet
    approved = service.operations(request_id, OPERATIONS_OID, command(record))
    card = manager_card(approved)
    assert approved.operations_decision is not None
    assert str(approved.operations_decision.decision_id) in str(card["body"])
    assert card["actions"][0]["data"]["stage"] == "manager"
    with pytest.raises(CoverageAuthorizationError):
        operations_card(approved)  # stage already passed
    with pytest.raises(ValidationError):
        CoverageCardDecision.model_validate(data | {"actor": "attacker"})


def test_http_decisions_scope_operations_and_manager(signed_api: Any) -> None:  # noqa: F811
    client, c, key, claims = signed_api

    def bearer(**changes: Any) -> dict[str, str]:
        return {"Authorization": "Bearer " + jwt.encode(claims | changes, key, algorithm="RS256")}

    assert client.get("/api/operations/coverage", headers=bearer()).status_code == 503
    manager_oid = str(uuid4())
    c.settings.manager_user_id = manager_oid
    controller, store, _ = setup()
    controller = CoverageController(
        store,
        Reader(),
        operations_object_id=c.settings.approver_user_id,
        manager_object_id=manager_oid,
        now=lambda: NOW,
    )
    request_id = awaiting_operations(controller)
    client.app.state.coverage_review = CoverageReviewService(controller)
    listing = client.get("/api/operations/coverage", headers=bearer())
    assert listing.status_code == 200 and len(listing.json()) == 1
    record = store.get(request_id)[0]
    body = {
        "decision": "approve",
        "package_version": 1,
        "package_hash": record.package_hash,
    }
    path = f"/api/operations/coverage/{request_id}"
    scoped = bearer(scp="Cases.Manage")
    assert client.post(f"{path}/operations-decision", json=body, headers=bearer()).status_code in (
        401,
        403,
    )
    approved = client.post(f"{path}/operations-decision", json=body, headers=scoped)
    assert approved.status_code == 200
    assert approved.json()["state"] == "AWAITING_MANAGER_APPROVAL"
    # Operations cannot self-approve the manager stage; the refusal is sanitized.
    denied = client.post(f"{path}/manager-decision", json=body, headers=scoped)
    assert denied.status_code == 403 and denied.json() == {"detail": "Decision not authorized"}
    manager = bearer(oid=manager_oid, scp="Cases.Manage")
    final = client.post(f"{path}/manager-decision", json=body, headers=manager)
    assert final.status_code == 200 and final.json()["state"] == "MANAGER_APPROVED"
    duplicate = client.post(f"{path}/manager-decision", json=body, headers=manager)
    assert duplicate.status_code == 200 and duplicate.json()["state"] == "MANAGER_APPROVED"
    # Time-shifted expiry claims still refuse: not our concern here; unknown IDs are 404.
    missing = client.get(f"/api/operations/coverage/{uuid4()}/review", headers=bearer())
    assert missing.status_code == 404


def test_expired_token_is_refused_even_with_correct_roles(signed_api: Any) -> None:  # noqa: F811
    client, _c, key, claims = signed_api
    client.app.state.coverage_review = CoverageReviewService(setup()[0])
    stale = {
        "Authorization": "Bearer "
        + jwt.encode(claims | {"exp": int(time.time()) - 60}, key, algorithm="RS256")
    }
    assert client.get("/api/operations/coverage", headers=stale).status_code == 401

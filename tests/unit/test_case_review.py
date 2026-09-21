from copy import deepcopy
from datetime import timedelta
from typing import Any
from uuid import uuid4

import jwt
import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError
from fastapi.testclient import TestClient
from innexq_api.case_review import CaseReviewController
from innexq_api.certificate_store import REVIEW, SNAPSHOT
from innexq_api.config import Settings
from innexq_api.controller import Denied
from innexq_api.main import create_app
from innexq_api.store import Conflict
from innexq_contracts.case_review import CaseCommand, CaseReview, next_case_state
from innexq_contracts.certificates import CertificateSources
from pydantic import ValidationError

from tests.unit.test_certificate_store import setup
from tests.unit.test_certificates import CUSTOMER, NOW, OPERATIONS, REQUEST, TENANT
from tests.unit.test_controller import detected
from tests.unit.test_http_security import signed_api  # noqa: F401


def held():
    certificates, evidence, store, container = setup()
    evidence.value = CertificateSources()
    record = certificates.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    controller = CaseReviewController(store, TENANT, OPERATIONS, lambda: NOW)
    return controller, certificates, record, store, container


def command(review: CaseReview, action="acknowledge", note="", **changes):
    return CaseCommand.model_validate(
        {
            "command_id": uuid4(),
            "case_id": review.case_id,
            "decision_hash": review.decision_hash,
            "expected_revision": review.revision,
            "action": action,
            "note": note,
        }
        | changes
    )


def test_customer_progress_projects_only_public_transitions_and_never_releases():
    controller, certificates, record, store, container = held()
    baseline = deepcopy(container.items)
    initial = certificates.customer_status(TENANT, CUSTOMER, REQUEST)
    assert initial["case_status"] == "open"
    assert container.items == baseline
    review = controller.read(REQUEST)
    public_time = NOW
    for index, (action, state) in enumerate(
        [
            ("acknowledge", "acknowledged"),
            ("add_note", "acknowledged"),
            ("close_without_release", "closed_without_release"),
        ],
        start=1,
    ):
        event_time = NOW + timedelta(minutes=index)
        controller.now = lambda event_time=event_time: event_time
        review = controller.act(
            REQUEST, TENANT, OPERATIONS, command(review, action, "PRIVATE staff reasoning")
        )
        if action != "add_note":
            public_time = event_time
        before_read = deepcopy(container.items)
        public = certificates.customer_status(TENANT, CUSTOMER, REQUEST)
        assert public["case_status"] == state
        assert public["status"] == "operations_required"
        assert public["updated_at"] == public_time.isoformat().replace("+00:00", "Z")
        assert set(public) == {"request_id", "status", "message", "case_status", "updated_at"}
        assert "PRIVATE" not in str(public) and str(OPERATIONS) not in str(public)
        assert container.items == before_read and store.get(REQUEST) == record
        with pytest.raises(Denied):
            certificates.download(TENANT, CUSTOMER, REQUEST)
    assert public["message"] == "Operations has closed your request. No certificate was released."


@pytest.mark.parametrize(
    "field", ["request_id", "tenant_id", "case_id", "assigned_user_id", "decision_hash"]
)
def test_customer_status_rejects_misbound_review(field):
    controller, certificates, _, store, _ = held()
    review = controller.read(REQUEST)
    changes = {field: "f" * 64 if field == "decision_hash" else uuid4()}
    store.get_review = lambda _: review.model_copy(update=changes)
    with pytest.raises(Conflict):
        certificates.customer_status(TENANT, CUSTOMER, REQUEST)


def test_customer_cannot_read_foreign_case_progress_or_hide_store_failure():
    _, certificates, _, store, _ = held()

    def unavailable(_):
        raise RuntimeError("private database failure")

    store.get_review = unavailable
    with pytest.raises(Denied):
        certificates.customer_status(TENANT, OPERATIONS, REQUEST)
    with pytest.raises(Denied):
        certificates.customer_status(uuid4(), CUSTOMER, REQUEST)
    with pytest.raises(RuntimeError):
        certificates.customer_status(TENANT, CUSTOMER, REQUEST)


def test_case_lifecycle_audit_and_download_denied_after_closure():
    controller, certificates, record, store, container = held()
    original = deepcopy(container.items)
    review = controller.read(REQUEST)
    assert review.state == "open" and review.revision == 0
    assert container.items == original  # GET is not a migration/write.
    for action, note, state in [
        ("acknowledge", "", "acknowledged"),
        ("add_note", "Investigating the expired service record.", "acknowledged"),
        (
            "close_without_release",
            "Service evidence remains expired; no PDF released.",
            "closed_without_release",
        ),
    ]:
        body = command(review, action, note)
        review = controller.act(REQUEST, TENANT, OPERATIONS, body)
        assert review.state == state
        assert controller.act(REQUEST, TENANT, OPERATIONS, body) == review
        assert len(container.batches[-1]) == 2  # snapshot + immutable event atomically.
    assert review.revision == 3
    assert len({event.command.command_id for event in review.events}) == 3
    assert all(event.actor_user_id == OPERATIONS for event in review.events)
    assert store.get(REQUEST) == record
    assert all(container.items[key] == value for key, value in original.items())
    with pytest.raises(Denied):
        certificates.download(TENANT, CUSTOMER, REQUEST)
    with pytest.raises(Conflict):
        controller.act(REQUEST, TENANT, OPERATIONS, command(review, "add_note", "No reopening"))


def test_direct_closure_and_open_notes_are_allowed_but_reacknowledge_is_not():
    c, _, _, _, _ = held()
    review = c.act(
        REQUEST, TENANT, OPERATIONS, command(c.read(REQUEST), "add_note", "Source review")
    )
    assert review.state == "open"
    closed = c.act(REQUEST, TENANT, OPERATIONS, command(review, "close_without_release", "Held"))
    assert closed.state == "closed_without_release"
    with pytest.raises(ValueError):
        next_case_state("acknowledged", "acknowledge")


def test_command_id_payload_revision_and_case_binding_are_enforced():
    c, _, _, _, _ = held()
    initial = c.read(REQUEST)
    body = command(initial)
    c.act(REQUEST, TENANT, OPERATIONS, body)
    for bad in [
        body.model_copy(update={"note": "changed"}),
        command(initial),
        command(initial, case_id=uuid4()),
        command(initial, decision_hash="f" * 64),
    ]:
        with pytest.raises(Conflict):
            c.act(REQUEST, TENANT, OPERATIONS, bad)
    for tenant, actor in [(uuid4(), OPERATIONS), (TENANT, CUSTOMER)]:
        with pytest.raises(Denied):
            c.act(REQUEST, tenant, actor, body)


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "release"},
        {"action": "add_note", "note": "   "},
        {"action": "close_without_release"},
        {"note": "x" * 2001},
        {"expected_revision": True},
        {"expected_revision": -1},
        {"actor_user_id": str(OPERATIONS)},
        {"decision_hash": "invalid"},
    ],
)
def test_invalid_commands_are_rejected(changes):
    c, _, _, _, _ = held()
    with pytest.raises(ValidationError):
        command(c.read(REQUEST), **changes)


def test_store_failure_cas_and_audit_tampering_fail_closed():
    c, _, _, store, container = held()
    body = command(c.read(REQUEST))
    initial = deepcopy(container.items)
    for status, exception in [(412, Conflict), (503, CosmosHttpResponseError)]:
        container.fail_status = status
        with pytest.raises(exception):
            c.act(REQUEST, TENANT, OPERATIONS, body)
        assert container.items == initial
    container.fail_status = None
    review = c.act(REQUEST, TENANT, OPERATIONS, body)
    with pytest.raises(Conflict):
        store.commit_review(review, 0)  # create-only first commit
    with pytest.raises(Conflict):
        store.commit_review(review, 1)  # must append exactly one event
    with pytest.raises(ValidationError):
        CaseReview.model_validate(review.model_dump() | {"state": "open"})
    changed = review.events[0].model_copy(update={"actor_user_id": CUSTOMER})
    with pytest.raises(ValidationError):
        CaseReview.model_validate(review.model_dump() | {"events": (changed,)})
    c.now = lambda: NOW - timedelta(seconds=1)
    with pytest.raises(ValidationError):
        c.act(REQUEST, TENANT, OPERATIONS, command(review, "add_note", "backwards"))
    container.items[f"certificate:{REQUEST}", REVIEW]["review"]["request_id"] = str(uuid4())
    with pytest.raises(Conflict):
        c.read(REQUEST)


def test_foreign_ready_missing_and_corrupted_cases_cannot_be_managed():
    certificates, _, store, _ = setup()
    certificates.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    with pytest.raises(Denied):
        CaseReviewController(store, TENANT, OPERATIONS).read(REQUEST)
    c, _, _, store, container = held()
    with pytest.raises(KeyError):
        c.read(uuid4())
    with pytest.raises(Denied):
        CaseReviewController(store, uuid4(), OPERATIONS).read(REQUEST)
    with pytest.raises(Denied):
        CaseReviewController(store, TENANT, CUSTOMER).read(REQUEST)
    container.items[f"certificate:{REQUEST}", SNAPSHOT]["record"]["decision_hash"] = "0" * 64
    with pytest.raises(Denied):
        c.read(REQUEST)


def test_manager_read_only_scope_and_operations_write_scope(signed_api: Any):  # noqa: F811
    client, legacy, key, claims = signed_api
    manager = str(uuid4())
    legacy.settings.manager_user_id = manager
    run = detected(legacy)
    c, _, record, store, _ = held()
    # The signed API uses its fixture tenant and Operations IDs; explicitly match them.
    legacy.settings.tenant_id = str(TENANT)
    legacy.settings.approver_user_id = str(OPERATIONS)
    claims = claims | {
        "tid": str(TENANT),
        "oid": str(OPERATIONS),
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
    }
    client.app.state.certificate_store = store

    def headers(oid=str(OPERATIONS), scope="Runs.Read", **changes):
        return {
            "Authorization": "Bearer "
            + jwt.encode(claims | {"oid": oid, "scp": scope} | changes, key, algorithm="RS256")
        }

    root = f"/api/operations/certificates/{REQUEST}"
    body = command(c.read(REQUEST)).model_dump(mode="json")
    for actor in (manager, str(OPERATIONS)):
        response = client.get(root + "/review", headers=headers(actor))
        assert response.status_code == 200, response.text
        assert response.json()["can_manage"] == (actor == str(OPERATIONS))
        assert response.json()["review"]["state"] == "open"
        assert client.get("/api/operations/certificates", headers=headers(actor)).json()[0][
            "record"
        ]["request_id"] == str(REQUEST)
    for oid, scope, extra in [
        (str(OPERATIONS), "Runs.Read", {}),
        (str(OPERATIONS), "user_impersonation", {}),
        (manager, "Cases.Manage", {}),
        (str(CUSTOMER), "Cases.Manage", {}),
        (str(OPERATIONS), "Cases.Manage", {"idtyp": "app"}),
        (str(OPERATIONS), ["Cases.Manage"], {}),
    ]:
        assert (
            client.post(
                root + "/actions", json=body, headers=headers(oid, scope, **extra)
            ).status_code
            == 403
        )
    response = client.post(root + "/actions", json=body, headers=headers(scope="Cases.Manage"))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["state"] == "acknowledged"
    assert store.get(REQUEST) == record
    # Manager may never use legacy mutation scope, even if Entra issues it.
    for path in (
        "/api/runs/detect",
        "/api/demo/reset",
        f"/api/runs/{run.run.run_id}/assemble",
        f"/api/runs/{run.run.run_id}/request-approval",
    ):
        assert (
            client.post(
                path, json={"revision": 1}, headers=headers(manager, "user_impersonation")
            ).status_code
            == 403
        )


def test_manager_can_read_only_configured_owner_runs(signed_api: Any):  # noqa: F811
    client, c, key, claims = signed_api
    c.settings.manager_user_id = str(uuid4())
    record = detected(c)
    header = {
        "Authorization": "Bearer "
        + jwt.encode(
            claims | {"oid": c.settings.manager_user_id, "scp": "Runs.Read"}, key, algorithm="RS256"
        )
    }
    assert client.get("/api/runs", headers=header).json()[0]["run"]["run_id"] == str(
        record.run.run_id
    )
    for suffix in ("", "/events"):
        assert (
            client.get(f"/api/runs/{record.run.run_id}{suffix}", headers=header).status_code == 200
        )
    c.store.records[record.run.run_id] = record.model_copy(
        update={"run": record.run.model_copy(update={"owner_user_id": "outsider"})}
    )
    assert client.get(f"/api/runs/{record.run.run_id}", headers=header).status_code == 403


def test_case_cors_does_not_expand_legacy_or_customer_origins():
    client = TestClient(
        create_app(
            Settings(
                web_origins=["https://staff.example"], customer_origins=["https://customer.example"]
            )
        )
    )
    for path, origin, expected in [
        (f"/api/operations/certificates/{REQUEST}/actions", "https://staff.example", 200),
        (f"/api/operations/certificates/{REQUEST}/actions", "https://customer.example", 400),
        ("/api/runs", "https://staff.example", 400),
    ]:
        response = client.options(
            path,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert response.status_code == expected


def test_employee_role_collisions_are_rejected():
    with pytest.raises(ValueError):
        Settings(manager_user_id=str(OPERATIONS), approver_user_id=str(OPERATIONS))
    with pytest.raises(ValueError):
        Settings(manager_user_id=str(CUSTOMER), customer_bindings={str(CUSTOMER): "DEMO-FAB"})
    with pytest.raises(ValueError):
        Settings(approver_user_id=str(CUSTOMER), customer_bindings={str(CUSTOMER): "DEMO-FAB"})
    with pytest.raises(ValueError):
        Settings(manager_user_id="not-a-uuid")

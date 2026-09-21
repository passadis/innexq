from copy import deepcopy
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from innexq_api.certificate_store import (
    OUTBOX,
    SNAPSHOT,
    CertificateNotification,
    CosmosCertificateStore,
)
from innexq_api.certificates import CertificateController
from innexq_api.store import Conflict
from innexq_contracts.certificates import CertificateSources

from tests.unit.test_certificates import (
    CUSTOMER,
    NOW,
    OPERATIONS,
    REQUEST,
    TENANT,
    Evidence,
    Pdfs,
)


class Container:
    """SDK-shaped atomic batch fake. No remote services or production fallbacks."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.batches: list[list[Any]] = []
        self.fail_status: int | None = None
        self.queries: list[dict[str, Any]] = []

    def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        try:
            return deepcopy(self.items[partition_key, item])
        except KeyError as exc:
            raise CosmosResourceNotFoundError(status_code=404) from exc

    def execute_item_batch(self, operations: list[Any], partition_key: str) -> None:
        if self.fail_status:
            raise CosmosHttpResponseError(status_code=self.fail_status)
        working = deepcopy(self.items)
        for operation in operations:
            verb, args = operation[:2]
            doc = deepcopy(args[-1])
            key = (partition_key, doc["id"])
            assert doc["run_id"] == partition_key
            if verb == "create" and key in working:
                raise CosmosHttpResponseError(status_code=409)
            if verb == "replace" and (
                key not in working or working[key]["_etag"] != operation[2]["if_match_etag"]
            ):
                raise CosmosHttpResponseError(status_code=412)
            doc["_etag"] = str(int(working.get(key, {}).get("_etag", "0")) + 1)
            working[key] = doc
        self.items = working
        self.batches.append(deepcopy(operations))

    def query_items(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.queries.append({"query": query} | kwargs)
        parameters = {item["name"]: item["value"] for item in kwargs["parameters"]}
        if "@state" in parameters:
            return [
                deepcopy(doc)
                for (_, item), doc in self.items.items()
                if item == OUTBOX and doc["notification"]["state"] == parameters["@state"]
            ]
        return [
            deepcopy(doc)
            for (_, item), doc in self.items.items()
            if item == SNAPSHOT
            and doc["record"]["tenant_id"] == parameters["@tenant"]
            and (doc["record"]["operations_case"] or {}).get("assigned_user_id")
            == parameters["@actor"]
        ]


def setup() -> tuple[CertificateController, Evidence, CosmosCertificateStore, Container]:
    container = Container()
    store = CosmosCertificateStore(container)
    evidence = Evidence()
    controller = CertificateController(
        TENANT, {CUSTOMER: "DEMO-FAB"}, OPERATIONS, evidence, Pdfs(), store, lambda: NOW
    )
    return controller, evidence, store, container


def test_atomic_case_and_outbox_do_not_use_legacy_snapshot_or_partitions() -> None:
    controller, evidence, store, container = setup()
    evidence.value = CertificateSources()
    record = controller.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    assert store.get(REQUEST) == record
    assert len(container.batches) == 1
    assert len(container.batches[0]) == 7  # snapshot + four events + case + outbox
    assert all(key[0] == f"certificate:{REQUEST}" for key in container.items)
    assert all(key[1] != "snapshot" for key in container.items)
    assert store.get_notification(REQUEST).state == "pending"
    assert len(store.pending_notifications()) == 1
    assert controller.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST) == record
    assert len(container.batches) == 1
    assert store.list_operations_cases(TENANT, OPERATIONS) == [record]
    assert store.list_operations_cases(TENANT, CUSTOMER) == []
    assert store.list_operations_cases(UUID(int=999), OPERATIONS) == []
    assert all(q["enable_cross_partition_query"] for q in container.queries)


def test_cas_appends_only_new_events_and_held_download_creates_one_outbox() -> None:
    controller, evidence, store, container = setup()
    record = controller.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    with pytest.raises(KeyError):
        store.get_notification(REQUEST)
    controller.download(TENANT, CUSTOMER, REQUEST)
    updated = store.get(REQUEST)
    assert len(updated.events) == len(record.events) + 2
    assert len(container.batches[-1]) == 3
    original_events = {
        key: deepcopy(value) for key, value in container.items.items() if "event" in key[1]
    }
    evidence.value = CertificateSources()
    from innexq_api.controller import Denied

    with pytest.raises(Denied):
        controller.download(TENANT, CUSTOMER, REQUEST)
    assert len(store.pending_notifications()) == 1
    assert all(container.items[key] == value for key, value in original_events.items())
    decisions = [
        value["decision"]
        for key, value in container.items.items()
        if key[1].startswith("certificate-event-") and value.get("decision") is not None
    ]
    assert decisions[0]["outcome"] == "release_ready"
    assert decisions[-1]["outcome"] == "operations_required"
    with pytest.raises(Conflict, match="count changed"):
        store.commit(store.get(REQUEST), expected_events=3)


def test_changed_identity_or_old_event_rejected_before_batch() -> None:
    controller, _, store, container = setup()
    first = controller.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    controller.download(TENANT, CUSTOMER, REQUEST)
    extended = store.get(REQUEST)
    # Restore the first snapshot and audit to prepare competing updates.
    partition = f"certificate:{REQUEST}"
    container.items[partition, SNAPSHOT]["record"] = first.model_dump(mode="json")
    for field, value in [
        ("tenant_id", UUID(int=55)),
        ("actor_user_id", UUID(int=55)),
        ("customer_id", "OTHER"),
        ("equipment_id", "OTHER"),
    ]:
        with pytest.raises(Conflict, match="identity"):
            store.commit(extended.model_copy(update={field: value}), len(first.events))
    events = (
        first.events[0].model_copy(update={"event_type": "certificate.held"}),
        *extended.events[1:],
    )
    with pytest.raises(Conflict, match="immutable"):
        store.commit(extended.model_copy(update={"events": events}), len(first.events))
    with pytest.raises(Conflict, match="append"):
        store.commit(first, len(first.events))
    with pytest.raises(Conflict, match="append"):
        store.commit(first, -1)
    with pytest.raises(Conflict, match="does not exist"):
        store.commit(extended.model_copy(update={"request_id": UUID(int=88)}), len(first.events))


@pytest.mark.parametrize("status", [409, 412, 424, 500])
def test_failed_transaction_never_partially_persists(status: int) -> None:
    controller, evidence, store, container = setup()
    evidence.value = CertificateSources()
    container.fail_status = status
    expected = Conflict if status != 500 else CosmosHttpResponseError
    # Direct commit avoids controller's concurrent-create read-back behavior.
    record = controller._record(
        REQUEST,
        CUSTOMER,
        "DEMO-FAB",
        "DEMO-PT-001",
        controller._evaluate("DEMO-FAB", "DEMO-PT-001"),
    )
    with pytest.raises(expected):
        store.commit(record, 0)
    assert container.items == {}


def test_claim_receipt_and_ambiguous_recovery_never_requeue() -> None:
    controller, evidence, store, container = setup()
    evidence.value = CertificateSources()
    controller.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    claimed = store.claim_notification(REQUEST, NOW)
    assert claimed is not None and claimed.attempt_id is not None
    assert claimed.state == "claimed" and store.pending_notifications() == []
    assert store.claim_notification(REQUEST, NOW) is None
    with pytest.raises(Conflict, match="this attempt"):
        store.mark_delivered(REQUEST, UUID(int=999), "teams-receipt", NOW)
    with pytest.raises(ValueError, match="receipt"):
        store.mark_delivered(REQUEST, claimed.attempt_id, " ", NOW)
    store.mark_delivered(REQUEST, claimed.attempt_id, "teams-receipt", NOW)
    assert store.get_notification(REQUEST).receipt_id == "teams-receipt"
    assert store.claim_notification(REQUEST, NOW) is None
    assert store.recover_stale_claims(NOW, NOW) == 0
    request2 = UUID(int=22)
    controller.request(TENANT, CUSTOMER, "DEMO-PT-001", request2)
    second = store.claim_notification(request2, NOW)
    assert second is not None
    assert store.recover_stale_claims(NOW - timedelta(seconds=1), NOW) == 0
    assert store.recover_stale_claims(NOW, NOW + timedelta(minutes=5)) == 1
    assert store.get_notification(request2).state == "ambiguous"
    assert store.claim_notification(request2, NOW + timedelta(minutes=5)) is None
    assert store.pending_notifications() == []
    assert len([key for key in container.items if "notification-" in key[1]]) == 4


def test_notification_clocks_query_limits_and_cas_conflicts() -> None:
    controller, evidence, store, container = setup()
    evidence.value = CertificateSources()
    controller.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    with pytest.raises(ValueError, match="timezone"):
        store.claim_notification(REQUEST, NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="backwards"):
        store.claim_notification(REQUEST, NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match="limit"):
        store.pending_notifications(101)
    with pytest.raises(ValueError, match="limit"):
        store.list_operations_cases(TENANT, OPERATIONS, 0)
    with pytest.raises(ValueError, match="future"):
        store.recover_stale_claims(NOW + timedelta(minutes=1), NOW)
    with pytest.raises(ValueError, match="together"):
        store.recover_stale_claims(NOW, NOW, TENANT)
    container.fail_status = 412
    with pytest.raises(Conflict):
        store.claim_notification(REQUEST, NOW)
    assert store.get_notification(REQUEST).state == "pending"
    container.fail_status = None
    claim = store.claim_notification(REQUEST, NOW)
    assert claim is not None and claim.attempt_id is not None
    with pytest.raises(ValueError, match="backwards"):
        store.mark_ambiguous(REQUEST, claim.attempt_id, NOW - timedelta(seconds=1))
    container.fail_status = 412
    assert store.recover_stale_claims(NOW, NOW) == 0
    assert store.get_notification(REQUEST).state == "claimed"


def test_corrupt_notification_records_fail_closed() -> None:
    initial = CertificateNotification(
        request_id=REQUEST, tenant_id=TENANT, case_id=UUID(int=90), assigned_user_id=OPERATIONS
    ).payload()
    for changes in [
        {"state": "invalid"},
        {"state": "claimed"},
        {"attempt_id": str(UUID(int=91))},
        {"claimed_at": NOW.isoformat()},
        {"receipt_id": "forged"},
    ]:
        with pytest.raises(ValueError, match="invalid notification"):
            CertificateNotification.parse(initial | changes)


def test_case_cannot_change_and_partition_mismatch_is_rejected() -> None:
    controller, evidence, store, container = setup()
    evidence.value = CertificateSources()
    first = controller.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    updated = controller._record(
        REQUEST, CUSTOMER, "DEMO-FAB", "DEMO-PT-001", first.decision, prior=first
    )
    case = updated.operations_case
    assert case is not None
    forged = updated.model_copy(
        update={"operations_case": case.model_copy(update={"assigned_user_id": CUSTOMER})}
    )
    with pytest.raises(Conflict, match="Operations case is immutable"):
        store.commit(forged, len(first.events))
    store.commit(updated, len(first.events))
    assert len(store.pending_notifications()) == 1
    container.items[f"certificate:{REQUEST}", SNAPSHOT]["record"]["request_id"] = str(UUID(int=99))
    with pytest.raises(Conflict, match="partition identity"):
        store.get(REQUEST)


def test_oversized_commit_is_not_split_into_partial_writes() -> None:
    controller, _, store, container = setup()
    record = controller._record(
        REQUEST,
        CUSTOMER,
        "DEMO-FAB",
        "DEMO-PT-001",
        controller._evaluate("DEMO-FAB", "DEMO-PT-001"),
    )
    event = record.events[-1]
    extended = record.model_copy(
        update={"events": tuple(event.model_copy(update={"sequence": n}) for n in range(1, 101))}
    )
    with pytest.raises(Conflict, match="atomic batch limit"):
        store.commit(extended, 0)
    assert container.items == {}

"""Coverage renewal snapshots, immutable audit and invoice reservations in Cosmos.

Every renewal request uses its own prefixed /run_id partition. Invoice numbers
live in per-year reservation partitions; a create-only write makes duplicates
impossible even across concurrent executors.
"""

from typing import Any
from uuid import UUID, uuid4

from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from innexq_contracts.coverage_renewal import CoverageRenewalRecord

from innexq_api.store import Conflict

SNAPSHOT = "coverage-snapshot"
EVENT = "coverage-event"


class CosmosCoverageStore:
    """Inject the already-configured Cosmos ContainerProxy; never use an upsert."""

    def __init__(self, container: Any) -> None:
        self.container = container

    @staticmethod
    def _partition(request_id: UUID) -> str:
        return f"coverage:{request_id}"

    def _read(self, request_id: UUID, item: str) -> dict[str, Any]:
        try:
            return dict(self.container.read_item(item, partition_key=self._partition(request_id)))
        except CosmosResourceNotFoundError as exc:
            raise KeyError(str(request_id)) from exc

    def _batch(self, partition: str, operations: list[Any]) -> None:
        try:
            self.container.execute_item_batch(operations, partition_key=partition)
        except CosmosHttpResponseError as exc:
            if exc.status_code in (409, 412, 424):
                raise Conflict("concurrent coverage commit") from exc
            raise

    def create(self, record: CoverageRenewalRecord) -> None:
        record = CoverageRenewalRecord.model_validate(record.model_dump())
        if record.revision != 0:
            raise Conflict("a new renewal request must start at revision zero")
        partition = self._partition(record.request_id)
        self._batch(
            partition,
            [
                (
                    "create",
                    (
                        {
                            "id": SNAPSHOT,
                            "run_id": partition,
                            "record": record.model_dump(mode="json"),
                        },
                    ),
                ),
                ("create", (self._event(record, "coverage.customer_requested"),)),
            ],
        )

    def get(self, request_id: UUID) -> tuple[CoverageRenewalRecord, str]:
        document = self._read(request_id, SNAPSHOT)
        record = CoverageRenewalRecord.model_validate(document["record"])
        if record.request_id != request_id:
            raise Conflict("coverage partition identity is inconsistent")
        return record, document["_etag"]

    def commit(self, record: CoverageRenewalRecord, event_type: str, expected_etag: str) -> None:
        record = CoverageRenewalRecord.model_validate(record.model_dump())
        partition = self._partition(record.request_id)
        self._batch(
            partition,
            [
                (
                    "replace",
                    (
                        SNAPSHOT,
                        {
                            "id": SNAPSHOT,
                            "run_id": partition,
                            "record": record.model_dump(mode="json"),
                        },
                    ),
                    {"if_match_etag": expected_etag},
                ),
                ("create", (self._event(record, event_type),)),
            ],
        )

    def _event(self, record: CoverageRenewalRecord, event_type: str) -> dict[str, Any]:
        return {
            "id": f"{EVENT}-{record.revision}-{uuid4()}",
            "run_id": self._partition(record.request_id),
            "event_type": event_type,
            "revision": record.revision,
            "state": record.state.value,
            "occurred_at": record.updated_at.isoformat(),
        }

    def events(self, request_id: UUID) -> list[dict[str, Any]]:
        documents = self.container.query_items(
            "SELECT * FROM c WHERE c.run_id = @partition",
            parameters=[{"name": "@partition", "value": self._partition(request_id)}],
            partition_key=self._partition(request_id),
        )
        return sorted(
            (dict(doc) for doc in documents if doc["id"].startswith(f"{EVENT}-")),
            key=lambda doc: doc["revision"],
        )

    def list_renewals(self) -> list[CoverageRenewalRecord]:
        documents = self.container.query_items(
            query="SELECT * FROM c WHERE c.id = @item",
            parameters=[{"name": "@item", "value": SNAPSHOT}],
            enable_cross_partition_query=True,
        )
        records = [CoverageRenewalRecord.model_validate(doc["record"]) for doc in documents]
        return sorted(records, key=lambda record: record.updated_at, reverse=True)

    def reserve_invoice_number(self, year: int, sequence: int) -> str:
        """Create-only reservation; a duplicate raises Conflict and never reuses a number."""

        if not 2000 <= year <= 9999 or not 1 <= sequence <= 99999:
            raise ValueError("invoice reservation outside the synthetic numbering policy")
        invoice_number = f"SYN-INV-{year}-{sequence:05d}"
        partition = f"coverage-invoice:{year}"
        self._batch(
            partition,
            [("create", ({"id": invoice_number, "run_id": partition},))],
        )
        return invoice_number

    def allocate_next_invoice(self, year: int) -> str:
        """CAS counter plus create-only reservation in one atomic per-year batch."""

        partition = f"coverage-invoice:{year}"
        for _ in range(5):
            try:
                counter = dict(self.container.read_item("counter", partition_key=partition))
            except CosmosResourceNotFoundError:
                try:
                    self._batch(
                        partition,
                        [("create", ({"id": "counter", "run_id": partition, "value": 0},))],
                    )
                except Conflict:
                    pass  # another allocator created it; re-read and continue
                continue
            sequence = int(counter["value"]) + 1
            if sequence > 99999:
                raise Conflict("synthetic invoice numbering exhausted for the year")
            invoice_number = f"SYN-INV-{year}-{sequence:05d}"
            try:
                self._batch(
                    partition,
                    [
                        (
                            "replace",
                            ("counter", counter | {"value": sequence}),
                            {"if_match_etag": counter["_etag"]},
                        ),
                        ("create", ({"id": invoice_number, "run_id": partition},)),
                    ],
                )
            except Conflict:
                continue
            return invoice_number
        raise Conflict("invoice allocation contention")

    def create_execution(self, request_id: UUID, payload: dict[str, Any]) -> None:
        """Create-once execution receipt: the idempotency anchor for the executor."""

        partition = self._partition(request_id)
        self._batch(
            partition,
            [("create", ({"id": "coverage-execution", "run_id": partition, "payload": payload},))],
        )

    def get_execution(self, request_id: UUID) -> dict[str, Any] | None:
        try:
            return dict(self._read(request_id, "coverage-execution")["payload"])
        except KeyError:
            return None

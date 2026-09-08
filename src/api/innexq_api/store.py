"""Atomic Run snapshot plus append-only event commits in one Cosmos partition."""

from copy import deepcopy
from threading import Lock
from typing import Any, Protocol
from uuid import UUID

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from innexq_contracts.events import RunEvent, RunRecord
from innexq_contracts.models import VersionedBrief


class Conflict(ValueError):
    """An optimistic write lost the race; no action may follow it."""


class Store(Protocol):
    def get(self, run_id: UUID) -> RunRecord: ...
    def commit(self, record: RunRecord, event: RunEvent, expected: int) -> None: ...
    def events(self, run_id: UUID) -> list[RunEvent]: ...
    def list_runs(self, actor: str) -> list[RunRecord]: ...
    def get_teams_reference(self) -> dict[str, Any] | None: ...
    def save_teams_reference(self, reference: dict[str, Any]) -> None: ...
    def ping(self) -> None: ...


class MemoryStore:
    """Explicitly injected test fake, never selected by environment fallback."""

    def __init__(self) -> None:
        self.records: dict[UUID, RunRecord] = {}
        self.log: dict[UUID, list[RunEvent]] = {}
        self.briefs: dict[tuple[UUID, int], VersionedBrief] = {}
        self.lock = Lock()
        self.teams_reference: dict[str, Any] | None = None

    def get(self, run_id: UUID) -> RunRecord:
        return deepcopy(self.records[run_id])

    def commit(self, record: RunRecord, event: RunEvent, expected: int) -> None:
        with self.lock:
            current = self.records.get(record.run.run_id)
            if (current.revision if current else 0) != expected:
                raise Conflict("revision changed")
            if record.revision != expected + 1 or event.sequence != record.revision:
                raise Conflict("invalid event sequence")
            if event.event_type == "brief.versioned" and record.envelope is not None:
                key = (record.run.run_id, record.envelope.brief.brief_version)
                if key in self.briefs:
                    raise Conflict("brief version already exists")
                self.briefs[key] = deepcopy(record.envelope)
            self.records[record.run.run_id] = deepcopy(record)
            self.log.setdefault(record.run.run_id, []).append(deepcopy(event))

    def events(self, run_id: UUID) -> list[RunEvent]:
        return deepcopy(self.log.get(run_id, []))

    def list_runs(self, actor: str) -> list[RunRecord]:
        return [deepcopy(r) for r in self.records.values() if r.run.owner_user_id == actor]

    def get_teams_reference(self) -> dict[str, Any] | None:
        return deepcopy(self.teams_reference)

    def save_teams_reference(self, reference: dict[str, Any]) -> None:
        self.teams_reference = deepcopy(reference)

    def ping(self) -> None:
        return None


class CosmosStore:
    def __init__(self, endpoint: str, credential: Any, database: str, container: str) -> None:
        self.client = CosmosClient(endpoint, credential=credential)
        self.container = self.client.get_database_client(database).get_container_client(container)

    def get(self, run_id: UUID) -> RunRecord:
        try:
            doc = self.container.read_item("snapshot", partition_key=str(run_id))
        except CosmosResourceNotFoundError as exc:
            raise KeyError(str(run_id)) from exc
        return RunRecord.model_validate(doc["record"])

    def commit(self, record: RunRecord, event: RunEvent, expected: int) -> None:
        partition = str(record.run.run_id)
        if record.revision != expected + 1 or event.sequence != record.revision:
            raise Conflict("invalid event sequence")
        doc = {"id": "snapshot", "run_id": partition, "record": record.model_dump(mode="json")}
        operations: list[Any] = []
        if expected == 0:
            operations.append(("create", (doc,)))
        else:
            old = self.container.read_item("snapshot", partition_key=partition)
            if old["record"]["revision"] != expected:
                raise Conflict("revision changed")
            operations.append(("replace", ("snapshot", doc), {"if_match_etag": old["_etag"]}))
        operations.append(
            (
                "create",
                (
                    {
                        "id": f"event-{event.sequence:08d}",
                        "run_id": partition,
                        "event": event.model_dump(mode="json"),
                    },
                ),
            )
        )
        if event.event_type == "brief.versioned" and record.envelope is not None:
            operations.append(
                (
                    "create",
                    (
                        {
                            "id": f"brief-{record.envelope.brief.brief_version:08d}",
                            "run_id": partition,
                            "envelope": record.envelope.model_dump(mode="json"),
                            "evidence": [e.model_dump(mode="json") for e in record.evidence],
                        },
                    ),
                )
            )
        try:
            self.container.execute_item_batch(operations, partition_key=partition)
        except CosmosHttpResponseError as exc:
            if exc.status_code in (409, 412, 424):
                raise Conflict("concurrent event commit") from exc
            raise

    def events(self, run_id: UUID) -> list[RunEvent]:
        docs = self.container.query_items(
            "SELECT c.event FROM c WHERE IS_DEFINED(c.event) ORDER BY c.event.sequence",
            partition_key=str(run_id),
        )
        return [RunEvent.model_validate(doc["event"]) for doc in docs]

    def list_runs(self, actor: str) -> list[RunRecord]:
        docs = self.container.query_items(
            "SELECT TOP 100 c.record FROM c WHERE c.id = 'snapshot' "
            "AND c.record.run.owner_user_id = @actor ORDER BY c.record.run.created_at DESC",
            parameters=[{"name": "@actor", "value": actor}],
            enable_cross_partition_query=True,
        )
        return [RunRecord.model_validate(d["record"]) for d in docs]

    def get_teams_reference(self) -> dict[str, Any] | None:
        try:
            doc = self.container.read_item("teams-reference", partition_key="configuration")
        except CosmosResourceNotFoundError:
            return None
        return dict(doc["reference"])

    def save_teams_reference(self, reference: dict[str, Any]) -> None:
        self.container.upsert_item(
            {"id": "teams-reference", "run_id": "configuration", "reference": reference}
        )

    def ping(self) -> None:
        self.container.read()

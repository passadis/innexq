"""Certificate snapshots, immutable audit and conservative Teams outbox in Cosmos.

Every request uses its own prefixed /run_id partition, with no legacy `snapshot`
document. A send claim is irreversible: unknown outcomes require staff attention,
not an automatic retry that could duplicate a Teams notification.
"""

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from innexq_contracts.case_review import CaseReview
from innexq_contracts.certificates import CertificateRequestRecord
from innexq_contracts.customer_conversation import CustomerMessageRecord

from innexq_api.store import Conflict

SNAPSHOT = "certificate-snapshot"
OUTBOX = "certificate-operations-notification"
REVIEW = "certificate-case-review"
MESSAGE = "customer-message"
NotificationState = Literal["pending", "claimed", "delivered", "ambiguous"]


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("notification clock must be timezone-aware")


@dataclass(frozen=True)
class CertificateNotification:
    request_id: UUID
    tenant_id: UUID
    case_id: UUID
    assigned_user_id: UUID
    state: NotificationState = "pending"
    attempt_id: UUID | None = None
    claimed_at: datetime | None = None
    updated_at: datetime | None = None
    receipt_id: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            key: value.isoformat()
            if isinstance(value, datetime)
            else str(value)
            if isinstance(value, UUID)
            else value
            for key, value in asdict(self).items()
        }

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> "CertificateNotification":
        data = dict(payload)
        for key in ("request_id", "tenant_id", "case_id", "assigned_user_id", "attempt_id"):
            if data.get(key) is not None:
                data[key] = UUID(data[key])
        for key in ("claimed_at", "updated_at"):
            if data.get(key) is not None:
                data[key] = datetime.fromisoformat(data[key])
                _aware(data[key])
        result = cls(**data)
        if result.state not in ("pending", "claimed", "delivered", "ambiguous"):
            raise ValueError("invalid notification state")
        if (result.state != "pending") != (result.attempt_id is not None):
            raise ValueError("invalid notification attempt")
        if (result.state != "pending") != (result.claimed_at is not None):
            raise ValueError("invalid notification claim timestamp")
        if (result.state == "delivered") != bool(result.receipt_id):
            raise ValueError("invalid notification receipt")
        return result


class CosmosCertificateStore:
    """Inject the already-configured Cosmos ContainerProxy; never use an upsert."""

    def __init__(self, container: Any) -> None:
        self.container = container

    @staticmethod
    def _partition(request_id: UUID) -> str:
        return f"certificate:{request_id}"

    def _read(self, request_id: UUID, item: str) -> dict[str, Any]:
        try:
            return dict(self.container.read_item(item, partition_key=self._partition(request_id)))
        except CosmosResourceNotFoundError as exc:
            raise KeyError(str(request_id)) from exc

    def _batch(self, request_id: UUID, operations: list[Any]) -> None:
        try:
            self.container.execute_item_batch(operations, partition_key=self._partition(request_id))
        except CosmosHttpResponseError as exc:
            if exc.status_code in (409, 412, 424):
                raise Conflict("concurrent certificate commit") from exc
            raise

    def get(self, request_id: UUID) -> CertificateRequestRecord:
        record = CertificateRequestRecord.model_validate(self._read(request_id, SNAPSHOT)["record"])
        if record.request_id != request_id:
            raise Conflict("certificate partition identity is inconsistent")
        return record

    def get_message(self, message_id: UUID) -> CustomerMessageRecord:
        record = CustomerMessageRecord.model_validate(self._read(message_id, MESSAGE)["record"])
        if record.input.message_id != message_id:
            raise Conflict("message partition identity is inconsistent")
        return record

    def create_message(self, record: CustomerMessageRecord) -> None:
        record = CustomerMessageRecord.model_validate(record.model_dump())
        message_id = record.input.message_id
        self._batch(
            message_id,
            [
                (
                    "create",
                    (
                        {
                            "id": MESSAGE,
                            "run_id": self._partition(message_id),
                            "kind": MESSAGE,
                            "record": record.model_dump(mode="json"),
                        },
                    ),
                )
            ],
        )

    def commit(self, record: CertificateRequestRecord, expected_events: int) -> None:
        # Validate even model_copy-built input before persisting trusted state.
        record = CertificateRequestRecord.model_validate(record.model_dump())
        if expected_events < 0 or len(record.events) <= expected_events:
            raise Conflict("a commit must append events")
        partition = self._partition(record.request_id)
        document = {
            "id": SNAPSHOT,
            "run_id": partition,
            "kind": "certificate-request",
            "record": record.model_dump(mode="json"),
        }
        previous: CertificateRequestRecord | None = None
        operations: list[Any] = []
        if expected_events == 0:
            operations.append(("create", (document,)))
        else:
            try:
                old = self._read(record.request_id, SNAPSHOT)
            except KeyError as exc:
                raise Conflict("certificate request does not exist") from exc
            previous = CertificateRequestRecord.model_validate(old["record"])
            if len(previous.events) != expected_events:
                raise Conflict("certificate event count changed")
            if previous.events != record.events[:expected_events]:
                raise Conflict("prior certificate events are immutable")
            for field in (
                "request_id",
                "tenant_id",
                "actor_user_id",
                "customer_id",
                "equipment_id",
                "request_context",
            ):
                if getattr(previous, field) != getattr(record, field):
                    raise Conflict("certificate request identity is immutable")
            if previous.operations_case is not None and (
                previous.operations_case != record.operations_case
            ):
                raise Conflict("existing Operations case is immutable")
            operations.append(("replace", (SNAPSHOT, document), {"if_match_etag": old["_etag"]}))
        for event in record.events[expected_events:]:
            operations.append(
                (
                    "create",
                    (
                        {
                            "id": f"certificate-event-{event.sequence:08d}",
                            "run_id": partition,
                            "kind": "certificate-event",
                            "event": event.model_dump(mode="json"),
                            "decision_hash": record.decision_hash,
                            # Retain historical evidence when the mutable snapshot
                            # moves from release-ready to held during a download.
                            "decision": (
                                record.decision.model_dump(mode="json")
                                if event.event_type == "certificate.policy_checked"
                                else None
                            ),
                        },
                    ),
                )
            )
        if record.operations_case is not None and (
            previous is None or previous.operations_case is None
        ):
            case = record.operations_case
            notification = CertificateNotification(
                request_id=record.request_id,
                tenant_id=record.tenant_id,
                case_id=case.case_id,
                assigned_user_id=case.assigned_user_id,
                updated_at=record.events[-1].occurred_at,
            )
            operations.extend(
                [
                    (
                        "create",
                        (
                            {
                                "id": "certificate-operations-case",
                                "run_id": partition,
                                "case": case.model_dump(mode="json"),
                            },
                        ),
                    ),
                    (
                        "create",
                        (
                            {
                                "id": OUTBOX,
                                "run_id": partition,
                                "kind": "certificate-notification",
                                "notification": notification.payload(),
                            },
                        ),
                    ),
                ]
            )
        # Cosmos transaction limit. Never split a logical authorization commit.
        if len(operations) > 100:
            raise Conflict("certificate commit exceeds atomic batch limit")
        self._batch(record.request_id, operations)

    @staticmethod
    def _limit(limit: int) -> int:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return limit

    def list_operations_cases(
        self, tenant_id: UUID, assigned_user_id: UUID, limit: int = 100
    ) -> list[CertificateRequestRecord]:
        documents = self.container.query_items(
            "SELECT TOP @limit c.record FROM c "
            "WHERE c.id = 'certificate-snapshot' AND c.record.tenant_id = @tenant "
            "AND c.record.operations_case.assigned_user_id = @actor",
            parameters=[
                {"name": "@limit", "value": self._limit(limit)},
                {"name": "@tenant", "value": str(tenant_id)},
                {"name": "@actor", "value": str(assigned_user_id)},
            ],
            enable_cross_partition_query=True,
        )
        return [CertificateRequestRecord.model_validate(item["record"]) for item in documents]

    def get_notification(self, request_id: UUID) -> CertificateNotification:
        return CertificateNotification.parse(self._read(request_id, OUTBOX)["notification"])

    def get_review(self, request_id: UUID) -> CaseReview | None:
        try:
            document = self._read(request_id, REVIEW)
        except KeyError:
            return None
        review = CaseReview.model_validate(document["review"])
        if review.request_id != request_id:
            raise Conflict("review partition identity is inconsistent")
        return review

    def commit_review(self, review: CaseReview, expected_revision: int) -> None:
        review = CaseReview.model_validate(review.model_dump())
        if expected_revision < 0 or review.revision != expected_revision + 1:
            raise Conflict("case commit must append exactly one event")
        # Bind to the held snapshot, without modifying it or its notification.
        record = self.get(review.request_id)
        case = record.operations_case
        if (
            case is None
            or record.tenant_id != review.tenant_id
            or case.case_id != review.case_id
            or case.assigned_user_id != review.assigned_user_id
            or record.decision_hash != review.decision_hash
        ):
            raise Conflict("review does not match the held case")
        if review.events[0].occurred_at < record.events[-1].occurred_at:
            raise Conflict("review cannot precede the held decision")
        partition = self._partition(review.request_id)
        document = {
            "id": REVIEW,
            "run_id": partition,
            "kind": "certificate-case-review",
            "review": review.model_dump(mode="json"),
        }
        operations: list[Any]
        if expected_revision == 0:
            operations = [("create", (document,))]
        else:
            try:
                old = self._read(review.request_id, REVIEW)
            except KeyError as exc:
                raise Conflict("case review does not exist") from exc
            previous = CaseReview.model_validate(old["review"])
            if previous.revision != expected_revision or previous.events != review.events[:-1]:
                raise Conflict("case review changed; prior events are immutable")
            operations = [("replace", (REVIEW, document), {"if_match_etag": old["_etag"]})]
        operations.append(
            (
                "create",
                (
                    {
                        "id": f"certificate-case-event-{review.revision:08d}",
                        "run_id": partition,
                        "kind": "certificate-case-review-event",
                        "tenant_id": str(review.tenant_id),
                        "request_id": str(review.request_id),
                        "event": review.events[-1].model_dump(mode="json"),
                    },
                ),
            )
        )
        self._batch(review.request_id, operations)

    def _notifications(self, state: NotificationState, limit: int) -> list[CertificateNotification]:
        documents = self.container.query_items(
            "SELECT TOP @limit c.notification FROM c "
            "WHERE c.id = 'certificate-operations-notification' "
            "AND c.notification.state = @state",
            parameters=[
                {"name": "@limit", "value": self._limit(limit)},
                {"name": "@state", "value": state},
            ],
            enable_cross_partition_query=True,
        )
        return [CertificateNotification.parse(item["notification"]) for item in documents]

    def pending_notifications(self, limit: int = 50) -> list[CertificateNotification]:
        return self._notifications("pending", limit)

    def _transition(self, old: dict[str, Any], notification: CertificateNotification) -> None:
        document = {
            "id": OUTBOX,
            "run_id": self._partition(notification.request_id),
            "kind": "certificate-notification",
            "notification": notification.payload(),
        }
        self._batch(
            notification.request_id,
            [
                ("replace", (OUTBOX, document), {"if_match_etag": old["_etag"]}),
                (
                    "create",
                    (
                        {
                            "id": (
                                f"certificate-notification-{notification.attempt_id}"
                                f"-{notification.state}"
                            ),
                            "run_id": self._partition(notification.request_id),
                            "kind": "certificate-notification-event",
                            "notification": notification.payload(),
                        },
                    ),
                ),
            ],
        )

    def claim_notification(self, request_id: UUID, now: datetime) -> CertificateNotification | None:
        _aware(now)
        old = self._read(request_id, OUTBOX)
        current = CertificateNotification.parse(old["notification"])
        if current.state != "pending":
            return None
        if current.updated_at is not None and now < current.updated_at:
            raise ValueError("notification clock moved backwards")
        claimed = replace(
            current, state="claimed", attempt_id=uuid4(), claimed_at=now, updated_at=now
        )
        self._transition(old, claimed)
        return claimed

    def _finish(
        self,
        request_id: UUID,
        attempt_id: UUID,
        state: Literal["delivered", "ambiguous"],
        now: datetime,
        receipt_id: str | None = None,
    ) -> None:
        _aware(now)
        old = self._read(request_id, OUTBOX)
        current = CertificateNotification.parse(old["notification"])
        if current.state != "claimed" or current.attempt_id != attempt_id:
            raise Conflict("notification is not claimed by this attempt")
        if current.updated_at is not None and now < current.updated_at:
            raise ValueError("notification clock moved backwards")
        self._transition(old, replace(current, state=state, receipt_id=receipt_id, updated_at=now))

    def mark_delivered(
        self, request_id: UUID, attempt_id: UUID, receipt_id: str, now: datetime
    ) -> None:
        """The receipt proves Teams accepted a post, not that Operations read it."""
        if not receipt_id.strip():
            raise ValueError("Teams receipt is required")
        self._finish(request_id, attempt_id, "delivered", now, receipt_id)

    def mark_ambiguous(self, request_id: UUID, attempt_id: UUID, now: datetime) -> None:
        self._finish(request_id, attempt_id, "ambiguous", now)

    def recover_stale_claims(
        self,
        before: datetime,
        now: datetime,
        tenant_id: UUID | None = None,
        assigned_user_id: UUID | None = None,
    ) -> int:
        """Mark interrupted workers for staff attention. NEVER put a claim back in pending."""
        _aware(before)
        _aware(now)
        if before > now:
            raise ValueError("recovery cutoff cannot be in the future")
        if (tenant_id is None) != (assigned_user_id is None):
            raise ValueError("recovery authority requires tenant and assigned user together")
        recovered = 0
        for notification in self._notifications("claimed", 100):
            if tenant_id is not None and (
                notification.tenant_id != tenant_id
                or notification.assigned_user_id != assigned_user_id
            ):
                continue
            if (
                notification.claimed_at is not None
                and notification.claimed_at <= before
                and notification.attempt_id is not None
            ):
                try:
                    self.mark_ambiguous(notification.request_id, notification.attempt_id, now)
                except Conflict:
                    continue  # another worker completed it; do not modify its receipt
                recovered += 1
        return recovered

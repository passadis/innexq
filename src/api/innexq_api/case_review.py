"""Controller for audited case administration. No PDF or external-write capability."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from innexq_contracts.case_review import CaseCommand, CaseReview, CaseReviewEvent, next_case_state
from innexq_contracts.certificates import CertificateRequestRecord

from innexq_api.certificates import decision_hash
from innexq_api.controller import Denied
from innexq_api.store import Conflict


class ReviewStore(Protocol):
    def get(self, request_id: UUID) -> CertificateRequestRecord: ...
    def get_review(self, request_id: UUID) -> CaseReview | None: ...
    def commit_review(self, review: CaseReview, expected_revision: int) -> None: ...


class CaseReviewController:
    def __init__(
        self,
        store: ReviewStore,
        tenant_id: UUID,
        operations_user_id: UUID,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.tenant_id = tenant_id
        self.operations_user_id = operations_user_id
        self.now = now

    def read(self, request_id: UUID) -> CaseReview:
        record = self.store.get(request_id)
        case = record.operations_case
        if (
            record.tenant_id != self.tenant_id
            or case is None
            or case.assigned_user_id != self.operations_user_id
            or record.decision_hash
            != decision_hash(
                record.request_id,
                record.tenant_id,
                record.actor_user_id,
                record.customer_id,
                record.equipment_id,
                record.decision,
            )
        ):
            raise Denied("case is outside the configured Operations scope")
        initial = CaseReview(
            request_id=request_id,
            tenant_id=record.tenant_id,
            case_id=case.case_id,
            assigned_user_id=case.assigned_user_id,
            decision_hash=record.decision_hash,
        )
        current = self.store.get_review(request_id)
        if current is None:
            return initial
        if current.model_dump(exclude={"revision", "state", "events"}) != initial.model_dump(
            exclude={"revision", "state", "events"}
        ):
            raise Conflict("case review binding changed")
        return current

    def act(
        self, request_id: UUID, tenant_id: UUID, actor_id: UUID, command: CaseCommand
    ) -> CaseReview:
        if tenant_id != self.tenant_id or actor_id != self.operations_user_id:
            raise Denied("only assigned Operations may manage a case")
        current = self.read(request_id)
        if command.case_id != current.case_id or command.decision_hash != current.decision_hash:
            raise Conflict("case command is bound to different evidence")
        for event in current.events:
            if event.command.command_id == command.command_id:
                if event.command != command:
                    raise Conflict("command key cannot be reused for a different action")
                return current
        if command.expected_revision != current.revision:
            raise Conflict("case revision changed")
        if current.revision >= 1000:
            raise Conflict("case review audit limit reached")
        try:
            state = next_case_state(current.state, command.action)
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        event = CaseReviewEvent(
            sequence=current.revision + 1,
            actor_user_id=actor_id,
            occurred_at=self.now(),
            command=command,
        )
        updated = CaseReview.model_validate(
            current.model_dump()
            | {
                "revision": current.revision + 1,
                "state": state,
                "events": (*current.events, event),
            }
        )
        self.store.commit_review(updated, current.revision)
        return updated

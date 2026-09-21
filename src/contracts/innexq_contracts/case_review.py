"""Non-release Operations lifecycle, independent of certificate eligibility."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from innexq_contracts.models import Sha256Hex, StrictContract

CaseAction = Literal["acknowledge", "add_note", "close_without_release"]
CaseState = Literal["open", "acknowledged", "closed_without_release"]


class CaseCommand(StrictContract):
    command_id: UUID
    case_id: UUID
    decision_hash: Sha256Hex
    expected_revision: Annotated[int, Field(strict=True, ge=0)]
    action: CaseAction
    note: Annotated[str, Field(max_length=2000)] = ""

    @model_validator(mode="after")
    def note_required(self) -> Self:
        if self.action != "acknowledge" and not self.note:
            raise ValueError("notes and closure require an internal explanation")
        return self


def next_case_state(state: CaseState, action: CaseAction) -> CaseState:
    if state == "closed_without_release":
        raise ValueError("closed cases cannot be changed")
    if action == "acknowledge":
        if state != "open":
            raise ValueError("case is already acknowledged")
        return "acknowledged"
    if action == "close_without_release":
        return "closed_without_release"
    return state


class CaseReviewEvent(StrictContract):
    sequence: Annotated[int, Field(strict=True, ge=1)]
    actor_user_id: UUID
    occurred_at: AwareDatetime
    command: CaseCommand


class CaseReview(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    tenant_id: UUID
    case_id: UUID
    assigned_user_id: UUID
    decision_hash: Sha256Hex
    revision: Annotated[int, Field(strict=True, ge=0)] = 0
    state: CaseState = "open"
    events: Annotated[tuple[CaseReviewEvent, ...], Field(max_length=1000)] = ()

    @model_validator(mode="after")
    def replay(self) -> Self:
        state: CaseState = "open"
        seen: set[UUID] = set()
        for sequence, event in enumerate(self.events, start=1):
            command = event.command
            if (
                event.sequence != sequence
                or command.expected_revision != sequence - 1
                or command.case_id != self.case_id
                or command.decision_hash != self.decision_hash
                or event.actor_user_id != self.assigned_user_id
                or command.command_id in seen
            ):
                raise ValueError("review event binding is inconsistent")
            if sequence > 1 and event.occurred_at < self.events[sequence - 2].occurred_at:
                raise ValueError("review clock moved backwards")
            seen.add(command.command_id)
            state = next_case_state(state, command.action)
        if self.revision != len(self.events) or self.state != state:
            raise ValueError("review snapshot does not match its audit")
        return self

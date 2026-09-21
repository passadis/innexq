"""Bounded customer conversation; interpretation is never release authority."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, model_validator

from innexq_contracts.models import StrictContract

MessageText = Annotated[str, Field(min_length=1, max_length=1000)]
EquipmentId = Annotated[str, Field(pattern=r"^DEMO-[A-Z0-9-]+$", max_length=80)]
CustomerIntent = Literal[
    "certificate_request",
    "service_status",
    "certificate_status",
    "service_request",
    "general",
    "clarify",
]


class CustomerMessage(StrictContract):
    message_id: UUID
    prompt: MessageText
    equipment_id: EquipmentId | None = None
    parent_message_id: UUID | None = None


class CustomerInterpretation(StrictContract):
    request_id: UUID
    intent: CustomerIntent
    equipment_id: EquipmentId | None


class CustomerCitation(StrictContract):
    document_id: Annotated[str, Field(min_length=1, max_length=200)]
    document_version: Annotated[str, Field(min_length=1, max_length=200)]
    page: Annotated[int, Field(ge=1)]
    label: Annotated[str, Field(min_length=1, max_length=200)]
    value: Annotated[str, Field(min_length=1, max_length=1000)]


class CustomerReply(StrictContract):
    message_id: UUID
    intent: CustomerIntent
    equipment_id: EquipmentId | None
    kind: Literal["answer", "clarification", "confirmation_required", "unsupported"]
    message: Annotated[str, Field(min_length=1, max_length=2000)]
    as_of: AwareDatetime | None = None
    citations: Annotated[tuple[CustomerCitation, ...], Field(max_length=30)] = ()
    can_confirm: StrictBool = False

    @model_validator(mode="after")
    def confirmation_is_only_a_certificate_proposal(self) -> Self:
        if self.can_confirm != (self.kind == "confirmation_required"):
            raise ValueError("confirmation flag must match reply kind")
        if self.can_confirm and (self.intent != "certificate_request" or self.equipment_id is None):
            raise ValueError("only an identified certificate request may be confirmed")
        return self


class CustomerRequestContext(StrictContract):
    customer_messages: Annotated[tuple[MessageText, ...], Field(min_length=1, max_length=6)]
    interpreted_intent: Literal["certificate_request"] = "certificate_request"
    equipment_id: EquipmentId
    interpreter_response_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class CustomerMessageRecord(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    tenant_id: UUID
    actor_user_id: UUID
    customer_id: Annotated[str, Field(pattern=r"^DEMO-[A-Z0-9-]+$")]
    input: CustomerMessage
    customer_messages: Annotated[tuple[MessageText, ...], Field(min_length=1, max_length=6)]
    interpreter_response_id: Annotated[str, Field(min_length=1, max_length=200)]
    reply: CustomerReply
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def consistent_turn(self) -> Self:
        if self.input.message_id != self.reply.message_id:
            raise ValueError("message identity mismatch")
        if self.customer_messages[-1] != self.input.prompt:
            raise ValueError("last customer message must be preserved exactly")
        if self.expires_at <= self.created_at:
            raise ValueError("proposal expiry must follow creation")
        return self

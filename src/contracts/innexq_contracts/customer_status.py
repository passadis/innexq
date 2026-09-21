"""Public certificate eligibility and case progress, never internal review notes."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from innexq_contracts.models import NonEmptyText, StrictContract


class CustomerCertificateStatus(StrictContract):
    request_id: UUID
    status: Literal["release_ready", "operations_required"]
    message: NonEmptyText
    case_status: Literal["not_required", "open", "acknowledged", "closed_without_release"]
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def consistent_status(self) -> Self:
        if (self.status == "release_ready") != (self.case_status == "not_required"):
            raise ValueError("case progress cannot authorize certificate release")
        return self

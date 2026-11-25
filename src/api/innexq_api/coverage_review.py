"""Staff review surface for coverage renewals; decisions bind to the exact package."""

from typing import Any, Literal
from uuid import UUID

from innexq_contracts.coverage_renewal import CoverageRenewalRecord
from innexq_contracts.models import StrictContract
from pydantic import Field

from innexq_api.coverage_controller import (
    CoverageAuthorizationError,
    CoverageController,
    public_progress,
)


class CoverageDecisionCommand(StrictContract):
    """The reviewer restates exactly what was displayed; drift refuses the decision."""

    decision: Literal["approve", "reject"]
    package_version: int = Field(ge=1)
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    note_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reject_reason: str | None = Field(default=None, min_length=1, max_length=500)


class CoverageReviewService:
    """Reads and stage decisions; the controller alone owns transitions and identity."""

    def __init__(self, controller: CoverageController) -> None:
        self.controller = controller

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "record": record.model_dump(mode="json"),
                "public_progress": public_progress(record),
            }
            for record in self.controller.store.list_renewals()
        ]

    def read(self, request_id: UUID) -> dict[str, Any]:
        record, _ = self.controller.store.get(request_id)
        return {
            "record": record.model_dump(mode="json"),
            "public_progress": public_progress(record),
            "events": self.controller.store.events(request_id),
        }

    def _bind(self, record: CoverageRenewalRecord, command: CoverageDecisionCommand) -> None:
        if (
            record.package is None
            or record.package_hash is None
            or record.package.package_version != command.package_version
            or record.package_hash != command.package_hash
        ):
            raise CoverageAuthorizationError("decision does not match the stored package")

    def operations(
        self, request_id: UUID, actor_object_id: str, command: CoverageDecisionCommand
    ) -> CoverageRenewalRecord:
        record, _ = self.controller.store.get(request_id)
        existing = record.operations_decision
        # A duplicate callback for the identical recorded decision is acknowledged, not replayed.
        if (
            existing is not None
            and existing.actor_object_id.casefold() == actor_object_id.casefold()
            and existing.decision == command.decision
            and existing.package_hash == command.package_hash
        ):
            return record
        self._bind(record, command)
        return self.controller.operations_decide(
            request_id,
            actor_object_id,
            command.decision,
            note_sha256=command.note_sha256,
            reject_reason=command.reject_reason,
        )

    def manager(
        self, request_id: UUID, actor_object_id: str, command: CoverageDecisionCommand
    ) -> CoverageRenewalRecord:
        record, _ = self.controller.store.get(request_id)
        existing = record.manager_decision
        if (
            existing is not None
            and existing.actor_object_id.casefold() == actor_object_id.casefold()
            and existing.decision == command.decision
            and existing.package_hash == command.package_hash
        ):
            return record
        self._bind(record, command)
        return self.controller.manager_decide(
            request_id,
            actor_object_id,
            command.decision,
            reject_reason=command.reject_reason,
        )

"""Coverage renewal approval cards: decisions bind to the frozen package hash.

Card data is display plus binding only; the controller re-validates identity,
state, version and hash on every callback.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from innexq_contracts.coverage_renewal import (
    CoverageRenewalRecord,
    CoverageRenewalState,
    RenewalPackage,
    compute_package_hash,
)
from pydantic import BaseModel, ConfigDict, Field

from innexq_api.controller import Denied
from innexq_api.coverage_controller import CoverageAuthorizationError

CARD_PAYLOAD_LIMIT = 24_000


class CoverageCardDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str
    stage: Literal["operations", "manager"]
    package_version: int = Field(ge=1)
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def request_uuid(self) -> UUID:
        return UUID(self.request_id)


def _verified_package(
    record: CoverageRenewalRecord, state: CoverageRenewalState
) -> tuple[RenewalPackage, str]:
    package, package_hash = record.package, record.package_hash
    if package is None or package_hash is None or record.state != state:
        raise CoverageAuthorizationError("a frozen package awaiting this decision is required")
    if package_hash != compute_package_hash(package):
        raise CoverageAuthorizationError("stored package hash mismatch")
    return package, package_hash


def _facts(record: CoverageRenewalRecord) -> list[dict[str, str]]:
    package = record.package
    assert package is not None  # noqa: S101 - guarded by _verified_package
    quote = package.quote
    return [
        {"title": "Customer", "value": package.customer_id},
        {"title": "Equipment", "value": package.equipment_id},
        {"title": "Serial", "value": package.serial_number},
        {"title": "Coverage", "value": f"{package.coverage_months} months on approval"},
        {"title": "Base", "value": f"{quote.currency} {quote.base_amount}"},
        {
            "title": f"VAT {quote.vat_rate_percent}% (synthetic)",
            "value": f"{quote.currency} {quote.vat_amount}",
        },
        {"title": "Total", "value": f"{quote.currency} {quote.total_amount}"},
        {
            "title": "Previous document",
            "value": f"{package.previous_document.document_id} "
            f"v{package.previous_document.document_version}",
        },
    ]


def _card(
    record: CoverageRenewalRecord,
    stage: Literal["operations", "manager"],
    heading: str,
    notes: list[str],
    approve_title: str,
) -> dict[str, Any]:
    package, package_hash = record.package, record.package_hash
    assert package is not None and package_hash is not None  # noqa: S101 - guarded upstream
    data = {
        "request_id": str(record.request_id),
        "stage": stage,
        "package_version": package.package_version,
        "package_hash": package_hash,
    }
    payload = {
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": heading,
                "size": "Large",
                "weight": "Bolder",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "SYNTHETIC DEMO · human authorization required · no fiscal document",
                "isSubtle": True,
                "wrap": True,
            },
            {"type": "FactSet", "facts": _facts(record)},
            *[{"type": "TextBlock", "text": note, "wrap": True} for note in notes],
            {
                "type": "TextBlock",
                "text": f"Package v{package.package_version} · SHA-256 {package_hash}",
                "size": "Small",
                "isSubtle": True,
                "wrap": True,
            },
        ],
        "actions": [
            {"type": "Action.Execute", "title": approve_title, "verb": "approve", "data": data},
            {"type": "Action.Execute", "title": "Reject", "verb": "reject", "data": data},
        ],
    }
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > CARD_PAYLOAD_LIMIT:
        raise Denied("approval card exceeds safe payload limit")
    return payload


def operations_card(record: CoverageRenewalRecord) -> dict[str, Any]:
    _verified_package(record, CoverageRenewalState.AWAITING_OPERATIONS_APPROVAL)
    return _card(
        record,
        "operations",
        "InnexQ | Coverage renewal — Operations review",
        [
            "Acknowledging approves this exact evidence-checked package for Manager "
            "review. Nothing is issued or charged until the Manager also approves.",
            "Rejecting stops the renewal; the customer sees a generic hold notice.",
        ],
        "Acknowledge and Approve",
    )


def manager_card(record: CoverageRenewalRecord) -> dict[str, Any]:
    _verified_package(record, CoverageRenewalState.AWAITING_MANAGER_APPROVAL)
    operations = record.operations_decision
    if operations is None or operations.decision != "approve":
        raise CoverageAuthorizationError("a recorded operations approval is required")
    return _card(
        record,
        "manager",
        "InnexQ | Coverage renewal — Manager approval",
        [
            f"Operations approved decision {operations.decision_id} at "
            f"{operations.submitted_at.isoformat()}. Self-approval is refused.",
            "Approving authorizes issuing exactly this certificate and synthetic "
            "invoice; coverage starts on the approval date. Rejecting issues nothing.",
        ],
        f"Approve package v{record.package.package_version if record.package else 0}",
    )

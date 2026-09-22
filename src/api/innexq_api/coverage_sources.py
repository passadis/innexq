"""Fixture-backed trusted sources and agent-directed citations for renewals (ADR-018).

The synthetic coverage corpus is the source of record for the demo. Adapters here
only surface facts; the controller still recomputes every eligibility verdict,
price and package hash deterministically. Agent citations carry evidence, never
executable authority, and cite the same registered amount the controller reads,
so an honest investigation never drifts the deterministic price.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from innexq_contracts.certificates import OwnershipSource
from innexq_contracts.coverage_renewal import (
    BillingProfileSource,
    CoverageDocumentSource,
    CoverageEvidenceSources,
    CoverageRenewalRecord,
    CoverageSourceFact,
    CoverageToolReceipt,
    EquipmentStatusSource,
    RenewalPolicySource,
)


class CoverageFixtureError(RuntimeError):
    """The synthetic coverage corpus is missing or malformed."""


def _aware(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FixtureCoverageSourceReader:
    """Trusted read-only adapter over the synthetic coverage corpus."""

    def __init__(self, scenarios_path: str, policy_path: str) -> None:
        try:
            scenarios = json.loads(Path(scenarios_path).read_text(encoding="utf-8"))
            self._policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CoverageFixtureError("coverage corpus is unavailable") from exc
        self._version = str(scenarios["as_of"])
        self._observed_at = _aware(scenarios["as_of"])
        self._fresh_until = _aware(scenarios["fresh_until"])
        self._by_equipment: dict[tuple[str, str], dict[str, Any]] = {
            (scenario["customer_id"], scenario["equipment_id"]): scenario
            for scenario in scenarios["scenarios"]
        }

    def scenario(self, customer_id: str, equipment_id: str) -> dict[str, Any] | None:
        return self._by_equipment.get((customer_id, equipment_id))

    def equipment_ids(self, customer_id: str) -> tuple[str, ...]:
        return tuple(equipment for (owner, equipment) in self._by_equipment if owner == customer_id)

    def pricing_rule_version(self) -> str:
        return str(self._policy["pricing_rule_version"])

    def _stamp(self) -> dict[str, Any]:
        return {
            "source_version": self._version,
            "observed_at": self._observed_at,
            "fresh_until": self._fresh_until,
        }

    def sources(self, customer_id: str, equipment_id: str) -> CoverageEvidenceSources:
        scenario = self.scenario(customer_id, equipment_id)
        if scenario is None:
            return CoverageEvidenceSources()
        stamp = self._stamp()
        serial = scenario["serial_number"]
        document_data = scenario.get("document")
        document = None
        if document_data is not None:
            document = CoverageDocumentSource(
                **stamp,
                customer_id=customer_id,
                equipment_id=equipment_id,
                serial_number=serial,
                document_id=document_data["document_id"],
                document_version=document_data["document_version"],
                sha256=document_data["sha256"],
                document_type=document_data["document_type"],
                coverage_from=_aware(document_data["coverage_from"]),
                coverage_until=_aware(document_data["coverage_until"]),
                accessible=document_data.get("accessible"),
                registry_document_version=document_data["document_version"],
                registry_sha256=document_data["sha256"],
            )
        billing_data = scenario["billing_profile"]
        return CoverageEvidenceSources(
            ownership=OwnershipSource(
                **stamp, customer_id=customer_id, equipment_id=equipment_id, serial_number=serial
            ),
            document=document,
            equipment=EquipmentStatusSource(
                **stamp,
                customer_id=customer_id,
                equipment_id=equipment_id,
                serial_number=serial,
                status=scenario["equipment_status"],
            ),
            billing=BillingProfileSource(
                **stamp,
                customer_id=customer_id,
                legal_name=billing_data.get("legal_name"),
                address_line=billing_data.get("address_line"),
                city=billing_data.get("city"),
                country_code=billing_data.get("country_code"),
                vat_id=billing_data.get("vat_id"),
            ),
            policy=RenewalPolicySource(
                **stamp,
                policy_id=self._policy["policy_id"],
                policy_version=self._policy["policy_version"],
                pricing_rule_id=self._policy["pricing_rule_id"],
                pricing_rule_version=self._policy["pricing_rule_version"],
            ),
        )

    def base_amount(self, customer_id: str, equipment_id: str) -> str:
        scenario = self.scenario(customer_id, equipment_id)
        if scenario is None:
            raise CoverageFixtureError("no registered price for the requested equipment")
        return str(scenario["annual_coverage_price"])

    def customer_name(self, customer_id: str) -> str:
        for scenario in self._by_equipment.values():
            if scenario["customer_id"] == customer_id:
                name = scenario["billing_profile"].get("legal_name")
                if name:
                    return str(name)
        raise CoverageFixtureError("no registered billing name for the customer")


class FixtureCoverageInvestigator:
    """Agent-directed evidence as verifiable citations over the same corpus."""

    def __init__(
        self,
        reader: FixtureCoverageSourceReader,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reader, self._now = reader, now

    def investigate(
        self, record: CoverageRenewalRecord
    ) -> tuple[tuple[CoverageSourceFact, ...], tuple[CoverageToolReceipt, ...], str | None]:
        scenario = self._reader.scenario(record.customer_id, record.equipment_id)
        document = None if scenario is None else scenario.get("document")
        if scenario is None or document is None:
            # No renewable document to cite; the controller holds on missing evidence.
            return (), (), None
        completed_at = self._now()
        facts = (
            CoverageSourceFact(
                document_id=document["document_id"],
                document_version=document["document_version"],
                sha256=document["sha256"],
                label="coverage_until",
                value=document["coverage_until"],
                page=1,
            ),
        )
        receipts = (
            CoverageToolReceipt(
                attempt_id=uuid4(),
                receipt_id=uuid4(),
                specialist="renewal_coordinator",
                tool_name="analyze_service_coverage_document",
                source_version=document["document_version"],
                document_id=document["document_id"],
                completed_at=completed_at,
            ),
            CoverageToolReceipt(
                attempt_id=uuid4(),
                receipt_id=uuid4(),
                specialist="coverage_billing",
                tool_name="calculate_renewal_quote",
                source_version=self._reader.pricing_rule_version(),
                completed_at=completed_at,
            ),
        )
        return facts, receipts, str(scenario["annual_coverage_price"])

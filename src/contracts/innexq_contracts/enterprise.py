"""Additive catalogue contracts; no identity grants or executable authorizations."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from innexq_contracts.models import NonEmptyText, StrictContract

DemoId = Annotated[str, Field(pattern=r"^DEMO-[A-Z0-9-]+$")]
MoneyText = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)\.[0-9]{2}$")]
DocumentKind = Literal["contract", "service_report", "certificate"]
RequestKind = Literal["certificate_request", "tier_upgrade_request"]


class DemoCustomer(StrictContract):
    customer_id: DemoId
    name: NonEmptyText
    preferred_language: Literal["en-GB", "sv-SE", "el-GR"]


class DemoContract(StrictContract):
    contract_id: DemoId
    customer_id: DemoId
    tier: Literal["Silver", "Gold"]
    starts_on: date
    expires_on: date
    annual_price: MoneyText
    currency: Literal["EUR"] = "EUR"
    document_id: DemoId

    @model_validator(mode="after")
    def ordered_dates(self) -> Self:
        if self.expires_on <= self.starts_on:
            raise ValueError("contract expiry must follow start")
        return self


class DemoEquipment(StrictContract):
    equipment_id: DemoId
    customer_id: DemoId
    contract_id: DemoId
    label: NonEmptyText
    serial_number: DemoId
    model: NonEmptyText
    service_valid_until: date
    service_document_id: DemoId
    certificate_document_id: DemoId | None


class DemoDocument(StrictContract):
    document_id: DemoId
    customer_id: DemoId
    contract_id: DemoId
    kind: DocumentKind
    equipment_id: DemoId | None = None
    recorded_serial_number: DemoId | None = None
    issued_on: date
    valid_until: date
    # A generated local filename, never a claim of uploaded/authorized availability.
    filename: Annotated[str, Field(pattern=r"^DEMO-[A-Z0-9-]+\.pdf$")]
    disclosure: Literal["SYNTHETIC DEMO - NOT VALID FOR REAL EQUIPMENT"] = (
        "SYNTHETIC DEMO - NOT VALID FOR REAL EQUIPMENT"
    )

    @model_validator(mode="after")
    def valid_document(self) -> Self:
        if self.valid_until < self.issued_on:
            raise ValueError("document validity must not precede issue")
        if self.filename != self.document_id + ".pdf":
            raise ValueError("filename must match document ID")
        if (self.kind == "contract") != (self.equipment_id is None):
            raise ValueError("only equipment documents require equipment ID")
        if (self.kind == "contract") != (self.recorded_serial_number is None):
            raise ValueError("only equipment documents require serial number")
        return self


class DemoSalesEntry(StrictContract):
    entry_id: DemoId
    customer_id: DemoId
    booked_on: date
    kind: Literal["invoice", "credit_note"]
    net_amount: MoneyText
    currency: Literal["EUR"] = "EUR"


class DemoRequestPreset(StrictContract):
    preset_id: DemoId
    customer_id: DemoId
    request_kind: RequestKind
    text: NonEmptyText
    equipment_id: DemoId | None = None
    contract_id: DemoId | None = None

    @model_validator(mode="after")
    def one_target(self) -> Self:
        if self.request_kind == "certificate_request":
            valid = self.equipment_id is not None and self.contract_id is None
        else:
            valid = self.contract_id is not None and self.equipment_id is None
        if not valid:
            raise ValueError("preset must have exactly the target for its request kind")
        return self


class EnterpriseDemoCatalog(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: Literal["innexq-equipment-demo-v1"] = "innexq-equipment-demo-v1"
    as_of: date
    synthetic: Literal[True] = True
    customers: Annotated[tuple[DemoCustomer, ...], Field(min_length=1, max_length=3)]
    contracts: Annotated[tuple[DemoContract, ...], Field(min_length=1, max_length=6)]
    equipment: Annotated[tuple[DemoEquipment, ...], Field(min_length=1, max_length=10)]
    documents: Annotated[tuple[DemoDocument, ...], Field(min_length=1)]
    sales: tuple[DemoSalesEntry, ...]
    presets: Annotated[tuple[DemoRequestPreset, ...], Field(min_length=1, max_length=10)]

    @model_validator(mode="after")
    def connected_catalog(self) -> Self:
        customers = {item.customer_id: item for item in self.customers}
        contracts = {item.contract_id: item for item in self.contracts}
        equipment = {item.equipment_id: item for item in self.equipment}
        documents = {item.document_id: item for item in self.documents}
        for count, unique in (
            (len(self.customers), len(customers)),
            (len(self.contracts), len(contracts)),
            (len(self.equipment), len(equipment)),
            (len(self.documents), len(documents)),
            (len(self.sales), len({item.entry_id for item in self.sales})),
            (len(self.presets), len({item.preset_id for item in self.presets})),
            (len(self.equipment), len({item.serial_number for item in self.equipment})),
        ):
            if count != unique:
                raise ValueError("duplicate catalogue identifier")

        def check_document(
            document_id: str, kind: DocumentKind, contract_id: str, equipment_id: str | None
        ) -> None:
            document = documents.get(document_id)
            if (
                document is None
                or document.kind != kind
                or document.contract_id != contract_id
                or document.equipment_id != equipment_id
            ):
                raise ValueError("invalid document relationship")

        for contract in self.contracts:
            if contract.customer_id not in customers:
                raise ValueError("unknown customer")
            check_document(contract.document_id, "contract", contract.contract_id, None)
        for item in self.equipment:
            owning_contract = contracts.get(item.contract_id)
            if owning_contract is None or item.customer_id != owning_contract.customer_id:
                raise ValueError("invalid equipment ownership")
            check_document(
                item.service_document_id, "service_report", item.contract_id, item.equipment_id
            )
            if item.certificate_document_id is not None:
                check_document(
                    item.certificate_document_id,
                    "certificate",
                    item.contract_id,
                    item.equipment_id,
                )
        for document in self.documents:
            document_contract = contracts.get(document.contract_id)
            if document_contract is None or document.customer_id != document_contract.customer_id:
                raise ValueError("invalid document ownership")
            if document.kind != "contract":
                document_equipment = equipment.get(document.equipment_id or "")
                if (
                    document_equipment is None
                    or document_equipment.contract_id != document.contract_id
                ):
                    raise ValueError("invalid document equipment")
            # A mismatching recorded serial is intentionally retained as conflicting
            # evidence for later live extraction, NOT accepted as a valid certificate.
        for sale in self.sales:
            if sale.customer_id not in customers:
                raise ValueError("unknown sales customer")
        for preset in self.presets:
            target = (
                equipment.get(preset.equipment_id or "")
                if preset.request_kind == "certificate_request"
                else contracts.get(preset.contract_id or "")
            )
            if target is None or target.customer_id != preset.customer_id:
                raise ValueError("invalid preset ownership")
        return self

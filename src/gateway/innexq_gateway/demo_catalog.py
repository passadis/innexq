"""Reproducible fictional source records, isolated from the live renewal fixture."""

from datetime import date, timedelta

from innexq_contracts.enterprise import (
    DemoContract,
    DemoCustomer,
    DemoDocument,
    DemoEquipment,
    DemoRequestPreset,
    DemoSalesEntry,
    EnterpriseDemoCatalog,
)


def build_demo_catalog(as_of: date) -> EnterpriseDemoCatalog:
    customers = (
        DemoCustomer(
            customer_id="DEMO-FAB", name="Fabrikam Industrial AB", preferred_language="sv-SE"
        ),
        DemoCustomer(customer_id="DEMO-NW", name="Northwind Logistics", preferred_language="en-GB"),
        DemoCustomer(
            customer_id="DEMO-ALP", name="Alpine Warehouse Services", preferred_language="el-GR"
        ),
    )
    contracts: list[DemoContract] = []
    documents: list[DemoDocument] = []
    equipment: list[DemoEquipment] = []
    presets: list[DemoRequestPreset] = []
    sales: list[DemoSalesEntry] = []
    for index, customer in enumerate(customers):
        for sequence in (1, 2):
            contract_id = f"{customer.customer_id}-CON-{sequence}"
            document_id = f"{contract_id}-PDF"
            contract = DemoContract(
                contract_id=contract_id,
                customer_id=customer.customer_id,
                tier="Silver" if sequence == 1 else "Gold",
                starts_on=as_of - timedelta(days=320),
                expires_on=as_of + timedelta(days=(30 if index == 0 else 120) * sequence),
                annual_price="7200.00" if sequence == 1 else "12000.00",
                document_id=document_id,
            )
            contracts.append(contract)
            documents.append(
                DemoDocument(
                    document_id=document_id,
                    customer_id=customer.customer_id,
                    contract_id=contract_id,
                    kind="contract",
                    issued_on=contract.starts_on,
                    valid_until=contract.expires_on,
                    filename=document_id + ".pdf",
                )
            )
        # Source invoices and credit notes, not a pre-decided eligibility outcome.
        sales.extend(
            (
                DemoSalesEntry(
                    entry_id=f"{customer.customer_id}-INV-1",
                    customer_id=customer.customer_id,
                    booked_on=as_of - timedelta(days=120),
                    kind="invoice",
                    net_amount=("18000.00", "9000.00", "10000.00")[index],
                ),
                DemoSalesEntry(
                    entry_id=f"{customer.customer_id}-CR-1",
                    customer_id=customer.customer_id,
                    booked_on=as_of - timedelta(days=30),
                    kind="credit_note",
                    net_amount=("1000.00", "600.00", "0.00")[index],
                ),
            )
        )
    # Four Fabrikam, three Northwind, three Alpine machines; ten in total.
    owners = [0, 0, 0, 0, 1, 1, 1, 2, 2, 2]
    for number, owner in enumerate(owners, start=1):
        customer_id = customers[owner].customer_id
        equipment_id = f"DEMO-PT-{number:03d}"
        serial = f"DEMO-SERIAL-{number:04d}"
        contract_id = f"{customer_id}-CON-{1 if number % 2 else 2}"
        service_id = f"{equipment_id}-SERVICE"
        certificate_id = None if number == 3 else f"{equipment_id}-CERT"
        service_until = as_of + timedelta(days=-1 if number == 2 else 90)
        equipment.append(
            DemoEquipment(
                equipment_id=equipment_id,
                customer_id=customer_id,
                contract_id=contract_id,
                label=f"Pallet truck PT-{number:03d}",
                serial_number=serial,
                model="Contoso Lift E20 (fictional)",
                service_valid_until=service_until,
                service_document_id=service_id,
                certificate_document_id=certificate_id,
            )
        )
        documents.append(
            DemoDocument(
                document_id=service_id,
                customer_id=customer_id,
                contract_id=contract_id,
                equipment_id=equipment_id,
                recorded_serial_number=serial,
                kind="service_report",
                issued_on=as_of - timedelta(days=180),
                valid_until=service_until,
                filename=service_id + ".pdf",
            )
        )
        if certificate_id is not None:
            documents.append(
                DemoDocument(
                    document_id=certificate_id,
                    customer_id=customer_id,
                    contract_id=contract_id,
                    equipment_id=equipment_id,
                    recorded_serial_number="DEMO-SERIAL-CONFLICT" if number == 4 else serial,
                    kind="certificate",
                    issued_on=as_of - timedelta(days=180),
                    valid_until=as_of + timedelta(days=-1 if number == 5 else 180),
                    filename=certificate_id + ".pdf",
                )
            )
        if number <= 7:
            presets.append(
                DemoRequestPreset(
                    preset_id=f"DEMO-REQ-{number:02d}",
                    customer_id=customer_id,
                    request_kind="certificate_request",
                    equipment_id=equipment_id,
                    text=f"Please provide the certificate for my pallet truck PT-{number:03d}.",
                )
            )
    for number, customer in enumerate(customers, start=8):
        presets.append(
            DemoRequestPreset(
                preset_id=f"DEMO-REQ-{number:02d}",
                customer_id=customer.customer_id,
                request_kind="tier_upgrade_request",
                contract_id=f"{customer.customer_id}-CON-1",
                text="Can you upgrade my Silver equipment service contract to Gold?",
            )
        )
    return EnterpriseDemoCatalog(
        as_of=as_of,
        customers=tuple(customers),
        contracts=tuple(contracts),
        equipment=tuple(equipment),
        documents=tuple(documents),
        sales=tuple(sales),
        presets=tuple(presets),
    )

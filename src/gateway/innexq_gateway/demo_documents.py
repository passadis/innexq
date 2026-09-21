"""Escaped fictional PDF source templates; never a production contract generator."""

from html import escape

from innexq_contracts.enterprise import DemoDocument, EnterpriseDemoCatalog


def render_demo_document(catalog: EnterpriseDemoCatalog, document: DemoDocument) -> str:
    if document not in catalog.documents:
        raise ValueError("document must belong to this catalogue")
    customer = next(item for item in catalog.customers if item.customer_id == document.customer_id)
    contract = next(item for item in catalog.contracts if item.contract_id == document.contract_id)
    titles = {
        "contract": "Equipment service agreement",
        "service_report": "Equipment service report",
        "certificate": "Equipment certificate - fictional sample",
    }
    rows = [
        ("Document ID", document.document_id),
        ("Customer", customer.name),
        ("Customer ID", customer.customer_id),
        ("Contract ID", contract.contract_id),
        ("Issued on", document.issued_on.isoformat()),
        ("Valid until", document.valid_until.isoformat()),
    ]
    if document.kind == "contract":
        rows.extend(
            [
                ("Service tier", contract.tier),
                ("Service starts", contract.starts_on.isoformat()),
                ("Contract expires", contract.expires_on.isoformat()),
                (
                    "Annual service price (excluding VAT)",
                    f"{contract.currency} {contract.annual_price}",
                ),
            ]
        )
        machine_rows = "".join(
            f"<tr><td>{escape(item.label)}</td><td>{escape(item.serial_number)}</td></tr>"
            for item in catalog.equipment
            if item.contract_id == contract.contract_id
        )
        detail = (
            "<h2>1. Parties and covered equipment</h2><p>Contoso Engineering Services "
            "(fictional provider) and the customer identified above.</p>"
            "<table><thead><tr><th>Equipment</th><th>Serial number</th></tr></thead>"
            f"<tbody>{machine_rows}</tbody></table>"
            "<h2>2. Service scope</h2><p>Scheduled maintenance, recorded inspections and "
            "support for the listed equipment. Replacement equipment and third-party "
            "certification are excluded. Service records identify the next due date.</p>"
            "<h2>3. Commercial terms</h2><p>The annual price and tier are stated above. "
            "Invoices are payable within 30 days. No discount or tier change is effective "
            "without a separately approved commercial package. This sample states no "
            "tax rate and makes no tax calculation.</p>"
            "<h2>4. Customer responsibilities</h2><p>Provide safe access and accurate "
            "equipment identifiers. Report damage and service changes. This fictional "
            "agreement is not permission to operate real machinery.</p>"
            "<h2>5. Renewal and changes</h2><p>No automatic renewal is granted. A renewal "
            "requires an exact proposed agreement, Operations review and final manager "
            "approval before delivery. Internal approval is not a customer signature.</p>"
            "<h2>6. Data and records</h2><p>Service documents are associated with the "
            "identified customer and equipment. Document access is limited to authorized "
            "parties; references do not grant access.</p>"
            "<h2>7. Demonstration limitations</h2><p>This document is unsigned, fictional "
            "and non-binding. It is not legal advice or an enforceable agreement. "
            "Production terms require separate business and legal review.</p>"
            '<p class="signature">Provider signature: NOT SIGNED &nbsp; '
            "Customer signature: NOT SIGNED</p>"
        )
    else:
        item = next(
            item for item in catalog.equipment if item.equipment_id == document.equipment_id
        )
        rows.extend(
            [
                ("Equipment ID", item.equipment_id),
                ("Equipment", item.label),
                ("Model", item.model),
                ("Recorded serial number", document.recorded_serial_number or ""),
            ]
        )
        if document.kind == "service_report":
            rows.append(("Next service due", item.service_valid_until.isoformat()))
            detail = (
                "<h2>Recorded demonstration activities</h2><ul><li>Visual inspection "
                "recorded in the fictional service dataset.</li><li>Brake, lift and "
                "battery checks represented as sample maintenance activities.</li>"
                "<li>Next service due date shown above.</li></ul><h2>Limitations</h2>"
                "<p>No real inspection was performed. No fitness-for-use conclusion "
                "or technical safety instruction is provided. The dates are source "
                "facts for a governed-workflow demonstration.</p>"
            )
        else:
            detail = (
                "<h2>Certificate scope</h2><p>This fictional sample records the equipment "
                "and serial number above for testing document retrieval and validation. "
                "It is not a manufacturer, CE, regulatory or accredited inspection "
                "certificate and must never be used for real equipment.</p>"
                "<h2>Release conditions</h2><p>A certificate request must be checked "
                "against current customer ownership, authoritative equipment records, "
                "document validity and current service eligibility. The presence of "
                "this PDF alone does not establish eligibility.</p>"
                "<h2>Issuer</h2><p>Contoso Engineering Services - fictional demo issuer. "
                "No accreditation, signature or real inspection is claimed.</p>"
            )
    table_rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>" for label, value in rows
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
        f"<title>{escape(document.document_id)}</title><style>"
        "@page{size:A4;margin:18mm}body{font:12px Arial,sans-serif;color:#173047;"
        "line-height:1.55}header{border-bottom:4px solid #168b8b;padding-bottom:12px}"
        ".brand{font-size:29px;font-weight:bold}.brand span{color:#168b8b}"
        ".warning{padding:10px;background:#fff2dc;border:1px solid #b66c00;"
        "font-weight:bold;color:#744700}h1{font-size:25px}h2{font-size:15px;"
        "break-after:avoid;margin-top:22px}table{width:100%;border-collapse:collapse;"
        "font-size:11px}td,th{text-align:left;padding:7px;border-bottom:1px solid #d8e3eb}"
        "th{width:42%}tr{break-inside:avoid}.signature{border-top:1px solid #abbcc8;"
        "padding-top:15px}footer{margin-top:22px;color:#526476;font-size:10px}"
        '</style></head><body><header><div class="brand">Innex<span>Q</span></div>'
        "<div>Contoso Engineering Services | Synthetic equipment-service portfolio</div>"
        f'</header><p class="warning">{escape(document.disclosure)}</p>'
        f"<h1>{titles[document.kind]}</h1><table>{table_rows}</table>{detail}"
        f"<footer>Dataset {escape(catalog.dataset_id)} | As of {catalog.as_of.isoformat()} "
        "| Seed document only; not an authorized customer delivery.</footer></body></html>"
    )

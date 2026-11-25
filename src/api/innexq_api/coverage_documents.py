"""Deterministic Service Coverage Certificate and synthetic invoice rendering (ADR-018 D4).

Identical inputs must produce identical bytes and SHA-256. Only the guarded
executor calls these functions with an approved package; agents never render.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from fpdf import FPDF
from innexq_contracts.coverage_renewal import (
    SYNTHETIC_INVOICE_NOTICE,
    InvoicePreview,
    PreviousDocumentRef,
    RenewalQuote,
)

CERTIFICATE_TEMPLATE_VERSION = "coverage-cert-v1"
INVOICE_TEMPLATE_VERSION = "coverage-invoice-v1"
_SYNTHETIC_MARK = "SYNTHETIC DEMO DOCUMENT - FICTIONAL BUSINESS DATA"
_COVERAGE_STATEMENT = (
    "This document records commercial service coverage managed by the supplier. "
    "It is not an inspection, safety, regulatory or manufacturer certificate."
)


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _document(created: datetime, title: str) -> FPDF:
    if created.tzinfo is None:
        raise ValueError("document timestamps must be timezone-aware")
    pdf = FPDF(format="A4")
    # Fixed metadata keeps rendering reproducible byte-for-byte (ADR-018 D4).
    pdf.set_creation_date(created.astimezone(UTC))
    pdf.set_title(title)
    pdf.set_producer("InnexQ deterministic renderer")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    return pdf


def _heading(pdf: FPDF, text: str) -> None:
    pdf.set_font("helvetica", style="B", size=16)
    pdf.cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", style="B", size=9)
    pdf.set_text_color(180, 30, 30)
    pdf.cell(0, 6, _SYNTHETIC_MARK, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)


def _row(pdf: FPDF, label: str, value: str) -> None:
    pdf.set_font("helvetica", style="B", size=10)
    pdf.cell(62, 7, label)
    pdf.set_font("helvetica", size=10)
    pdf.cell(0, 7, value, new_x="LMARGIN", new_y="NEXT")


def render_coverage_certificate(
    *,
    document_id: str,
    customer_id: str,
    customer_name: str,
    equipment_id: str,
    serial_number: str,
    equipment_model: str,
    coverage_start: date,
    coverage_end: date,
    issued_at: datetime,
    policy_version: int,
    previous_document: PreviousDocumentRef,
) -> bytes:
    """Render a renewed Service Coverage Certificate; every field is spec-mandated."""

    pdf = _document(issued_at, f"Service Coverage Certificate {document_id}")
    _heading(pdf, "Service Coverage Certificate")
    _row(pdf, "Document ID", document_id)
    _row(pdf, "Customer", f"{customer_name} ({customer_id})")
    _row(pdf, "Equipment", equipment_id)
    _row(pdf, "Serial number", serial_number)
    _row(pdf, "Model", equipment_model)
    _row(pdf, "Coverage start", coverage_start.isoformat())
    _row(pdf, "Coverage end", coverage_end.isoformat())
    _row(pdf, "Issued at", issued_at.astimezone(UTC).isoformat())
    _row(pdf, "Renewal policy version", str(policy_version))
    _row(pdf, "Certificate template", CERTIFICATE_TEMPLATE_VERSION)
    _row(
        pdf,
        "Replaces document",
        f"{previous_document.document_id} v{previous_document.document_version} "
        f"(sha256 {previous_document.sha256[:16]}...)",
    )
    pdf.ln(4)
    pdf.set_font("helvetica", size=9)
    pdf.multi_cell(0, 5, _COVERAGE_STATEMENT)
    return bytes(pdf.output())


def render_invoice(
    *,
    invoice_number: str,
    customer_id: str,
    customer_name: str,
    equipment_id: str,
    quote: RenewalQuote,
    preview: InvoicePreview,
    issued_at: datetime,
) -> bytes:
    """Render the synthetic invoice with deterministic line items and the mandatory notice."""

    pdf = _document(issued_at, f"Synthetic invoice {invoice_number}")
    _heading(pdf, "Invoice (synthetic)")
    _row(pdf, "Invoice number", invoice_number)
    _row(pdf, "Customer", f"{customer_name} ({customer_id})")
    _row(pdf, "Equipment", equipment_id)
    _row(pdf, "Issued at", issued_at.astimezone(UTC).isoformat())
    _row(pdf, "Pricing rule", f"{quote.pricing_rule_id} {quote.pricing_rule_version}")
    _row(pdf, "Invoice template", INVOICE_TEMPLATE_VERSION)
    pdf.ln(3)
    pdf.set_font("helvetica", style="B", size=10)
    pdf.cell(96, 7, "Description")
    pdf.cell(16, 7, "Qty")
    pdf.cell(36, 7, "Unit")
    pdf.cell(0, 7, "Amount", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=10)
    for item in preview.line_items:
        pdf.cell(96, 7, item.description)
        pdf.cell(16, 7, str(item.quantity))
        pdf.cell(36, 7, f"{item.unit_amount} {preview.currency}")
        pdf.cell(0, 7, f"{item.line_amount} {preview.currency}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _row(pdf, "Subtotal", f"{preview.subtotal} {preview.currency}")
    _row(pdf, f"VAT {preview.vat_rate_percent}%", f"{preview.vat_amount} {preview.currency}")
    _row(pdf, "Total", f"{preview.total_amount} {preview.currency}")
    pdf.ln(4)
    pdf.set_font("helvetica", style="B", size=11)
    pdf.set_text_color(180, 30, 30)
    # Core PDF fonts are latin-1; the mandated notice renders with an ASCII dash.
    pdf.multi_cell(0, 6, SYNTHETIC_INVOICE_NOTICE.replace("\u2014", "-"))
    pdf.set_text_color(0, 0, 0)
    return bytes(pdf.output())

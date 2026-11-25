"""Deterministic PDF rendering tests for coverage certificates and synthetic invoices."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from innexq_api.coverage_documents import (
    render_coverage_certificate,
    render_invoice,
    sha256_hex,
)
from innexq_contracts.coverage_renewal import PreviousDocumentRef

from tests.unit.coverage_factories import invoice_preview, quote

ISSUED_AT = datetime(2026, 9, 22, 14, 30, tzinfo=UTC)
PREVIOUS = PreviousDocumentRef(document_id="DOC-COV-0001", document_version="1", sha256="a" * 64)


def certificate(document_id: str = "DOC-COV-0007") -> bytes:
    return render_coverage_certificate(
        document_id=document_id,
        customer_id="CUS-FABRIKAM-SE",
        customer_name="Fabrikam Industrial AB",
        equipment_id="COV-PT-001",
        serial_number="COV-SERIAL-0001",
        equipment_model="IC-3000 Industrial Compressor",
        coverage_start=date(2026, 9, 22),
        coverage_end=date(2027, 9, 22),
        issued_at=ISSUED_AT,
        policy_version=1,
        previous_document=PREVIOUS,
    )


def invoice(invoice_number: str = "SYN-INV-2026-00001") -> bytes:
    return render_invoice(
        invoice_number=invoice_number,
        customer_id="CUS-FABRIKAM-SE",
        customer_name="Fabrikam Industrial AB",
        equipment_id="COV-PT-001",
        quote=quote(),
        preview=invoice_preview(),
        issued_at=ISSUED_AT,
    )


def test_certificate_rendering_is_deterministic() -> None:
    first, second = certificate(), certificate()
    assert first.startswith(b"%PDF-")
    assert first == second
    assert sha256_hex(first) == sha256_hex(second)


def test_certificate_hash_changes_with_content() -> None:
    assert sha256_hex(certificate()) != sha256_hex(certificate(document_id="DOC-COV-0008"))


def test_invoice_rendering_is_deterministic() -> None:
    first, second = invoice(), invoice()
    assert first.startswith(b"%PDF-")
    assert first == second


def test_invoice_hash_changes_with_invoice_number() -> None:
    assert sha256_hex(invoice()) != sha256_hex(invoice("SYN-INV-2026-00002"))


def test_naive_timestamp_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        render_coverage_certificate(
            document_id="DOC-COV-0009",
            customer_id="CUS-FABRIKAM-SE",
            customer_name="Fabrikam Industrial AB",
            equipment_id="COV-PT-001",
            serial_number="COV-SERIAL-0001",
            equipment_model="IC-3000 Industrial Compressor",
            coverage_start=date(2026, 9, 22),
            coverage_end=date(2027, 9, 22),
            issued_at=datetime(2026, 9, 22, 14, 30),
            policy_version=1,
            previous_document=PREVIOUS,
        )

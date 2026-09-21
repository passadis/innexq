from datetime import date, timedelta

import pytest
from innexq_contracts.enterprise import EnterpriseDemoCatalog
from innexq_gateway.demo_catalog import build_demo_catalog
from innexq_gateway.demo_documents import render_demo_document
from pydantic import ValidationError

AS_OF = date(2026, 9, 10)


def test_seed_is_reproducible_bounded_connected_and_not_live_authority() -> None:
    catalog = build_demo_catalog(AS_OF)
    assert catalog == build_demo_catalog(AS_OF)
    assert (len(catalog.customers), len(catalog.contracts), len(catalog.equipment)) == (3, 6, 10)
    assert (len(catalog.documents), len(catalog.presets)) == (25, 10)
    assert len({item.filename for item in catalog.documents}) == 25
    assert EnterpriseDemoCatalog.model_validate_json(catalog.model_dump_json()) == catalog
    assert "CON-FAB-2025-001" not in catalog.model_dump_json()
    for preset in catalog.presets:
        assert "outcome" not in preset.model_dump()
        assert "approval" not in preset.model_dump()
    assert build_demo_catalog(AS_OF + timedelta(days=1)).as_of != catalog.as_of


def test_deliberate_source_gaps_survive_seed_validation_without_becoming_authority() -> None:
    catalog = build_demo_catalog(AS_OF)
    machines = {item.equipment_id: item for item in catalog.equipment}
    documents = {item.document_id: item for item in catalog.documents}
    assert machines["DEMO-PT-002"].service_valid_until < AS_OF
    assert machines["DEMO-PT-003"].certificate_document_id is None
    conflict = machines["DEMO-PT-004"]
    assert (
        documents[conflict.certificate_document_id].recorded_serial_number != conflict.serial_number
    )
    assert documents["DEMO-PT-005-CERT"].valid_until < AS_OF
    assert documents["DEMO-PT-001-CERT"].valid_until > AS_OF


@pytest.mark.parametrize("collection", ["customers", "contracts", "equipment", "presets"])
def test_catalogue_size_limits(collection: str) -> None:
    payload = build_demo_catalog(AS_OF).model_dump(mode="json")
    payload[collection].append(payload[collection][0])
    with pytest.raises(ValidationError):
        EnterpriseDemoCatalog.model_validate(payload)


@pytest.mark.parametrize(
    ("collection", "field"),
    [
        ("customers", "customer_id"),
        ("contracts", "contract_id"),
        ("equipment", "equipment_id"),
        ("equipment", "serial_number"),
        ("documents", "document_id"),
        ("sales", "entry_id"),
        ("presets", "preset_id"),
    ],
)
def test_duplicate_identifiers(collection: str, field: str) -> None:
    payload = build_demo_catalog(AS_OF).model_dump(mode="json")
    payload[collection][1][field] = payload[collection][0][field]
    if collection == "documents":
        payload[collection][1]["filename"] = payload[collection][0]["filename"]
    with pytest.raises(ValidationError, match="duplicate"):
        EnterpriseDemoCatalog.model_validate(payload)


@pytest.mark.parametrize(
    ("collection", "field", "value", "message"),
    [
        ("contracts", "customer_id", "DEMO-UNKNOWN", "unknown customer"),
        ("contracts", "document_id", "DEMO-UNKNOWN", "document relationship"),
        ("contracts", "expires_on", "2000-01-01", "expiry must follow"),
        ("equipment", "customer_id", "DEMO-NW", "equipment ownership"),
        ("equipment", "contract_id", "DEMO-UNKNOWN", "equipment ownership"),
        ("equipment", "service_document_id", "DEMO-PT-001-CERT", "document relationship"),
        ("equipment", "certificate_document_id", "DEMO-PT-002-CERT", "document relationship"),
        ("documents", "customer_id", "DEMO-NW", "document ownership"),
        ("documents", "filename", "../other.pdf", "pattern"),
        ("documents", "filename", "DEMO-WRONG.pdf", "filename must match"),
        ("documents", "valid_until", "2000-01-01", "validity must not precede"),
        ("documents", "equipment_id", "DEMO-PT-001", "require equipment"),
        ("documents", "recorded_serial_number", "DEMO-SERIAL-0001", "require serial"),
        ("sales", "customer_id", "DEMO-UNKNOWN", "sales customer"),
        ("sales", "net_amount", "NaN", "pattern"),
        ("presets", "customer_id", "DEMO-NW", "preset ownership"),
        ("presets", "equipment_id", "DEMO-UNKNOWN", "preset ownership"),
        ("presets", "contract_id", "DEMO-FAB-CON-1", "exactly the target"),
    ],
)
def test_invalid_relationships_and_source_fields(
    collection: str, field: str, value: str, message: str
) -> None:
    payload = build_demo_catalog(AS_OF).model_dump(mode="json")
    payload[collection][0][field] = value
    with pytest.raises(ValidationError, match=message):
        EnterpriseDemoCatalog.model_validate(payload)


def test_orphan_equipment_document_rejected() -> None:
    payload = build_demo_catalog(AS_OF).model_dump(mode="json")
    extra = dict(payload["documents"][-1])
    extra.update(document_id="DEMO-ORPHAN", filename="DEMO-ORPHAN.pdf", equipment_id="DEMO-UNKNOWN")
    payload["documents"].append(extra)
    with pytest.raises(ValidationError, match="document equipment"):
        EnterpriseDemoCatalog.model_validate(payload)


def test_all_document_templates_disclose_synthetic_origin_and_no_active_resources() -> None:
    catalog = build_demo_catalog(AS_OF)
    for document in catalog.documents:
        html = render_demo_document(catalog, document)
        assert document.disclosure in html
        assert document.document_id in html
        assert document.valid_until.isoformat() in html
        assert "<script" not in html and "<img" not in html and "href=" not in html
        assert "Content-Security-Policy" in html
        if document.kind == "contract":
            assert "NOT SIGNED" in html
        else:
            assert document.recorded_serial_number in html


def test_document_renderer_escapes_dynamic_text_and_rejects_foreign_record() -> None:
    catalog = build_demo_catalog(AS_OF)
    payload = catalog.model_dump(mode="json")
    payload["customers"][0]["name"] = '<script>alert("x")</script>'
    hostile = EnterpriseDemoCatalog.model_validate(payload)
    html = render_demo_document(hostile, hostile.documents[0])
    assert "&lt;script&gt;" in html and "<script>" not in html
    foreign = catalog.documents[0].model_copy(update={"document_id": "DEMO-FOREIGN"})
    with pytest.raises(ValueError, match="belong"):
        render_demo_document(catalog, foreign)


def test_seed_cannot_claim_non_synthetic_or_authorization() -> None:
    payload = build_demo_catalog(AS_OF).model_dump(mode="json")
    payload["synthetic"] = False
    with pytest.raises(ValidationError):
        EnterpriseDemoCatalog.model_validate(payload)
    payload["synthetic"] = True
    payload["approved"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        EnterpriseDemoCatalog.model_validate(payload)

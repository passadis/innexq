"""Tool activity must not alter pre-ADR-017 serialized authorization evidence."""

import hashlib
import json
from uuid import UUID

from innexq_api.certificates import decision_hash
from innexq_contracts.certificates import CertificateInvestigation, CertificateRequestRecord

from tests.unit.test_certificate_runtime import ACTOR, TENANT, body, system


def test_legacy_investigation_serialization_has_exact_original_keys():
    legacy = {
        "request_id": str(UUID(int=18)),
        "extraction_api": "2024-11-30",
        "extraction_model": "prebuilt-layout",
        "fields": [],
        "specialists": [],
    }
    investigation = CertificateInvestigation.model_validate(legacy)
    assert investigation.tool_activity == ()
    assert investigation.model_dump(mode="json") == legacy
    assert json.loads(investigation.model_dump_json()) == legacy
    explicit_empty = CertificateInvestigation.model_validate({**legacy, "tool_activity": []})
    assert explicit_empty.model_dump(mode="json") == legacy


def test_legacy_nested_decision_hash_and_reload_remain_byte_compatible():
    app, _, _, _, store = system()
    request = body()
    app.request(TENANT, ACTOR, request)
    record = store.get(request.request_id)
    wire = record.model_dump(mode="json")
    old_decision = wire["decision"]
    old_investigation = old_decision["sources"]["investigation"]
    assert set(old_investigation) == {
        "request_id",
        "extraction_api",
        "extraction_model",
        "fields",
        "specialists",
    }
    # Reconstruct the pre-change envelope without the new model or hash helper.
    old_envelope = {
        "request_id": str(record.request_id),
        "tenant_id": str(record.tenant_id),
        "actor_id": str(record.actor_user_id),
        "customer_id": record.customer_id,
        "equipment_id": record.equipment_id,
        "decision": old_decision,
    }
    old_bytes = json.dumps(
        old_envelope, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    old_hash = hashlib.sha256(old_bytes).hexdigest()
    assert record.decision_hash == old_hash
    reloaded = CertificateRequestRecord.model_validate_json(json.dumps(wire))
    assert reloaded.model_dump(mode="json") == wire
    assert (
        decision_hash(
            reloaded.request_id,
            reloaded.tenant_id,
            reloaded.actor_user_id,
            reloaded.customer_id,
            reloaded.equipment_id,
            reloaded.decision,
        )
        == old_hash
    )
    # Exercise the existing controller's stored-hash validation and release path.
    assert app.download(TENANT, ACTOR, request.request_id).startswith(b"%PDF-")

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from innexq_api.evidence_broker import (
    ROLES,
    EvidenceBinding,
    EvidenceBroker,
    EvidenceDenied,
    EvidenceStore,
)
from innexq_api.store import Conflict
from pydantic import SecretStr

from tests.unit.test_certificate_store import Container
from tests.unit.test_certificates import NOW, TENANT

AGENT = UUID(int=500)
DOCUMENT = "DEMO-PT-001-CERTIFICATE-PDF"


class Backend:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False

    def read(
        self, binding: EvidenceBinding, name: str, arguments: dict[str, str]
    ) -> dict[str, Any]:
        self.calls.append(name)
        if self.fail:
            raise RuntimeError("PRIVATE SOURCE")
        return {"source_version": binding.source_version, "evidence": "test evidence"}


def setup() -> tuple[EvidenceBroker, EvidenceBinding, Container, Backend, dict[str, SecretStr]]:
    container, backend = Container(), Backend()
    broker = EvidenceBroker(EvidenceStore(container), backend, now=lambda: NOW)
    binding = EvidenceBinding(
        request_id=uuid4(),
        workflow_request_id=uuid4(),
        tenant_id=TENANT,
        agent_principal_id=AGENT,
        customer_id="DEMO-FAB",
        equipment_id="DEMO-PT-001",
        source_version="registry-v1",
        policy_sha256="b" * 64,
        document_hashes={DOCUMENT: "a" * 64},
        expires_at=NOW + timedelta(minutes=5),
    )
    handles = broker.issue(binding)
    return broker, binding, container, backend, dict(handles)


def test_scopes_are_hashed_isolated_and_cannot_be_reissued() -> None:
    broker, binding, container, _, handles = setup()
    assert len(container.items) == 2
    assert all(key[0] == f"evidence:{binding.request_id}" for key in container.items)
    assert all(handle.get_secret_value() not in str(container.items) for handle in handles.values())
    with pytest.raises(Conflict):
        broker.issue(binding)


def test_complete_receipts_close_scopes_atomically_and_cannot_replay() -> None:
    broker, binding, container, _, handles = setup()
    calls = {
        "document_analyst": [
            ("list_equipment_documents", {}),
            ("analyze_document", {"document_id": DOCUMENT}),
        ],
        "equipment_service": [
            ("get_equipment_record", {}),
            ("retrieve_policy", {"query": "release"}),
        ],
    }
    ids = {}
    for role in ROLES:
        ids[role] = [
            UUID(broker.call(TENANT, AGENT, handles[role], name, args)["receipt_id"])
            for name, args in calls[role]
        ]
    assert len(broker.finish(binding, ids)) == 4
    assert len(container.batches[-1]) == 2
    for role in ROLES:
        assert broker.store._read(binding.request_id, f"scope-{role}")["state"] == "closed"
    with pytest.raises(EvidenceDenied):
        broker.call(TENANT, AGENT, handles["document_analyst"], "list_equipment_documents", {})
    with pytest.raises(EvidenceDenied):
        broker.finish(binding, ids)


@pytest.mark.parametrize("attack", ["tenant", "principal", "handle", "unknown", "malformed"])
def test_untrusted_identity_or_handle_cannot_access_or_poison_scope(attack: str) -> None:
    broker, binding, _, backend, handles = setup()
    handle = handles["document_analyst"]
    if attack == "handle":
        handle = SecretStr(handle.get_secret_value()[:-1] + "!")
    elif attack == "unknown":
        handle = SecretStr(handle.get_secret_value().replace(binding.request_id.hex, uuid4().hex))
    elif attack == "malformed":
        handle = SecretStr("../../secret")
    with pytest.raises(EvidenceDenied, match=r"^Evidence tool failed; investigation must stop$"):
        broker.call(
            uuid4() if attack == "tenant" else TENANT,
            uuid4() if attack == "principal" else AGENT,
            handle,
            "list_equipment_documents",
            {},
        )
    assert not backend.calls
    assert broker.store._read(binding.request_id, "scope-document_analyst")["state"] == "active"


@pytest.mark.parametrize(
    "name,args",
    [
        ("send_email", {}),
        ("get_equipment_record", {}),
        ("analyze_document", {"document_id": "DEMO-FOREIGN"}),
        ("list_equipment_documents", {"customer_id": "DEMO-NW"}),
    ],
)
def test_authenticated_scope_abuse_latches_failure(name: str, args: dict[str, str]) -> None:
    broker, binding, _, backend, handles = setup()
    with pytest.raises(EvidenceDenied):
        broker.call(TENANT, AGENT, handles["document_analyst"], name, args)
    assert not backend.calls
    assert broker.store._read(binding.request_id, "scope-document_analyst")["state"] == "failed"


def test_failed_backend_never_retries_or_returns_a_receipt() -> None:
    broker, binding, container, backend, handles = setup()
    backend.fail = True
    for _ in range(2):
        with pytest.raises(EvidenceDenied):
            broker.call(TENANT, AGENT, handles["document_analyst"], "list_equipment_documents", {})
    assert len(backend.calls) == 1
    assert not any(key[1].startswith("receipt-") for key in container.items)
    assert broker.store._read(binding.request_id, "scope-document_analyst")["state"] == "failed"


def test_expiry_and_request_wide_budget_are_durable() -> None:
    broker, binding, _, backend, handles = setup()
    for _ in range(6):
        broker.call(TENANT, AGENT, handles["document_analyst"], "list_equipment_documents", {})
    restarted = EvidenceBroker(broker.store, backend, now=lambda: NOW)
    with pytest.raises(EvidenceDenied):
        restarted.call(TENANT, AGENT, handles["document_analyst"], "list_equipment_documents", {})
    restarted.now = lambda: binding.expires_at
    with pytest.raises(EvidenceDenied):
        restarted.call(TENANT, AGENT, handles["equipment_service"], "get_equipment_record", {})
    assert len(backend.calls) == 6


def test_partial_evidence_does_not_finalize() -> None:
    broker, binding, _, _, handles = setup()
    receipt = broker.call(
        TENANT, AGENT, handles["document_analyst"], "list_equipment_documents", {}
    )
    with pytest.raises(EvidenceDenied):
        broker.finish(
            binding, {"document_analyst": [UUID(receipt["receipt_id"])], "equipment_service": []}
        )


def test_failed_reservation_does_not_call_backend() -> None:
    broker, _, container, backend, handles = setup()
    container.fail_status = 412
    with pytest.raises(EvidenceDenied):
        broker.call(TENANT, AGENT, handles["document_analyst"], "list_equipment_documents", {})
    assert not backend.calls

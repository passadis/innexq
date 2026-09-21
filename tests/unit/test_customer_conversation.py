"""Offline doubles validate boundaries; these tests do not claim live model quality."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError
from innexq_api.certificate_store import MESSAGE, SNAPSHOT, CosmosCertificateStore
from innexq_api.certificates import EvidenceUnavailable
from innexq_api.controller import Denied
from innexq_api.customer_routes import CustomerRequest
from innexq_api.store import Conflict
from innexq_contracts.customer_conversation import (
    CustomerInterpretation,
    CustomerMessage,
    CustomerMessageRecord,
    CustomerReply,
)
from pydantic import ValidationError

from tests.unit.test_certificate_runtime import ACTOR, NOW, OTHER, TENANT, system
from tests.unit.test_certificate_store import Container
from tests.unit.test_customer_routes import setup


def conversation(intent: str = "certificate_request", equipment: str | None = "DEMO-PT-001"):
    app, repo, extractor, team, _ = system()
    container = Container()
    store = CosmosCertificateStore(container)
    app.store = store
    packets: list[dict[str, Any]] = []

    def interpret(packet):
        packets.append(packet)
        return CustomerInterpretation(
            request_id=packet["request_id"], intent=intent, equipment_id=equipment
        ), "unit-interpretation-response"

    team.interpret = interpret
    return app, repo, extractor, team, store, container, packets


def message(prompt: str = "Provide certificate for PT-001", **kwargs):
    return CustomerMessage(message_id=uuid4(), prompt=prompt, **kwargs)


def test_certificate_requires_explicit_confirmation_and_preserves_customer_words():
    app, _, extractor, team, store, container, packets = conversation()
    body = message("Provice Certificate for PT-001")
    reply = app.message(TENANT, ACTOR, body)
    assert reply.kind == "confirmation_required" and reply.can_confirm
    assert extractor.calls == [] and team.packets == []
    assert all(key[1] == MESSAGE for key in container.items)
    assert set(packets[0]["equipment_ids"]) == {
        "DEMO-PT-001",
        "DEMO-PT-002",
        "DEMO-PT-003",
        "DEMO-PT-004",
    }
    assert app.confirm(TENANT, ACTOR, body.message_id)["status"] == "release_ready"
    record = store.get(body.message_id)
    assert record.request_context.customer_messages == (body.prompt,)
    assert record.request_context.interpreter_response_id == "unit-interpretation-response"
    assert record.operations_case is None
    before = len(extractor.calls), len(team.packets), len(container.batches)
    assert app.confirm(TENANT, ACTOR, body.message_id)["status"] == "release_ready"
    assert before == (len(extractor.calls), len(team.packets), len(container.batches))
    app.download(TENANT, ACTOR, body.message_id)
    assert store.get(body.message_id).request_context == record.request_context


@pytest.mark.parametrize("equipment", ["DEMO-PT-002", "DEMO-PT-003", "DEMO-PT-004"])
def test_confirmed_failures_hold_and_never_override_release_policy(equipment):
    app, _, _, _, store, _, _ = conversation(equipment=equipment)
    body = message(f"Provide certificate for {equipment}")
    assert app.message(TENANT, ACTOR, body).can_confirm
    assert app.confirm(TENANT, ACTOR, body.message_id)["status"] == "operations_required"
    assert store.get(body.message_id).operations_case is not None
    with pytest.raises(Denied):
        app.download(TENANT, ACTOR, body.message_id)


@pytest.mark.parametrize(
    "equipment,current",
    [
        ("DEMO-PT-001", True),
        ("DEMO-PT-002", False),
        ("DEMO-PT-003", True),
    ],
)
def test_service_question_reads_service_only_even_when_certificate_is_missing(equipment, current):
    app, _, extractor, team, _, container, _ = conversation("service_status", equipment)
    body = message(f"Is the service for {equipment} updated?")
    result = app.message(TENANT, ACTOR, body)
    assert result.kind == "answer" and not result.can_confirm
    assert ("service is current" if current else "service is not current") in result.message
    assert len(extractor.calls) == 1 and "SERVICE" in extractor.calls[0]
    assert team.packets[0]["intent"] == "service_status"
    assert result.as_of == NOW and result.citations
    assert all(key[1] == MESSAGE for key in container.items)
    with pytest.raises(Denied):
        app.confirm(TENANT, ACTOR, body.message_id)


def test_certificate_question_does_not_release_pdf_or_open_case():
    app, _, _, _, _, container, _ = conversation("certificate_status")
    result = app.message(TENANT, ACTOR, message("Is certificate PT-001 valid?"))
    assert result.kind == "answer" and "pass at this time" in result.message
    assert result.citations and result.as_of == NOW
    assert all(key[1] == MESSAGE for key in container.items)


@pytest.mark.parametrize("failure", ["ocr", "team", "changed", "stale", "unknown-service"])
def test_unverifiable_service_is_unknown_and_does_not_create_a_case(failure):
    app, repo, extractor, team, _, container, _ = conversation("service_status")
    if failure == "ocr":
        extractor.mismatch = True
    elif failure == "team":
        team.failure = True
    elif failure == "changed":
        original = team.investigate

        def change_during_investigation(packet):
            result = original(packet)
            repo.change_version = True
            return result

        team.investigate = change_during_investigation
    elif failure == "unknown-service":
        repo.value = repo.value.model_copy(update={"in_service": {}})
    else:
        app.now = lambda: NOW + timedelta(minutes=6)
    reply = app.message(TENANT, ACTOR, message("Is service for PT-001 current?"))
    assert "could not verify" in reply.message
    assert reply.as_of is None and not reply.citations
    assert all(key[1] == MESSAGE for key in container.items)


@pytest.mark.parametrize(
    "intent,kind",
    [("service_request", "unsupported"), ("general", "answer"), ("clarify", "clarification")],
)
def test_non_workflow_messages_do_not_investigate_or_request(intent, kind):
    app, _, extractor, team, _, container, _ = conversation(intent, None)
    reply = app.message(TENANT, ACTOR, message("Tell me what you can do"))
    assert reply.kind == kind and not reply.can_confirm
    assert not extractor.calls and not team.packets
    assert all(key[1] == MESSAGE for key in container.items)


def test_missing_equipment_asks_followup_then_preserves_both_messages():
    app, _, _, team, store, _, _ = conversation(equipment=None)
    first = message("I need my certificate")
    assert app.message(TENANT, ACTOR, first).kind == "clarification"

    def interpret(packet):
        assert packet["messages"] == [first.prompt, "PT-001 please"]
        return CustomerInterpretation(
            request_id=packet["request_id"],
            intent="certificate_request",
            equipment_id="DEMO-PT-001",
        ), "unit-next"

    team.interpret = interpret
    second = message("PT-001 please", parent_message_id=first.message_id)
    assert app.message(TENANT, ACTOR, second).can_confirm
    app.confirm(TENANT, ACTOR, second.message_id)
    assert store.get(second.message_id).request_context.customer_messages == (
        first.prompt,
        second.prompt,
    )


@pytest.mark.parametrize(
    "text,selected",
    [
        ("Give me PT-001 and PT-002 certificates", None),
        ("Give me PT-999 certificate", None),
        ("Give me PT-002 certificate", "DEMO-PT-001"),
        ("Give me PT-001 certificate", "DEMO-PT-002"),
    ],
)
def test_explicit_machine_disagreement_never_silently_changes_target(text, selected):
    app, _, extractor, _, _, _, _ = conversation()
    result = app.message(TENANT, ACTOR, message(text, equipment_id=selected))
    assert result.kind == "clarification" and result.equipment_id is None
    assert not extractor.calls


@pytest.mark.parametrize("tenant,actor", [(uuid4(), ACTOR), (TENANT, uuid4())])
def test_identity_denied_before_registry_or_model(tenant, actor):
    app, repo, _, _, _, _, packets = conversation()
    with pytest.raises(Denied):
        app.message(tenant, actor, message())
    assert repo.registry_reads == 0 and packets == []


def test_cross_customer_parent_replay_confirm_and_selected_equipment_are_denied():
    app, _, _, _, _, _, _ = conversation()
    body = message()
    app.message(TENANT, ACTOR, body)
    for action in [
        lambda: app.message(TENANT, OTHER, body),
        lambda: app.message(TENANT, OTHER, message(parent_message_id=body.message_id)),
        lambda: app.confirm(TENANT, OTHER, body.message_id),
        lambda: app.message(TENANT, ACTOR, message(equipment_id="DEMO-PT-005")),
    ]:
        with pytest.raises(Denied):
            action()


def test_model_cannot_select_foreign_equipment_or_substitute_request_id():
    app, _, _, team, _, container, _ = conversation(equipment="DEMO-PT-005")
    with pytest.raises(EvidenceUnavailable):
        app.message(TENANT, ACTOR, message())
    team.interpret = lambda _: (
        CustomerInterpretation(
            request_id=uuid4(), intent="certificate_request", equipment_id="DEMO-PT-001"
        ),
        "unit-wrong-request",
    )
    with pytest.raises(EvidenceUnavailable):
        app.message(TENANT, ACTOR, message())
    assert not container.items


def test_message_id_replay_is_identical_and_changed_payload_conflicts():
    app, _, _, _, _, _, packets = conversation()
    body = message()
    first = app.message(TENANT, ACTOR, body)
    assert app.message(TENANT, ACTOR, body) == first
    assert len(packets) == 1
    with pytest.raises(Conflict):
        app.message(TENANT, ACTOR, body.model_copy(update={"prompt": "Changed"}))


def test_expired_confirmation_and_overlong_conversation_are_rejected():
    app, _, _, _, _, _, _ = conversation()
    body = message()
    app.message(TENANT, ACTOR, body)
    app.now = lambda: NOW + timedelta(minutes=15)
    with pytest.raises(Conflict):
        app.confirm(TENANT, ACTOR, body.message_id)
    with pytest.raises(Conflict):
        app.message(TENANT, ACTOR, message(parent_message_id=body.message_id))
    app.now = lambda: NOW
    parent = body.message_id
    for _ in range(5):
        turn = message(parent_message_id=parent)
        app.message(TENANT, ACTOR, turn)
        parent = turn.message_id
    with pytest.raises(Conflict):
        app.message(TENANT, ACTOR, message(parent_message_id=parent))


def test_confirmation_retry_after_expiry_is_existing_request_not_new_work():
    app, _, extractor, _, _, _, _ = conversation()
    body = message()
    app.message(TENANT, ACTOR, body)
    first = app.confirm(TENANT, ACTOR, body.message_id)
    app.now = lambda: NOW + timedelta(hours=1)
    assert app.confirm(TENANT, ACTOR, body.message_id) == first and len(extractor.calls) == 2


def test_store_failure_blocks_confirmation_and_never_acknowledges_a_message():
    app, _, _, _, store, container, _ = conversation()
    body = message()
    container.fail_status = 503
    with pytest.raises(CosmosHttpResponseError):
        app.message(TENANT, ACTOR, body)
    assert not container.items
    with pytest.raises(KeyError):
        store.get_message(body.message_id)
    with pytest.raises(KeyError):
        app.confirm(TENANT, ACTOR, body.message_id)


def test_message_cannot_reuse_existing_legacy_request_identifier():
    app, _, _, _, _, _, _ = conversation()
    body = message()
    app.request(
        TENANT,
        ACTOR,
        CustomerRequest(
            request_id=body.message_id, equipment_id="DEMO-PT-001", prompt="My certificate"
        ),
    )
    with pytest.raises(Conflict):
        app.message(TENANT, ACTOR, body)


def test_immutable_context_cannot_change_during_download_commit():
    app, _, _, _, store, _, _ = conversation()
    body = message()
    app.message(TENANT, ACTOR, body)
    app.confirm(TENANT, ACTOR, body.message_id)
    record = store.get(body.message_id)
    from innexq_contracts.certificates import CertificateAuditEvent

    changed = record.model_copy(
        update={
            "request_context": record.request_context.model_copy(
                update={"customer_messages": ("altered",)}
            ),
            "events": (
                *record.events,
                CertificateAuditEvent(
                    sequence=len(record.events) + 1,
                    event_type="certificate.download_prepared",
                    occurred_at=NOW,
                ),
            ),
        }
    )
    with pytest.raises(Conflict):
        store.commit(changed, len(record.events))


def test_routes_return_typed_public_reply_and_confirmation_rejects_extra_fields():
    app, _, _, _, _, container, _ = conversation()
    client = setup(app)
    body = message()
    response = client.post("/messages", json=body.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "actor_user_id" not in response.text and "response_id" not in response.text
    assert (
        client.post(
            f"/messages/{body.message_id}/confirm", json={"equipment_id": "DEMO-PT-002"}
        ).status_code
        == 422
    )
    assert all(key[1] == MESSAGE for key in container.items)
    response = client.post(f"/messages/{body.message_id}/confirm", json={})
    assert response.status_code == 200 and response.json()["status"] == "release_ready"
    assert any(key[1] == SNAPSHOT for key in container.items)


@pytest.mark.parametrize("route", ["/messages", f"/messages/{uuid4()}/confirm"])
def test_conversation_routes_require_authentication(route):
    app, _, _, _, _, container, _ = conversation()
    response = setup(app, override_identity=False).post(route, json={})
    assert response.status_code == 401 and not container.items


def test_customer_contract_forbids_fabricated_authority_and_oversized_context():
    for change in [{"approved": True}, {"prompt": "x" * 1001}]:
        with pytest.raises(ValidationError):
            CustomerMessage.model_validate(message().model_dump() | change)
    with pytest.raises(ValidationError):
        CustomerReply(
            message_id=uuid4(),
            intent="service_status",
            equipment_id="DEMO-PT-001",
            kind="confirmation_required",
            message="Not allowed",
            can_confirm=True,
        )


def test_message_store_detects_cross_partition_identity_and_invalid_record():
    app, _, _, _, store, container, _ = conversation()
    body = message()
    app.message(TENANT, ACTOR, body)
    record = store.get_message(body.message_id)
    with pytest.raises(ValidationError):
        CustomerMessageRecord.model_validate(record.model_dump() | {"customer_messages": ["wrong"]})
    entry = container.items[f"certificate:{body.message_id}", MESSAGE]
    entry["record"]["input"]["message_id"] = str(UUID(int=1))
    entry["record"]["reply"]["message_id"] = str(UUID(int=1))
    with pytest.raises(Conflict):
        store.get_message(body.message_id)

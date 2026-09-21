"""Notification delivery never confers approval or guesses at an unknown send outcome."""

import asyncio
import json
import logging
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from innexq_api.certificate_notifications import CertificateNotifications
from innexq_api.config import Settings
from innexq_api.controller import Denied
from innexq_api.store import Conflict
from innexq_api.teams import TeamsApprovals
from innexq_contracts.certificates import CertificateSources

from tests.unit.test_certificate_store import setup
from tests.unit.test_certificates import CUSTOMER, NOW, OPERATIONS, REQUEST, TENANT
from tests.unit.test_teams import reference


def worker():
    controller, evidence, store, container = setup()
    evidence.value = CertificateSources()
    record = controller.request(TENANT, CUSTOMER, "DEMO-PT-001", REQUEST)
    sender = SimpleNamespace(notify_operations=AsyncMock(return_value="teams-receipt"))
    instance = CertificateNotifications(store, sender, TENANT, OPERATIONS, lambda: NOW)
    return instance, sender.notify_operations, store, container, record


def test_notification_success_persists_receipt_and_never_resends() -> None:
    instance, send, store, _, record = worker()
    asyncio.run(instance.dispatch_once())
    send.assert_awaited_once_with(REQUEST, record.operations_case.case_id)
    notification = store.get_notification(REQUEST)
    assert notification.state == "delivered" and notification.receipt_id == "teams-receipt"
    asyncio.run(instance.dispatch_once())
    assert send.await_count == 1
    assert store.get(REQUEST) == record  # notification does not mutate policy or approval


@pytest.mark.parametrize("failure", ["timeout", "send_error", "empty_receipt", "receipt_persist"])
def test_unknown_send_outcome_is_ambiguous_and_never_automatically_retried(
    failure, monkeypatch, caplog
) -> None:
    instance, send, store, _, _ = worker()
    if failure == "timeout":
        send.side_effect = TimeoutError("private send failure")
    elif failure == "send_error":
        send.side_effect = RuntimeError("private send failure")
    elif failure == "empty_receipt":
        send.return_value = ""
    else:
        monkeypatch.setattr(store, "mark_delivered", MagicMock(side_effect=RuntimeError("private")))
    with caplog.at_level(logging.WARNING, logger="innexq.audit"):
        asyncio.run(instance.dispatch_once())
    assert store.get_notification(REQUEST).state == "ambiguous"
    asyncio.run(instance.dispatch_once())
    assert send.await_count == 1
    entries = [entry for entry in caplog.records if entry.name == "innexq.audit"]
    assert entries[-1].msg == "certificate_notification_ambiguous"
    assert entries[-1].exc_info is None and entries[-1].args == ()
    assert "private" not in repr(entries[-1].__dict__)


def test_crashed_worker_claim_requires_attention_not_another_send() -> None:
    instance, send, store, _, _ = worker()
    store.claim_notification(REQUEST, NOW)
    instance.now = lambda: NOW + timedelta(minutes=6)
    asyncio.run(instance.dispatch_once())
    assert store.get_notification(REQUEST).state == "ambiguous"
    send.assert_not_awaited()


@pytest.mark.parametrize("identity", ["tenant", "operations"])
def test_stale_foreign_authority_claim_is_not_mutated(identity) -> None:
    instance, send, store, _, _ = worker()
    store.claim_notification(REQUEST, NOW)
    instance.now = lambda: NOW + timedelta(minutes=6)
    if identity == "tenant":
        instance.tenant_id = UUID(int=999)
    else:
        instance.operations_id = UUID(int=999)
    asyncio.run(instance.dispatch_once())
    assert store.get_notification(REQUEST).state == "claimed"
    send.assert_not_awaited()


@pytest.mark.parametrize("identity", ["tenant", "operations"])
def test_pending_foreign_authority_context_is_not_claimed_or_sent(identity) -> None:
    instance, send, store, _, _ = worker()
    if identity == "tenant":
        instance.tenant_id = UUID(int=999)
    else:
        instance.operations_id = UUID(int=999)
    asyncio.run(instance.dispatch_once())
    assert store.get_notification(REQUEST).state == "pending"
    send.assert_not_awaited()


@pytest.mark.parametrize("result", ["conflict", "already_claimed", "invalid_claim"])
def test_lost_claim_is_never_sent(result, monkeypatch) -> None:
    instance, send, store, _, _ = worker()
    if result == "conflict":
        claim = MagicMock(side_effect=Conflict("lost claim"))
    elif result == "already_claimed":
        claim = MagicMock(return_value=None)
    else:
        claim = MagicMock(return_value=store.get_notification(REQUEST))
    monkeypatch.setattr(store, "claim_notification", claim)
    asyncio.run(instance.dispatch_once())
    send.assert_not_awaited()


@pytest.mark.parametrize("condition", ["missing_case", "case_id", "operations", "tenant"])
def test_case_binding_mismatch_stops_before_send(condition, monkeypatch) -> None:
    instance, send, store, _, record = worker()
    case = record.operations_case
    if condition == "missing_case":
        altered = record.model_copy(update={"operations_case": None})
    elif condition == "tenant":
        altered = record.model_copy(update={"tenant_id": UUID(int=999)})
    else:
        field = "case_id" if condition == "case_id" else "assigned_user_id"
        altered = record.model_copy(
            update={"operations_case": case.model_copy(update={field: UUID(int=999)})}
        )
    monkeypatch.setattr(store, "get", MagicMock(return_value=altered))
    asyncio.run(instance.dispatch_once())
    send.assert_not_awaited()
    assert store.get_notification(REQUEST).state == "ambiguous"


@pytest.mark.parametrize("field", ["tenant_id", "assigned_user_id", "request_id"])
def test_authority_is_rechecked_after_atomic_claim(field, monkeypatch) -> None:
    instance, send, store, _, _ = worker()
    real_claim = store.claim_notification

    def corrupt_claim(request_id, now):
        return replace(real_claim(request_id, now), **{field: UUID(int=999)})

    monkeypatch.setattr(store, "claim_notification", corrupt_claim)
    # A corrupt request ID cannot be marked in a nonexistent partition; the
    # dispatcher raises to its outer worker and leaves the real claim untouched.
    if field == "request_id":
        with pytest.raises(KeyError):
            asyncio.run(instance.dispatch_once())
    else:
        asyncio.run(instance.dispatch_once())
        assert store.get_notification(REQUEST).state == "ambiguous"
    send.assert_not_awaited()


def test_ambiguous_reconciliation_does_not_overwrite_concurrent_receipt(monkeypatch) -> None:
    instance, send, store, _, _ = worker()
    send.side_effect = TimeoutError()
    monkeypatch.setattr(store, "mark_ambiguous", MagicMock(side_effect=Conflict("completed")))
    asyncio.run(instance.dispatch_once())
    assert send.await_count == 1
    # No automatic resend even if reconciliation itself did not complete.
    assert store.get_notification(REQUEST).state == "claimed"


def test_worker_logs_only_fixed_unavailable_status_and_remains_cancellable(monkeypatch, caplog):
    instance, _, _, _, _ = worker()
    instance.dispatch_once = AsyncMock(side_effect=RuntimeError("private database error"))
    monkeypatch.setattr(
        "innexq_api.certificate_notifications.asyncio.sleep",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    with caplog.at_level(logging.WARNING, logger="innexq.audit"):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(instance.run())
    assert caplog.records[-1].msg == "certificate_outbox_unavailable"
    assert caplog.records[-1].exc_info is None
    assert "private" not in repr(caplog.records[-1].__dict__)


def teams_bridge():
    settings = Settings(
        managed_identity_client_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        web_origins=["https://control.example.invalid"],
    )
    store = MagicMock()
    bridge = TeamsApprovals(settings, FastAPI(), store)
    bridge.save_reference(reference(settings))
    saved = store.save_teams_reference.call_args.args[0]
    store.save_teams_reference.reset_mock()
    store.get_teams_reference.return_value = saved
    bridge.app.activity_sender.send = AsyncMock(return_value=SimpleNamespace(id="teams-message"))
    return bridge, settings, saved


def test_live_operations_card_is_generic_read_only_and_returns_transport_receipt() -> None:
    bridge, _, _ = teams_bridge()
    case_id = UUID(int=80)
    assert asyncio.run(bridge.notify_operations(REQUEST, case_id)) == "teams-message"
    message, destination = bridge.app.activity_sender.send.call_args.args
    payload = message.model_dump(mode="json", by_alias=True, exclude_none=True)
    text = json.dumps(payload)
    assert "No PDF was released" in text and str(case_id) in text
    assert f"https://control.example.invalid/?operations={REQUEST}" in text
    assert "Action.OpenUrl" in text
    for forbidden in ("Action.Execute", "Action.Submit", "approve", "DEMO-FAB", "revoked"):
        assert forbidden not in text
    assert destination.service_url == "https://smba.trafficmanager.net/emea/"
    bridge.store.save_teams_reference.assert_not_called()  # validating is read-only


@pytest.mark.parametrize("condition", ["missing", "tenant", "team", "channel", "origin"])
def test_operations_notification_requires_registered_pinned_destination(condition) -> None:
    bridge, settings, saved = teams_bridge()
    if condition == "missing":
        bridge.store.get_teams_reference.return_value = None
    elif condition == "origin":
        settings.web_origins = []
    else:
        saved[f"{condition}_id"] = "another-context"
    with pytest.raises(Denied, match="channel required"):
        asyncio.run(bridge.notify_operations(REQUEST, UUID(int=80)))
    bridge.app.activity_sender.send.assert_not_awaited()


@pytest.mark.parametrize("condition", ["url", "conversation", "platform", "receipt"])
def test_operations_sender_revalidates_reference_and_requires_receipt(condition) -> None:
    bridge, _, saved = teams_bridge()
    if condition == "receipt":
        bridge.app.activity_sender.send.return_value.id = None
    elif condition == "url":
        saved["reference"]["serviceUrl"] = "https://evil.invalid"
    elif condition == "conversation":
        saved["reference"]["conversation"]["id"] = "19:another-channel"
    else:
        saved["reference"]["channelId"] = "emulator"
    with pytest.raises(Denied):
        asyncio.run(bridge.notify_operations(REQUEST, UUID(int=80)))
    if condition != "receipt":
        bridge.app.activity_sender.send.assert_not_awaited()

"""Result cards and SDK HTTP envelopes, with no live credentials or external writes."""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from innexq_api.config import Settings
from innexq_api.main import create_app
from innexq_api.teams import TeamsApprovals, status_card
from innexq_api.teams_http import TeamsResponseTelemetry
from innexq_contracts.models import RunState

from tests.unit.factories import approval
from tests.unit.test_teams import activity, record


@pytest.mark.parametrize("state", [RunState.EXECUTED, RunState.CLOSED_REJECTED])
def test_status_card_has_no_mutations_or_claim_of_delivery(state):
    current = record()
    key = current.envelope.action_manifest.actions[0].idempotency_key
    current = current.model_copy(
        update={
            "run": current.run.model_copy(update={"state": state}),
            "approval": approval(current.envelope),
            "action_status": {key: "completed"},
            "receipts": {key: "stored-receipt"},
        }
    )
    payload = status_card(current).model_dump(by_alias=True, exclude_none=True)
    text = json.dumps(payload)
    assert state.value in text and "stored-receipt" in text
    assert "not proof of recipient delivery" in text
    assert not payload.get("actions") and "Action.Execute" not in text
    assert "refresh" not in payload


def test_status_card_without_envelope_or_approval_does_not_invent_results():
    current = record().model_copy(update={"envelope": None})
    text = status_card(current).model_dump_json()
    assert "Recorded decision" not in text and "Receipt:" not in text


def test_sdk_processor_and_http_adapter_serialize_terminal_card(monkeypatch, caplog):
    settings = Settings(managed_identity_client_id="test-bot")
    api = FastAPI()
    api.add_middleware(TeamsResponseTelemetry)
    bridge = TeamsApprovals(settings, api, MagicMock())
    current = record()
    approved = current.model_copy(update={"approval": approval(current.envelope)})
    executed = approved.model_copy(
        update={"run": current.run.model_copy(update={"state": RunState.EXECUTED})}
    )
    controller = MagicMock()
    controller.decide.return_value = approved
    controller.execute = AsyncMock(return_value=executed)
    bridge.bind(controller)
    asyncio.run(bridge.initialize())
    raw = activity(settings)
    # Replace only JWT validation/parsing with an already validated test token.
    # The real SDK processor, handler, formatter and FastAPI adapter run.
    # The separate transport-auth tests retain missing/invalid JWT -> 401 coverage.
    monkeypatch.setattr(
        bridge.app.server._token_validator, "validate_token", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "microsoft_teams.apps.http.http_server.JsonWebToken", lambda **_: MagicMock()
    )
    with caplog.at_level(logging.INFO, logger="innexq.audit"):
        response = TestClient(bridge.app.server.adapter.app).post(
            "/api/messages", json=raw, headers={"Authorization": "Bearer offline-test"}
        )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"statusCode", "type", "value"}
    assert payload["statusCode"] == 200
    assert payload["type"] == "application/vnd.microsoft.card.adaptive"
    assert payload["value"]["type"] == "AdaptiveCard"
    assert "EXECUTED" in json.dumps(payload["value"])
    assert not payload["value"].get("actions")
    controller.execute.assert_awaited_once_with(current.run.run_id)
    logs = [r for r in caplog.records if r.name == "innexq.audit"]
    callback = next(r for r in logs if r.msg == "teams_callback_completed")
    http = next(r for r in logs if r.msg == "teams_http_response")
    assert callback.elapsed_ms >= 0 and callback.state == "EXECUTED"
    assert http.http_status == 200 and http.response_completed is True
    assert http.elapsed_ms >= callback.elapsed_ms
    assert "offline-test" not in repr([r.__dict__ for r in logs])


@pytest.mark.parametrize("fails", [False, True])
def test_http_observer_preserves_messages_and_records_incomplete_send(caplog, fails):
    messages = [
        {"type": "http.response.start", "status": 200, "headers": []},
        {"type": "http.response.body", "body": b"private-content", "more_body": True},
        {"type": "http.response.body", "body": b"", "more_body": False},
    ]

    async def app(scope, receive, send):
        for message in messages:
            await send(message)

    received = []

    async def send(message):
        received.append(message)
        if fails:
            raise RuntimeError("private-error")

    async def run():
        await TeamsResponseTelemetry(app)(
            {"type": "http", "method": "POST", "path": "/api/messages"}, AsyncMock(), send
        )

    with caplog.at_level(logging.INFO, logger="innexq.audit"):
        if fails:
            with pytest.raises(RuntimeError):
                asyncio.run(run())
        else:
            asyncio.run(run())
    log = caplog.records[-1]
    assert log.response_completed is (not fails)
    assert log.http_status == 200 and log.elapsed_ms >= 0
    assert log.exc_info is None and "private" not in repr(log.__dict__)
    assert received == (messages[:1] if fails else messages)


def test_non_teams_requests_pass_through_without_telemetry(caplog):
    app = AsyncMock()
    with caplog.at_level(logging.INFO, logger="innexq.audit"):
        asyncio.run(
            TeamsResponseTelemetry(app)(
                {"type": "http", "method": "GET", "path": "/health/live"},
                AsyncMock(),
                AsyncMock(),
            )
        )
    app.assert_awaited_once()
    assert not caplog.records


def test_runtime_startup_registers_teams_after_middleware_stack_is_built(monkeypatch, caplog):
    settings = Settings(
        managed_identity_client_id="test-bot", cosmos_endpoint="https://cosmos.example.invalid"
    )
    credential = MagicMock()
    monkeypatch.setattr("innexq_api.adapters.workload_credential", lambda _: credential)
    monkeypatch.setattr("innexq_api.telemetry.configure_telemetry", lambda _: None)
    monkeypatch.setattr("innexq_api.store.CosmosStore", MagicMock())
    monkeypatch.setattr("innexq_api.adapters.FoundryAgent", MagicMock())
    monkeypatch.setattr("innexq_api.adapters.GraphExecutor", MagicMock())
    with caplog.at_level(logging.INFO, logger="innexq.audit"):
        with TestClient(create_app(settings)) as client:
            assert client.get("/health/live").status_code == 200
            assert client.post("/api/messages", json=activity(settings)).status_code == 401
    credential.close.assert_called_once()
    log = next(r for r in caplog.records if r.msg == "teams_http_response")
    assert log.http_status == 401 and log.response_completed is True

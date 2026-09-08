"""SDK transport authentication and exact human/destination boundaries."""

import asyncio
import json
import struct
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from innexq_api.config import Settings
from innexq_api.controller import Denied
from innexq_api.teams import TeamsApprovals, approval_card
from innexq_contracts.events import RunRecord
from innexq_contracts.hashing import version_brief
from innexq_contracts.models import Run, RunState
from microsoft_teams.api import AdaptiveCardInvokeActivity, ConversationReference, MessageActivity

from scripts.package_teams import build_package, icon_png
from tests.unit.factories import RUN_ID, approval, brief, manifest


@pytest.fixture
def settings():
    return Settings(managed_identity_client_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


@pytest.fixture
def bridge(settings):
    store = MagicMock()
    store.get_teams_reference.return_value = None
    return TeamsApprovals(settings, FastAPI(), store)


def record():
    envelope = version_brief(brief(), manifest())
    now = datetime.now(UTC)
    return RunRecord(
        run=Run(
            run_id=RUN_ID,
            contract_id="synthetic",
            state=RunState.AWAITING_APPROVAL,
            created_at=now,
            updated_at=now,
            correlation_id=uuid4(),
            current_brief_version=1,
            current_brief_hash=envelope.brief_hash,
        ),
        revision=1,
        envelope=envelope,
    )


def activity(settings):
    return {
        "type": "invoke",
        "name": "adaptiveCard/action",
        "id": "activity-id",
        "channelId": "msteams",
        "serviceUrl": "https://smba.trafficmanager.net/emea/",
        "from": {"id": "29:person", "aadObjectId": settings.approver_user_id},
        "recipient": {"id": f"28:{settings.managed_identity_client_id}"},
        "conversation": {"id": settings.teams_channel_id, "conversationType": "channel"},
        "channelData": {
            "tenant": {"id": settings.tenant_id},
            "team": {"id": "19:team@thread.tacv2", "aadGroupId": settings.teams_team_id},
            "channel": {"id": settings.teams_channel_id},
        },
        "value": {
            "action": {
                "type": "Action.Execute",
                "verb": "approve",
                "data": {
                    "run_id": str(RUN_ID),
                    "brief_version": 1,
                    "brief_hash": record().envelope.brief_hash,
                },
            }
        },
    }


def reference(settings, **updates):
    return ConversationReference.model_validate(
        {
            "channelId": "msteams",
            "serviceUrl": "https://smba.trafficmanager.net/emea/",
            "bot": {"id": f"28:{settings.managed_identity_client_id}"},
            "conversation": {"id": settings.teams_channel_id},
            **updates,
        }
    )


def test_missing_identity_fails_closed():
    with pytest.raises(Denied):
        TeamsApprovals(Settings(managed_identity_client_id=""), FastAPI(), MagicMock())


def test_card_displays_complete_stored_brief_and_bound_actions():
    current = record()
    card = approval_card(current).model_dump(by_alias=True, exclude_none=True)
    text = json.dumps(card)
    assert current.envelope.brief_hash in text
    assert "customer@example.invalid" in text
    for action in current.envelope.action_manifest.actions:
        for value in action.parameters.values():
            assert str(value) in text
    assert {item["verb"] for item in card["actions"]} == {"approve", "reject"}
    assert all(item["data"]["brief_version"] == 1 for item in card["actions"])


def test_card_refuses_wrong_state_hash_absent_or_oversized():
    current = record()
    for invalid in [
        current.model_copy(update={"envelope": None}),
        current.model_copy(
            update={"run": current.run.model_copy(update={"state": RunState.DETECTED})}
        ),
        current.model_copy(
            update={"envelope": current.envelope.model_copy(update={"brief_hash": "0" * 64})}
        ),
    ]:
        with pytest.raises(Denied):
            approval_card(invalid)
    huge = brief("x" * 30_000)
    with pytest.raises(Denied, match="payload"):
        approval_card(current.model_copy(update={"envelope": version_brief(huge, manifest())}))


@pytest.mark.parametrize("field", ["tenant", "actor", "team", "channel", "platform"])
def test_actor_destination_must_all_match(bridge, settings, field):
    raw = activity(settings)
    if field == "actor":
        raw["from"]["aadObjectId"] = "someone-else"
    elif field == "platform":
        raw["channelId"] = "emulator"
    else:
        raw["channelData"][field] = {"id": "other", "aadGroupId": "other"}
    ctx = SimpleNamespace(activity=AdaptiveCardInvokeActivity.model_validate(raw))
    controller = MagicMock()
    bridge.bind(controller)
    result = asyncio.run(bridge.on_card_action(ctx))
    assert "could not accept" in result.value
    controller.decide.assert_not_called()


@pytest.mark.parametrize("change", ["role", "version", "hash", "verb", "type", "run"])
def test_action_payload_rejects_tampering(bridge, settings, change):
    raw = activity(settings)
    action = raw["value"]["action"]
    if change == "role":
        action["data"]["role"] = "administrator"
    elif change == "version":
        action["data"]["brief_version"] = "1"
    elif change == "hash":
        action["data"]["brief_hash"] = "not-a-hash"
    elif change == "run":
        action["data"]["run_id"] = "not-a-uuid"
    elif change == "verb":
        action["verb"] = "execute"
    else:
        action["type"] = "Action.Submit"
    bridge.bind(MagicMock())
    result = asyncio.run(
        bridge.on_card_action(
            SimpleNamespace(activity=AdaptiveCardInvokeActivity.model_validate(raw))
        )
    )
    assert "could not accept" in result.value
    bridge.controller.decide.assert_not_called()


def test_decision_controller_receives_verified_identity_and_version(bridge, settings):
    current = record()
    approved = current.model_copy(update={"approval": approval(current.envelope)})
    controller = MagicMock()
    controller.decide.return_value = approved
    controller.execute = AsyncMock(
        return_value=approved.model_copy(
            update={"run": approved.run.model_copy(update={"state": RunState.EXECUTED})}
        )
    )
    bridge.bind(controller)
    result = asyncio.run(
        bridge.on_card_action(
            SimpleNamespace(activity=AdaptiveCardInvokeActivity.model_validate(activity(settings)))
        )
    )
    assert "EXECUTED" in result.value
    args, kwargs = controller.decide.call_args
    assert args[:3] == (RUN_ID, settings.tenant_id, settings.approver_user_id)
    assert kwargs == {"brief_version": 1}
    controller.execute.assert_awaited_once_with(RUN_ID)


def test_rejection_never_calls_executor_and_unbound_fails(bridge, settings):
    raw = activity(settings)
    raw["value"]["action"]["verb"] = "reject"
    ctx = SimpleNamespace(activity=AdaptiveCardInvokeActivity.model_validate(raw))
    assert "could not accept" in asyncio.run(bridge.on_card_action(ctx)).value
    controller = MagicMock()
    controller.decide.return_value = record()
    bridge.bind(controller)
    asyncio.run(bridge.on_card_action(ctx))
    controller.execute.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "http://smba.trafficmanager.net/emea/",
        "https://evil.invalid/",
        "https://smba.trafficmanager.net.evil.invalid/",
        "https://user@smba.trafficmanager.net/",
        "https://smba.trafficmanager.net:8443/",
    ],
)
def test_proactive_reference_rejects_arbitrary_destination(bridge, settings, url):
    with pytest.raises(Denied):
        bridge.save_reference(reference(settings, serviceUrl=url))
    bridge.store.save_teams_reference.assert_not_called()


def test_reference_bootstrap_request_and_missing_receipt(bridge, settings):
    raw = activity(settings)
    raw.update(type="message", text="connect")
    raw.pop("value")
    raw.pop("name")
    ctx = SimpleNamespace(
        activity=MessageActivity.model_validate(raw),
        conversation_ref=reference(settings),
        send=AsyncMock(),
    )
    asyncio.run(bridge.on_message(ctx))
    saved = bridge.store.save_teams_reference.call_args.args[0]
    bridge.store.get_teams_reference.return_value = saved
    bridge.app.activity_sender.send = AsyncMock(return_value=SimpleNamespace(id="message-1"))
    assert asyncio.run(bridge.request(record())) == "message-1"
    bridge.app.activity_sender.send.return_value.id = None
    with pytest.raises(Denied, match="receipt"):
        asyncio.run(bridge.request(record()))


def test_unregistered_and_wrong_scope_references_fail_closed(bridge):
    with pytest.raises(Denied):
        asyncio.run(bridge.request(record()))
    bridge.store.get_teams_reference.return_value = {"tenant_id": "other"}
    with pytest.raises(Denied):
        asyncio.run(bridge.request(record()))


def test_sdk_http_rejects_missing_or_invalid_service_authentication(bridge, settings):
    asyncio.run(bridge.initialize())
    client = TestClient(bridge.app.server.adapter.app)
    assert client.post("/api/messages", json=activity(settings)).status_code == 401
    # Signature parsing fails locally; no JWKS or cloud request is needed.
    assert (
        client.post(
            "/api/messages", json=activity(settings), headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )
    bridge.store.save_teams_reference.assert_not_called()
    assert bridge.app.options.dangerously_allow_unauthenticated_requests is False


def test_package_has_valid_dimensions_and_no_credentials(tmp_path):
    path = build_package(
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "https://api.example.invalid",
        tmp_path / "innexq.zip",
    )
    with ZipFile(path) as archive:
        assert set(archive.namelist()) == {"manifest.json", "color.png", "outline.png"}
        manifest_doc = json.loads(archive.read("manifest.json"))
        assert manifest_doc["bots"][0]["scopes"] == ["team"]
        assert manifest_doc["validDomains"] == ["api.example.invalid"]
        for name, size in [("color.png", 192), ("outline.png", 32)]:
            data = archive.read(name)
            assert data[:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", data[16:24]) == (size, size)
    with pytest.raises(FileExistsError):
        build_package("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "https://api.example.invalid", path)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.invalid",
        "https://user:pass@api.invalid",  # pragma: allowlist secret - negative URL fixture
        "https://api.invalid/path",
        "https://api.invalid?q=secret",
    ],
)
def test_package_rejects_unsafe_origins(tmp_path: Path, url: str):
    with pytest.raises(ValueError):
        build_package("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", url, tmp_path / "app.zip")
    assert not (tmp_path / "app.zip").exists()


def test_original_outline_icon_is_transparent():
    assert icon_png(32, outline=True) != icon_png(32, outline=False)

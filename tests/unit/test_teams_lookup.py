"""Missing Teams metadata is verified server-side, never filled from card claims."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from innexq_api.config import Settings
from innexq_api.teams import TeamsApprovals
from microsoft_teams.api import AdaptiveCardInvokeActivity, TeamDetails

from tests.unit.test_teams import activity, record, reference


@pytest.fixture
def lookup_case():
    settings = Settings(_env_file=None, managed_identity_client_id="bot-identity")
    bridge = TeamsApprovals(settings, FastAPI(), MagicMock())
    controller = MagicMock()
    controller.decide.return_value = record()  # Never execute external actions in these tests.
    bridge.bind(controller)
    raw = activity(settings)
    del raw["channelData"]["team"]["aadGroupId"]
    team = TeamDetails(id="19:team@thread.tacv2", aad_group_id=settings.teams_team_id)
    lookup = AsyncMock(return_value=team)
    ctx = SimpleNamespace(
        activity=AdaptiveCardInvokeActivity.model_validate(raw),
        conversation_ref=reference(settings),
        api=SimpleNamespace(teams=SimpleNamespace(get_by_id=lookup)),
    )
    return settings, bridge, controller, raw, team, lookup, ctx


def test_missing_group_resolves_through_bot_api_without_mutating_activity(lookup_case):
    settings, bridge, controller, _, _, lookup, ctx = lookup_case
    before = deepcopy(ctx.activity.model_dump())
    result = asyncio.run(bridge.on_card_action(ctx))
    assert "could not accept" not in result.value.model_dump_json()
    lookup.assert_awaited_once_with("19:team@thread.tacv2")
    assert controller.decide.call_args.args[1:3] == (settings.tenant_id, settings.approver_user_id)
    assert ctx.activity.model_dump() == before
    bridge.store.save_teams_reference.assert_not_called()
    controller.execute.assert_not_called()


@pytest.mark.parametrize("field", ["actor", "tenant", "channel", "platform", "team_group"])
def test_any_other_failure_prevents_lookup(lookup_case, field):
    _, bridge, controller, raw, _, lookup, ctx = lookup_case
    if field == "actor":
        raw["from"]["aadObjectId"] = "other"
    elif field == "platform":
        raw["channelId"] = "emulator"
    elif field == "team_group":
        raw["channelData"]["team"]["aadGroupId"] = "conflicting"
    else:
        raw["channelData"][field]["id"] = "other"
    ctx.activity = AdaptiveCardInvokeActivity.model_validate(raw)
    assert "could not accept" in asyncio.run(bridge.on_card_action(ctx)).value
    lookup.assert_not_awaited()
    controller.decide.assert_not_called()


@pytest.mark.parametrize(
    "team_id", [None, "", "../other", "19:team@thread.tacv2?x=1", "https://evil.invalid"]
)
def test_unsafe_or_missing_team_id_stops_before_network(lookup_case, team_id):
    _, bridge, controller, raw, _, lookup, ctx = lookup_case
    raw["channelData"]["team"]["id"] = team_id
    ctx.activity = AdaptiveCardInvokeActivity.model_validate(raw)
    assert "could not accept" in asyncio.run(bridge.on_card_action(ctx)).value
    lookup.assert_not_awaited()
    controller.decide.assert_not_called()


@pytest.mark.parametrize("field", ["id", "aad_group_id", "tenant_id"])
def test_lookup_identity_conflicts_block_authorization(lookup_case, field):
    _, bridge, controller, _, team, lookup, ctx = lookup_case
    lookup.return_value = team.model_copy(update={field: "other"})
    assert "could not accept" in asyncio.run(bridge.on_card_action(ctx)).value
    controller.decide.assert_not_called()


def test_lookup_missing_group_is_not_evidence(lookup_case):
    _, bridge, controller, _, team, lookup, ctx = lookup_case
    lookup.return_value = team.model_copy(update={"aad_group_id": None})
    assert "could not accept" in asyncio.run(bridge.on_card_action(ctx)).value
    controller.decide.assert_not_called()


@pytest.mark.parametrize(
    "error", [TimeoutError(), PermissionError("denied"), ValueError("malformed")]
)
def test_failed_lookup_never_grants_authorization(lookup_case, error):
    _, bridge, controller, _, _, lookup, ctx = lookup_case
    lookup.side_effect = error
    assert "could not accept" in asyncio.run(bridge.on_card_action(ctx)).value
    controller.decide.assert_not_called()


@pytest.mark.parametrize("change", ["host", "channel"])
def test_untrusted_connector_or_conversation_never_used_for_lookup(lookup_case, change):
    settings, bridge, controller, _, _, lookup, ctx = lookup_case
    ctx.conversation_ref = reference(
        settings,
        **(
            {"serviceUrl": "https://evil.invalid"}
            if change == "host"
            else {"conversation": {"id": "19:other@thread.tacv2"}}
        ),
    )
    assert "could not accept" in asyncio.run(bridge.on_card_action(ctx)).value
    lookup.assert_not_awaited()
    controller.decide.assert_not_called()


def test_present_matching_group_needs_no_network_lookup(lookup_case):
    settings, bridge, controller, _, _, lookup, ctx = lookup_case
    ctx.activity = AdaptiveCardInvokeActivity.model_validate(activity(settings))
    assert "could not accept" not in asyncio.run(bridge.on_card_action(ctx)).value
    lookup.assert_not_awaited()
    controller.decide.assert_called_once()

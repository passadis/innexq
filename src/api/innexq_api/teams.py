"""Teams transport: SDK authenticates the service; controller authorizes the human.

The SDK owns /api/messages. No client-supplied role, manifest, price or recipient
is accepted as authorization. Only a stored brief version/hash may be decided.
"""

from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI
from innexq_contracts.events import RunRecord
from innexq_contracts.hashing import compute_brief_hash
from innexq_contracts.models import Decision, RunState
from microsoft_teams.api import (  # type: ignore[import-untyped]
    AdaptiveCardActionMessageResponse,
    AdaptiveCardInvokeActivity,
    ConversationReference,
    MessageActivity,
    MessageActivityInput,
)
from microsoft_teams.apps import App  # type: ignore[import-untyped]
from microsoft_teams.apps.http import FastAPIAdapter  # type: ignore[import-untyped]
from microsoft_teams.apps.routing import ActivityContext  # type: ignore[import-untyped]
from microsoft_teams.cards import AdaptiveCard  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from innexq_api.config import Settings
from innexq_api.controller import Controller, Denied
from innexq_api.store import Conflict


class ReferenceStore(Protocol):
    def get_teams_reference(self) -> dict[str, Any] | None: ...
    def save_teams_reference(self, reference: dict[str, Any]) -> None: ...


class CardDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str
    brief_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    brief_version: int = Field(ge=1)


def approval_card(record: RunRecord) -> AdaptiveCard:
    """Include exact stored content, not just a hash or a model-written digest."""
    envelope = record.envelope
    if envelope is None or record.run.state != RunState.AWAITING_APPROVAL:
        raise Denied("a stored brief awaiting approval is required")
    if envelope.brief_hash != compute_brief_hash(envelope.brief, envelope.action_manifest):
        raise Denied("stored brief hash mismatch")
    data = {
        "run_id": str(record.run.run_id),
        "brief_hash": envelope.brief_hash,
        "brief_version": envelope.brief.brief_version,
    }
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": "InnexQ | Contract Renewal",
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": "SYNTHETIC TEST — human authorization required",
            "weight": "Bolder",
            "wrap": True,
        },
        {"type": "TextBlock", "text": envelope.brief.recommendation.summary, "wrap": True},
        {
            "type": "TextBlock",
            "text": "Deterministic calculations: "
            + json.dumps([c.model_dump(mode="json") for c in envelope.brief.calculations]),
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": "Policy checks: "
            + json.dumps([p.model_dump(mode="json") for p in envelope.brief.policy_checks]),
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": "Approve authorizes only the exact actions below. "
            "Reject performs no file/email writes. This approval expires after one hour.",
            "wrap": True,
        },
    ]
    displayed_content: set[str] = set()
    for action in envelope.action_manifest.actions:
        body.append(
            {
                "type": "TextBlock",
                "text": action.action_type.value,
                "weight": "Bolder",
                "wrap": True,
            }
        )
        for name, value in action.parameters.items():
            if name == "content" and isinstance(value, str):
                if value in displayed_content:
                    body.append(
                        {
                            "type": "TextBlock",
                            "wrap": True,
                            "text": "content: exactly the full content displayed above "
                            f"(SHA-256 {action.artifact_hash})",
                        }
                    )
                    continue
                displayed_content.add(value)
            body.append({"type": "TextBlock", "text": f"{name}: {value}", "wrap": True})
    body.extend(
        [
            {
                "type": "TextBlock",
                "text": f"Run: {record.run.run_id}\n"
                f"Brief v{envelope.brief.brief_version}\nSHA-256: {envelope.brief_hash}",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "Evidence-backed claims",
                "weight": "Bolder",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "\n".join(c.text for c in envelope.brief.material_claims),
                "wrap": True,
            },
        ]
    )
    payload = {
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": body,
        "actions": [
            {"type": "Action.Execute", "title": title, "verb": verb, "data": data}
            for title, verb in [("Approve exact actions", "approve"), ("Reject", "reject")]
        ],
    }
    # Teams has a bounded message payload. Never silently truncate approved content.
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 24_000:
        raise Denied("approval card exceeds safe payload limit; content cannot be truncated")
    return AdaptiveCard.model_validate(payload)


class TeamsApprovals:
    def __init__(self, settings: Settings, api: FastAPI, store: ReferenceStore) -> None:
        if not settings.managed_identity_client_id or not settings.tenant_id:
            raise Denied("Teams managed identity and tenant are required")
        self.settings, self.store = settings, store
        self.controller: Controller | None = None
        self.app = App(
            client_id=settings.managed_identity_client_id,
            managed_identity_client_id=settings.managed_identity_client_id,
            tenant_id=settings.tenant_id,
            http_server_adapter=FastAPIAdapter(api),
            messaging_endpoint="/api/messages",
            dangerously_allow_unauthenticated_requests=False,
            fetch_user_token=False,
        )
        self.app.on_message(self.on_message)
        self.app.on_card_action(self.on_card_action)

    def bind(self, controller: Controller) -> None:
        self.controller = controller

    async def initialize(self) -> None:
        await self.app.initialize()

    def authorized_activity(self, activity: Any) -> tuple[str, str]:
        """Only call after the SDK's Bot Connector JWT validation succeeded."""
        raw = activity.model_dump(by_alias=True, exclude_none=True)
        channel = raw.get("channelData", {})
        tenant = channel.get("tenant", {}).get("id")
        actor = raw.get("from", {}).get("aadObjectId")
        if (
            raw.get("channelId") != "msteams"
            or tenant != self.settings.tenant_id
            or actor != self.settings.approver_user_id
            or channel.get("team", {}).get("aadGroupId") != self.settings.teams_team_id
            or channel.get("channel", {}).get("id") != self.settings.teams_channel_id
        ):
            raise Denied("Teams actor or destination is not allowlisted")
        return str(tenant), str(actor)

    def save_reference(self, reference: ConversationReference) -> None:
        url = urlsplit(reference.service_url)
        # Public-cloud Teams connector endpoint; never persist arbitrary outbound URLs.
        if (
            url.scheme != "https"
            or url.hostname != "smba.trafficmanager.net"
            or url.username
            or url.password
            or url.port not in (None, 443)
            or reference.channel_id != "msteams"
            or reference.conversation.id.split(";", 1)[0] != self.settings.teams_channel_id
        ):
            raise Denied("invalid Teams conversation reference")
        self.store.save_teams_reference(
            {
                "tenant_id": self.settings.tenant_id,
                "team_id": self.settings.teams_team_id,
                "channel_id": self.settings.teams_channel_id,
                "reference": reference.model_dump(mode="json", by_alias=True, exclude_none=True),
            }
        )

    async def on_message(self, ctx: ActivityContext[MessageActivity]) -> None:
        try:
            self.authorized_activity(ctx.activity)
            self.save_reference(ctx.conversation_ref)
        except Denied:
            return
        await ctx.send(
            "InnexQ approval channel connected. Start a Run through the authenticated "
            "API; its exact decision brief will be posted here for your approval."
        )

    async def request(self, record: RunRecord) -> str:
        saved = self.store.get_teams_reference()
        if (
            saved is None
            or saved.get("tenant_id") != self.settings.tenant_id
            or saved.get("team_id") != self.settings.teams_team_id
            or saved.get("channel_id") != self.settings.teams_channel_id
        ):
            raise Denied("authorized Teams conversation not registered")
        reference = ConversationReference.model_validate(saved["reference"])
        # Revalidate the outbound URL and pinned channel after loading durable state.
        self.save_reference(reference)
        message = MessageActivityInput().add_card(approval_card(record))
        sent = await self.app.activity_sender.send(message, reference)
        if not sent.id:
            raise Denied("Teams did not return a message receipt")
        return str(sent.id)

    async def on_card_action(
        self,
        ctx: ActivityContext[AdaptiveCardInvokeActivity],
    ) -> AdaptiveCardActionMessageResponse:
        try:
            tenant, actor = self.authorized_activity(ctx.activity)
            action = ctx.activity.value.action
            if action.type != "Action.Execute" or action.verb not in ("approve", "reject"):
                raise Denied("unsupported card action")
            data = CardDecision.model_validate(action.data)
            run_id = UUID(data.run_id)
            if self.controller is None:
                raise Denied("controller unavailable")
            record = self.controller.decide(
                run_id,
                tenant,
                actor,
                data.brief_hash,
                Decision(action.verb),
                brief_version=data.brief_version,
            )
            if record.approval is not None and record.approval.decision == Decision.APPROVE:
                record = await self.controller.execute(run_id)
            return AdaptiveCardActionMessageResponse(
                value=f"InnexQ Run {run_id}: {record.run.state.value}. "
                "The stored Run Events are the authoritative execution record."
            )
        except (ValueError, KeyError, Conflict):
            # No exception text, payload, identity or document content leaks to another viewer.
            return AdaptiveCardActionMessageResponse(
                value="InnexQ could not accept this action. No new authorization was granted. "
                "Inspect the Run Events for current status."
            )

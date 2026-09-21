"""Teams transport: SDK authenticates the service; controller authorizes the human.

The SDK owns /api/messages. No client-supplied role, manifest, price or recipient
is accepted as authorization. Only a stored brief version/hash may be decided.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from time import monotonic
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI
from innexq_contracts.events import RunRecord
from innexq_contracts.hashing import compute_brief_hash
from innexq_contracts.models import Decision, RunState
from microsoft_teams.api import (  # type: ignore[import-untyped]
    AdaptiveCardActionCardResponse,
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
from innexq_api.presentation import decision_url
from innexq_api.store import Conflict


class ReferenceStore(Protocol):
    def get_teams_reference(self) -> dict[str, Any] | None: ...
    def save_teams_reference(self, reference: dict[str, Any]) -> None: ...


class CardDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str
    brief_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    brief_version: int = Field(ge=1)


class TeamsActivityDenied(Denied):
    """Fixed check labels only; never retain incoming identity or payload values."""

    def __init__(self, failed_checks: tuple[str, ...]) -> None:
        super().__init__("Teams actor or destination is not allowlisted")
        self.failed_checks = failed_checks


def approval_card(record: RunRecord, web_origin: str = "") -> AdaptiveCard:
    """Compact linked review in production; full inline review without a web origin."""
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
    if web_origin:
        return compact_approval_card(record, web_origin, data)
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


def compact_approval_card(record: RunRecord, web_origin: str, data: dict[str, Any]) -> AdaptiveCard:
    envelope = record.envelope
    if envelope is None:
        raise Denied("a stored brief is required")
    brief = envelope.brief
    facts = [
        {"title": "Customer", "value": record.facts.get("customer_name", record.run.contract_id)},
        {"title": "Contract", "value": record.run.contract_id},
        {
            "title": "Renewal",
            "value": f"{brief.recommendation.term_months} months · "
            + brief.recommendation.service_level,
        },
    ]
    for calculation in brief.calculations:
        values = calculation.outputs
        if "discounted_annual_value" in values:
            facts.append(
                {
                    "title": "Net annual value",
                    "value": f"{values.get('currency', '')} {values['discounted_annual_value']}",
                }
            )
        if "discount_percent" in values:
            facts.append({"title": "Discount", "value": str(values["discount_percent"]) + "%"})
    for action in envelope.action_manifest.actions:
        p = action.parameters
        if action.action_type.value == "sharepoint.create_file":
            facts.append({"title": "Create document", "value": str(p.get("filename", ""))})
        if action.action_type.value == "graph.send_mail":
            facts.extend(
                [
                    {"title": "Email from", "value": str(p.get("sender", ""))},
                    {"title": "Email to", "value": str(p.get("recipient", ""))},
                ]
            )
    roles = sorted(
        {
            check.required_scenario_role
            for check in brief.policy_checks
            if check.required_scenario_role
        }
    )
    if roles:
        facts.append({"title": "Required authority", "value": ", ".join(roles)})
    payload = {
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "InnexQ | Renewal approval",
                "size": "Large",
                "weight": "Bolder",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "SYNTHETIC DEMO · human authorization required",
                "isSubtle": True,
                "wrap": True,
            },
            {"type": "FactSet", "facts": facts},
            {
                "type": "TextBlock",
                "text": "Review the exact document and email in the "
                "Control Room before approving. Approval authorizes this version only; "
                "reject makes no file/email writes. Expires after one hour.",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": f"Brief v{brief.brief_version} · SHA-256 " + envelope.brief_hash,
                "size": "Small",
                "isSubtle": True,
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "Review exact decision",
                "url": decision_url(
                    web_origin, record.run.run_id, brief.brief_version, envelope.brief_hash
                ),
            },
            *[
                {"type": "Action.Execute", "title": title, "verb": verb, "data": data}
                for title, verb in [
                    ("Approve v" + str(brief.brief_version), "approve"),
                    ("Reject", "reject"),
                ]
            ],
        ],
    }
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 24_000:
        raise Denied("approval card exceeds safe payload limit")
    return AdaptiveCard.model_validate(payload)


def status_card(record: RunRecord, web_origin: str = "") -> AdaptiveCard:
    """Render stored results only; this response cannot authorize or retry an action."""
    lines = [
        "InnexQ | Contract Renewal",
        f"Run: {record.run.run_id}",
        f"Stored status: {record.run.state.value}",
    ]
    if record.approval is not None:
        lines.append(
            f"Recorded decision: {record.approval.decision.value} | "
            f"Brief v{record.approval.brief_version} | "
            f"{record.approval.submitted_at.isoformat()}"
        )
    if record.envelope is not None:
        for action in record.envelope.action_manifest.actions:
            key = action.idempotency_key
            lines.append(
                f"{action.action_type.value}: {record.action_status.get(key, 'not started')}"
            )
            if key in record.receipts and not web_origin:
                lines.append(f"Receipt: {record.receipts[key]}")
    lines.append(
        "Run Events are the authoritative record. A mail acceptance receipt is not "
        "proof of recipient delivery. Do not approve again or resend this Run."
    )
    return AdaptiveCard.model_validate(
        {
            "type": "AdaptiveCard",
            "version": "1.5",
            "body": [{"type": "TextBlock", "text": line, "wrap": True} for line in lines],
            "actions": [
                {
                    "type": "Action.OpenUrl",
                    "title": "View decision and receipts",
                    "url": decision_url(
                        web_origin,
                        record.run.run_id,
                        record.envelope.brief.brief_version,
                        record.envelope.brief_hash,
                    ),
                }
            ]
            if web_origin and record.envelope
            else [],
        }
    )


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
        checks = (
            ("platform", raw.get("channelId"), "msteams"),
            ("tenant", tenant, self.settings.tenant_id),
            ("actor", actor, self.settings.approver_user_id),
            ("team_group", channel.get("team", {}).get("aadGroupId"), self.settings.teams_team_id),
            ("channel", channel.get("channel", {}).get("id"), self.settings.teams_channel_id),
        )
        failed_checks = tuple(
            f"{name}.{'missing' if actual is None else 'mismatch'}"
            for name, actual, expected in checks
            if actual != expected
        )
        if failed_checks:
            raise TeamsActivityDenied(failed_checks)
        return str(tenant), str(actor)

    def validate_reference(self, reference: ConversationReference) -> None:
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

    def save_reference(self, reference: ConversationReference) -> None:
        self.validate_reference(reference)
        self.store.save_teams_reference(
            {
                "tenant_id": self.settings.tenant_id,
                "team_id": self.settings.teams_team_id,
                "channel_id": self.settings.teams_channel_id,
                "reference": reference.model_dump(mode="json", by_alias=True, exclude_none=True),
            }
        )

    async def authorize_card_activity(
        self, ctx: ActivityContext[AdaptiveCardInvokeActivity]
    ) -> tuple[str, str]:
        """Resolve an omitted group ID through the authenticated Bot Connector API."""
        try:
            return self.authorized_activity(ctx.activity)
        except TeamsActivityDenied as exc:
            # Never repair conflicting metadata or any other failed boundary.
            if exc.failed_checks != ("team_group.missing",):
                raise
        raw = ctx.activity.model_dump(by_alias=True, exclude_none=True)
        team_id = raw.get("channelData", {}).get("team", {}).get("id")
        # The SDK interpolates this ID into a URL path, so reject path/query syntax.
        if not isinstance(team_id, str) or not re.fullmatch(
            r"19:[A-Za-z0-9_-]+@thread\.(?:tacv2|skype)", team_id
        ):
            raise TeamsActivityDenied(("team_lookup.invalid_id",))
        self.validate_reference(ctx.conversation_ref)
        try:
            team = await asyncio.wait_for(ctx.api.teams.get_by_id(team_id), timeout=3)
        except Exception:
            # Access denial, timeouts and malformed responses never become evidence.
            raise TeamsActivityDenied(("team_lookup.failed",)) from None
        if (
            team.id != team_id
            or team.aad_group_id != self.settings.teams_team_id
            or team.tenant_id not in (None, self.settings.tenant_id)
        ):
            raise TeamsActivityDenied(("team_lookup.mismatch",))
        logging.getLogger("innexq.audit").info(
            "teams_team_verified", extra={"verification": "bot_team_lookup"}
        )
        # These exact values already passed the strict check above. Do not modify
        # the received activity, trust card data, cache grants, or change Run state.
        return self.settings.tenant_id, self.settings.approver_user_id

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
        origin = self.settings.web_origins[0] if self.settings.web_origins else ""
        message = MessageActivityInput().add_card(approval_card(record, origin))
        sent = await self.app.activity_sender.send(message, reference)
        if not sent.id:
            raise Denied("Teams did not return a message receipt")
        return str(sent.id)

    async def notify_operations(self, request_id: UUID, case_id: UUID) -> str:
        saved = self.store.get_teams_reference()
        if (
            saved is None
            or saved.get("tenant_id") != self.settings.tenant_id
            or saved.get("team_id") != self.settings.teams_team_id
            or saved.get("channel_id") != self.settings.teams_channel_id
            or not self.settings.web_origins
        ):
            raise Denied("authorized Operations notification channel required")
        reference = ConversationReference.model_validate(saved["reference"])
        self.validate_reference(reference)
        card = AdaptiveCard.model_validate(
            {
                "type": "AdaptiveCard",
                "version": "1.5",
                "body": [
                    {"type": "TextBlock", "text": "InnexQ | Operations review", "weight": "Bolder"},
                    {
                        "type": "TextBlock",
                        "text": "A certificate request needs review. No PDF was released.",
                        "wrap": True,
                    },
                    {
                        "type": "TextBlock",
                        "text": f"Case {case_id}",
                        "isSubtle": True,
                        "wrap": True,
                    },
                ],
                "actions": [
                    {
                        "type": "Action.OpenUrl",
                        "title": "Open case",
                        "url": f"{self.settings.web_origins[0]}/?operations={request_id}",
                    }
                ],
            }
        )
        sent = await self.app.activity_sender.send(MessageActivityInput().add_card(card), reference)
        if not sent.id:
            raise Denied("Teams notification receipt missing")
        return str(sent.id)

    async def on_card_action(
        self,
        ctx: ActivityContext[AdaptiveCardInvokeActivity],
    ) -> AdaptiveCardActionCardResponse | AdaptiveCardActionMessageResponse:
        started = monotonic()
        stage = "activity_authorization"
        try:
            tenant, actor = await self.authorize_card_activity(ctx)
            stage = "card_action"
            action = ctx.activity.value.action
            if action.type != "Action.Execute" or action.verb not in ("approve", "reject"):
                raise Denied("unsupported card action")
            stage = "card_payload"
            data = CardDecision.model_validate(action.data)
            run_id = UUID(data.run_id)
            stage = "controller_binding"
            if self.controller is None:
                raise Denied("controller unavailable")
            stage = "controller_decision"
            record = self.controller.decide(
                run_id,
                tenant,
                actor,
                data.brief_hash,
                Decision(action.verb),
                brief_version=data.brief_version,
            )
            if record.approval is not None and record.approval.decision == Decision.APPROVE:
                stage = "controlled_execution"
                record = await self.controller.execute(run_id)
            origin = self.settings.web_origins[0] if self.settings.web_origins else ""
            response = AdaptiveCardActionCardResponse(value=status_card(record, origin))
            logging.getLogger("innexq.audit").info(
                "teams_callback_completed",
                extra={
                    "run_id": str(record.run.run_id),
                    "correlation_id": str(record.run.correlation_id),
                    "state": record.run.state.value,
                    "elapsed_ms": round((monotonic() - started) * 1000),
                    "response_type": "adaptive_card",
                },
            )
            return response
        except (ValueError, KeyError, Conflict) as exc:
            # Keep pre-controller failures observable without trusting/logging card data.
            # Do not attach exception text/tracebacks: validation errors contain inputs.
            logging.getLogger("innexq.audit").warning(
                "teams_callback_rejected",
                extra={
                    "failed_checks": ",".join(exc.failed_checks)
                    if isinstance(exc, TeamsActivityDenied)
                    else stage,
                    "elapsed_ms": round((monotonic() - started) * 1000),
                },
            )
            # No exception text, payload, identity or document content leaks to another viewer.
            return AdaptiveCardActionMessageResponse(
                value="InnexQ could not accept or finish this action. "
                "An approval or external action may already be recorded. "
                "Inspect the Run Events before taking any further action; do not re-approve."
            )

"""Explicit packet-mode routing; a failed candidate never falls back to legacy."""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from agent_framework import Agent, AgentContext, AgentMiddleware

from certificate_team import CertificateTeamGuard
from evidence_team import EvidenceTeamGuard
from evidence_transport import current_evidence_handles


class EvidenceDispatch(AgentMiddleware):
    def __init__(self, client: Any, credential: Any, endpoint: str, project: str) -> None:
        self.candidate = EvidenceTeamGuard(client, credential, endpoint, project)
        self.legacy = CertificateTeamGuard(client)

    async def process(
        self, context: AgentContext, call_next: Callable[[], Awaitable[None]]
    ) -> None:
        users = [m for m in context.messages if m.role == "user"]
        if len(users) != 1 or len(users[0].text) > 50000:
            raise ValueError("one bounded controller packet required")
        packet = json.loads(users[0].text)
        if isinstance(packet, dict) and packet.get("mode") == "evidence_investigation":
            await self.candidate.process(context, call_next)
        else:
            if current_evidence_handles():
                raise ValueError("evidence handles cannot be used with legacy packets")
            await self.legacy.process(context, call_next)


def candidate_certificate_team(client: Any, credential: Any, endpoint: str, project: str) -> Agent:
    return Agent(
        client=client,
        name="innexq-request-coordinator",
        middleware=[EvidenceDispatch(client, credential, endpoint, project)],
        default_options={"store": False},
    )

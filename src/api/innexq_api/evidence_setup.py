"""Explicit candidate wiring; enabling does not select or promote an agent version."""

from pathlib import Path
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from starlette.types import ASGIApp

from innexq_api.auth import EntraAuth
from innexq_api.certificate_runtime import CertificateApplication
from innexq_api.config import Settings
from innexq_api.document_extraction import DocumentIntelligenceExtractor
from innexq_api.evidence_broker import EvidenceBroker, EvidenceStore
from innexq_api.evidence_mcp import evidence_mcp
from innexq_api.evidence_runtime import BrokerInvestigatedEvidence, HostedEvidenceTeam
from innexq_api.evidence_sources import CertificateEvidenceBackend


def configure_evidence(
    config: Settings,
    application: CertificateApplication,
    auth: EntraAuth,
    container: Any,
    credential: Any,
) -> tuple[ASGIApp, FastMCP]:
    if not config.evidence_broker_enabled:
        raise ValueError("evidence broker not enabled")
    policy = Path("docs/security/certificate-release-policy-v1.md").read_text(encoding="utf-8")
    candidate_extractor = DocumentIntelligenceExtractor(
        application.extractor.endpoint, application.extractor.credential, deadline_seconds=45
    )
    backend = CertificateEvidenceBackend(application.repository, candidate_extractor, policy)
    broker = EvidenceBroker(EvidenceStore(container), backend, now=application.now)
    principal = UUID(config.evidence_agent_principal_id)
    mounted = evidence_mcp(
        broker, auth, principal, UUID(config.evidence_agent_client_id), config.evidence_api_host
    )
    if not config.evidence_tools_enabled:
        # Broker staging must not alter the accepted customer investigation path.
        # Scopes still originate only in trusted controller code, never HTTP/MCP.
        return mounted
    team = HostedEvidenceTeam(config, credential)

    def factory(request_id: UUID, prompt: str, intent: str) -> BrokerInvestigatedEvidence:
        return BrokerInvestigatedEvidence(
            application.repository,
            backend,
            broker,
            team,
            UUID(config.tenant_id),
            principal,
            request_id,
            prompt,
            intent,
            now=application.now,
        )

    application.evidence_factory = factory
    return mounted

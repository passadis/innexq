"""Broker-only deployment probe; never creates a workflow or authorizes a PDF.

Run inside the existing API container with explicit --execute. This uses the API
managed identity for Cosmos/Foundry and the distinct reader identity for sources.
Only evidence attempt scopes/receipts may be written. The customer release path
must remain disabled. A successful probe proves evidence investigation, not an
eligibility decision, customer download, notification or business workflow.
"""

import argparse
import json
import logging
import os
import re
import secrets
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Never
from uuid import UUID, uuid4

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import VersionRefIndicator
from azure.cosmos import CosmosClient
from azure.identity import ManagedIdentityCredential

from innexq_api.certificate_repository import PrivateCertificateRepository
from innexq_api.config import Settings
from innexq_api.document_extraction import DocumentIntelligenceExtractor
from innexq_api.evidence_broker import ALLOWED, EvidenceBroker, EvidenceStore
from innexq_api.evidence_runtime import BrokerInvestigatedEvidence, HostedEvidenceTeam
from innexq_api.evidence_sources import CertificateEvidenceBackend

EQUIPMENT = ("DEMO-PT-001", "DEMO-PT-002", "DEMO-PT-003")
AGENT_NAME = "innexq-certificate-team"


def transport_canary(config: Settings, version: str, execute: bool) -> dict[str, Any]:
    """Send never-issued dummy handles; failure is expected, not transport proof."""
    candidate = validate_probe(config, version, "DEMO-PT-001", execute)
    request_id = uuid4()
    marker = secrets.token_urlsafe(32)
    header_prefix = "x-client-innexq-evidence-"
    packet = {
        "mode": "evidence_investigation",
        "request_id": str(request_id),
        "tenant_id": candidate.tenant_id,
        "customer_id": "DEMO-FAB",
        "equipment_id": "DEMO-PT-001",
        "intent": "certificate_request",
        "prompt": "Inspect certificate evidence.",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    output: dict[str, Any] = {"status": "canary_sent", "marker": marker, "session_id": None}
    with ManagedIdentityCredential(client_id=candidate.managed_identity_client_id) as credential:
        with AIProjectClient(
            endpoint=candidate.foundry_project_endpoint, credential=credential
        ) as project:
            session = project.agents.create_session(
                agent_name=AGENT_NAME,
                version_indicator=VersionRefIndicator(agent_version=version),
            )
            output["session_id"] = session.agent_session_id
            try:
                with project.get_openai_client(
                    agent_name=AGENT_NAME, max_retries=0, timeout=280
                ) as client:
                    response = client.responses.create(
                        input=json.dumps(packet),
                        store=False,
                        extra_headers={
                            header_prefix
                            + role.replace("_", "-"): f"{request_id.hex}.{role}.{marker}"
                            for role in ("document_analyst", "equipment_service")
                        },
                        extra_body={"agent_session_id": session.agent_session_id},
                    )
                if response.status == "completed":
                    output["status"] = "fail"
            except Exception:  # noqa: S110 - expected denial; no raw errors
                pass
    # The marker was never issued to the broker, so it has no capability. It is
    # deliberately emitted only for an operator's telemetry/storage leak check.
    return output


def disable_telemetry() -> None:
    """Dedicated process only: disable SDK exporters, content/header capture and logs."""
    os.environ.update(
        {
            "OTEL_SDK_DISABLED": "true",
            "AZURE_SDK_TRACING_ENABLED": "false",
            "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED": "false",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
            "OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST": "",
            "OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_CLIENT_REQUEST": "",
            "OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SANITIZE_FIELDS": ".*",
        }
    )
    # Provider errors can contain transport headers; emit only our bounded JSON.
    logging.disable(logging.CRITICAL)


def validate_probe(config: Settings, version: str, equipment: str, execute: bool) -> Settings:
    if (
        not execute
        or config.environment not in {"dev", "demo"}
        or not config.certificates_enabled
        or not config.evidence_broker_enabled
        or config.evidence_tools_enabled
        or config.certificate_agent_name != AGENT_NAME
        or not re.fullmatch(r"[1-9][0-9]*", version)
        or version == "3"
        or equipment not in EQUIPMENT
    ):
        raise ValueError("broker-only candidate probe configuration required")
    api_identity = UUID(config.managed_identity_client_id)
    reader_identity = UUID(config.certificate_reader_client_id)
    agent_identity = UUID(config.evidence_agent_client_id)
    UUID(config.evidence_agent_principal_id)
    UUID(config.tenant_id)
    if len({api_identity, reader_identity, agent_identity}) != 3:
        raise ValueError("separate identities required")
    if not all(
        (
            config.cosmos_endpoint,
            config.cosmos_database,
            config.cosmos_container,
            config.foundry_project_endpoint,
            config.certificate_blob_endpoint,
            config.document_intelligence_endpoint,
        )
    ):
        raise ValueError("explicit evidence resource configuration required")
    # Immutable local copy, never changes the deployment's selected agent version.
    return Settings.model_validate(config.model_dump() | {"certificate_agent_version": version})


def probe(config: Settings, version: str, equipment: str, *, execute: bool) -> dict[str, Any]:
    disable_telemetry()
    candidate = validate_probe(config, version, equipment, execute)
    output: dict[str, Any] = {"status": "fail", "attempt_id": None, "tools": []}
    with ExitStack() as stack:
        api_identity = stack.enter_context(
            ManagedIdentityCredential(client_id=candidate.managed_identity_client_id)
        )
        reader_identity = stack.enter_context(
            ManagedIdentityCredential(client_id=candidate.certificate_reader_client_id)
        )
        cosmos = stack.enter_context(
            CosmosClient(candidate.cosmos_endpoint, credential=api_identity, logging_enable=False)
        )
        container = cosmos.get_database_client(candidate.cosmos_database).get_container_client(
            candidate.cosmos_container
        )
        repository = PrivateCertificateRepository(
            candidate.certificate_blob_endpoint, candidate.certificate_container, reader_identity
        )
        extractor = DocumentIntelligenceExtractor(
            candidate.document_intelligence_endpoint, reader_identity, deadline_seconds=45
        )
        policy = Path("docs/security/certificate-release-policy-v1.md").read_text(encoding="utf-8")
        backend = CertificateEvidenceBackend(repository, extractor, policy)
        broker = EvidenceBroker(EvidenceStore(container), backend)
        team = HostedEvidenceTeam(candidate, api_identity)
        reader = BrokerInvestigatedEvidence(
            repository,
            backend,
            broker,
            team,
            UUID(candidate.tenant_id),
            UUID(candidate.evidence_agent_principal_id),
            uuid4(),  # correlation only; no workflow or case is created
            "Inspect the existing certificate and service evidence for this equipment.",
            "certificate_request",
        )
        try:
            registry, _, _ = repository.registry()
            machine = next(e for e in registry.catalog.equipment if e.equipment_id == equipment)
            # This is a synthetic source lookup, not a delegated customer identity.
            if not re.fullmatch(r"DEMO-[A-Z0-9-]+", machine.customer_id):
                raise ValueError("synthetic customer required")
            sources = reader.read(machine.customer_id, equipment)
            if reader.active_binding is None or sources.investigation is None:
                raise ValueError("verified investigation required")
            attempt = UUID(str(reader.active_binding.request_id))
            activity = sources.investigation.tool_activity
            if not 4 <= len(activity) <= 12:
                raise ValueError("complete verified tool receipts required")
            tools = []
            for item in activity:
                if (
                    UUID(str(item.attempt_id)) != attempt
                    or item.specialist not in ALLOWED
                    or item.tool_name not in ALLOWED[item.specialist]
                ):
                    raise ValueError("verified tool activity binding required")
                tools.append(
                    {"tool_name": item.tool_name, "receipt_id": str(UUID(str(item.receipt_id)))}
                )
            if len({item["receipt_id"] for item in tools}) != len(tools):
                raise ValueError("unique verified receipts required")
            output = {"status": "pass", "attempt_id": str(attempt), "tools": tools}
        except (Exception, KeyboardInterrupt):
            if reader.active_binding is not None:
                output["attempt_id"] = str(UUID(str(reader.active_binding.request_id)))
                try:
                    broker.abort(reader.active_binding)
                except Exception:  # noqa: S110 - never expose private provider errors
                    pass
    return output


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise ValueError("invalid probe arguments")


def main(argv: list[str] | None = None) -> int:
    disable_telemetry()
    parser = SafeParser(description=__doc__)
    parser.add_argument("--agent-version", required=True)
    parser.add_argument("--equipment", choices=EQUIPMENT, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--transport-canary", action="store_true")
    try:
        args = parser.parse_args(argv)
        result = (
            transport_canary(Settings(), args.agent_version, args.execute)
            if args.transport_canary
            else probe(Settings(), args.agent_version, args.equipment, execute=args.execute)
        )
    except (Exception, KeyboardInterrupt):
        result = {"status": "fail", "attempt_id": None, "tools": []}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"pass", "canary_sent"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

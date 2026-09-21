"""Candidate controller bridge: agent-directed reads, controller-verified receipts."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import VersionRefIndicator
from innexq_contracts.certificates import (
    CertificateInvestigation,
    CertificateSource,
    CertificateSources,
    DocumentFieldProof,
    EvidenceToolActivity,
    OwnershipSource,
    ServiceSource,
    SpecialistProof,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from innexq_api.certificate_repository import PrivateCertificateRepository
from innexq_api.certificates import EvidenceUnavailable
from innexq_api.config import Settings
from innexq_api.evidence_broker import ROLES, EvidenceBinding, EvidenceBroker, Role
from innexq_api.evidence_sources import CertificateEvidenceBackend


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    specialist: Role
    response_id: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    receipt_ids: list[UUID] = Field(min_length=2, max_length=6)


class TeamReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    intent: Literal["certificate_request", "certificate_status", "service_status"]
    specialists: list[Report] = Field(min_length=2, max_length=2)


class EvidenceTeam(Protocol):
    def investigate(
        self, binding: EvidenceBinding, handles: dict[Role, SecretStr], prompt: str, intent: str
    ) -> tuple[TeamReport, str]: ...


class HostedEvidenceTeam:
    def __init__(self, settings: Settings, credential: Any) -> None:
        if not settings.certificate_agent_name or not settings.certificate_agent_version:
            raise ValueError("immutable candidate agent required")
        self.settings, self.credential = settings, credential

    def investigate(
        self, binding: EvidenceBinding, handles: dict[Role, SecretStr], prompt: str, intent: str
    ) -> tuple[TeamReport, str]:
        packet = {
            "mode": "evidence_investigation",
            "request_id": str(binding.request_id),
            "tenant_id": str(binding.tenant_id),
            "customer_id": binding.customer_id,
            "equipment_id": binding.equipment_id,
            "expires_at": binding.expires_at.isoformat(),
            "prompt": prompt,
            "intent": intent,
        }
        try:
            with AIProjectClient(
                endpoint=self.settings.foundry_project_endpoint, credential=self.credential
            ) as project:
                session = project.agents.create_session(
                    agent_name=self.settings.certificate_agent_name,
                    version_indicator=VersionRefIndicator(
                        agent_version=self.settings.certificate_agent_version
                    ),
                )
                with project.get_openai_client(
                    agent_name=self.settings.certificate_agent_name, max_retries=0, timeout=280
                ) as client:
                    response = client.responses.create(
                        input=json.dumps(packet),
                        store=False,
                        extra_headers={
                            f"x-client-innexq-evidence-{role.replace('_', '-')}": handles[
                                role
                            ].get_secret_value()
                            for role in ROLES
                        },
                        extra_body={"agent_session_id": session.agent_session_id},
                    )
                if (
                    response.status != "completed"
                    or not response.id
                    or len(response.output_text) > 20000
                    or any(h.get_secret_value() in response.output_text for h in handles.values())
                ):
                    raise ValueError("invalid candidate response")
                report = TeamReport.model_validate_json(response.output_text)
                if report.request_id != binding.request_id or report.intent != intent:
                    raise ValueError("candidate request binding mismatch")
                if {r.specialist for r in report.specialists} != set(ROLES):
                    raise ValueError("both specialist reports required")
                return report, response.id
        except Exception:
            raise EvidenceUnavailable("scoped evidence specialists unavailable") from None


class BrokerInvestigatedEvidence:
    def __init__(
        self,
        repository: PrivateCertificateRepository,
        backend: CertificateEvidenceBackend,
        broker: EvidenceBroker,
        team: EvidenceTeam,
        tenant_id: UUID,
        principal_id: UUID,
        workflow_request_id: UUID,
        prompt: str,
        intent: str = "certificate_request",
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository, self.backend, self.broker, self.team = repository, backend, broker, team
        self.tenant_id, self.principal_id = tenant_id, principal_id
        self.workflow_request_id, self.prompt, self.intent = workflow_request_id, prompt, intent
        self.now = now
        self.cached: tuple[EvidenceBinding, Any, CertificateSources] | None = None
        self.active_binding: EvidenceBinding | None = None

    def read(self, customer_id: str, equipment_id: str) -> CertificateSources:
        try:
            return self._read(customer_id, equipment_id)
        except Exception:
            if self.active_binding is not None:
                try:
                    self.broker.abort(self.active_binding)
                except Exception:  # noqa: S110 - expiry/CAS still fail closed; no private error logging
                    pass
            raise EvidenceUnavailable("scoped certificate evidence unavailable") from None

    def _read(self, customer_id: str, equipment_id: str) -> CertificateSources:
        registry, version, _ = self.repository.registry()
        if self.cached is not None:
            binding, previous, sources = self.cached
            if (
                binding.customer_id != customer_id
                or binding.equipment_id != equipment_id
                or binding.source_version != version
                or previous != registry
                or binding.policy_sha256 != self.backend.policy_sha256
                or self.now() >= binding.expires_at
            ):
                raise EvidenceUnavailable("cached evidence no longer current")
            return sources
        equipment = next(
            (
                e
                for e in registry.catalog.equipment
                if e.equipment_id == equipment_id and e.customer_id == customer_id
            ),
            None,
        )
        if equipment is None or self.intent not in {
            "certificate_request",
            "certificate_status",
            "service_status",
        }:
            raise EvidenceUnavailable("equipment or intent outside scope")
        required = [equipment.service_document_id]
        if self.intent != "service_status":
            if equipment.certificate_document_id is None:
                raise EvidenceUnavailable("required certificate missing")
            required.append(equipment.certificate_document_id)
        if any(doc not in registry.artifacts for doc in required):
            raise EvidenceUnavailable("required existing PDF missing")
        binding = EvidenceBinding(
            request_id=uuid4(),
            workflow_request_id=self.workflow_request_id,
            tenant_id=self.tenant_id,
            agent_principal_id=self.principal_id,
            customer_id=customer_id,
            equipment_id=equipment_id,
            source_version=version,
            policy_sha256=self.backend.policy_sha256,
            document_hashes={doc: registry.artifacts[doc].sha256 for doc in required},
            expires_at=self.now() + timedelta(minutes=5),
        )
        handles = self.broker.issue(binding)
        self.active_binding = binding
        report, response_id = self.team.investigate(binding, handles, self.prompt, self.intent)
        if (
            report.request_id != binding.request_id
            or report.intent != self.intent
            or not response_id
            or {r.specialist for r in report.specialists} != set(ROLES)
        ):
            raise EvidenceUnavailable("complete bound specialist reports required")
        results = self.broker.finish(
            binding, {r.specialist: r.receipt_ids for r in report.specialists}
        )
        current, current_version, observed = self.repository.registry()
        if current_version != version or current != registry or self.now() >= binding.expires_at:
            raise EvidenceUnavailable("source changed during investigation")
        fields = []
        for result in results:
            if result["tool_name"] != "analyze_document":
                continue
            payload = result["payload"]
            doc_id = payload["document_id"]
            if (
                doc_id not in binding.document_hashes
                or payload["sha256"] != binding.document_hashes[doc_id]
                or payload["document_version"] != binding.document_hashes[doc_id]
            ):
                raise EvidenceUnavailable("receipt artifact changed")
            for field in payload["fields"]:
                for citation in field["citations"]:
                    fields.append(
                        DocumentFieldProof(
                            document_id=doc_id,
                            document_version=payload["document_version"],
                            sha256=payload["sha256"],
                            label=field["key"],
                            value=field["value"],
                            page=citation["page_number"],
                            polygon=tuple(Decimal(str(c)) for c in citation["polygon"]),
                        )
                    )
        documents = {d.document_id: d for d in registry.catalog.documents}
        stamp: dict[str, Any] = {
            "source_version": version,
            "observed_at": observed,
            "fresh_until": min(observed + timedelta(minutes=5), binding.expires_at),
        }
        identity: dict[str, Any] = {
            "customer_id": customer_id,
            "equipment_id": equipment_id,
            "serial_number": equipment.serial_number,
        }
        service = documents[equipment.service_document_id]
        certificate = None
        if self.intent != "service_status":
            doc = documents[equipment.certificate_document_id or ""]
            certificate = CertificateSource(
                **stamp,
                **identity,
                **registry.artifacts[doc.document_id].model_dump(),
                accessible=True,
                revoked=registry.revoked.get(doc.document_id),
                valid_from=datetime.combine(doc.issued_on, time.min, UTC),
                valid_until=datetime.combine(doc.valid_until + timedelta(days=1), time.min, UTC),
            )
        sources = CertificateSources(
            ownership=OwnershipSource(**stamp, **identity),
            certificate=certificate,
            service=ServiceSource(
                **stamp,
                **identity,
                in_service=registry.in_service.get(equipment_id),
                valid_from=datetime.combine(service.issued_on, time.min, UTC),
                valid_until=datetime.combine(
                    service.valid_until + timedelta(days=1), time.min, UTC
                ),
            ),
            investigation=CertificateInvestigation(
                request_id=self.workflow_request_id,
                fields=tuple(fields),
                tool_activity=tuple(
                    EvidenceToolActivity(
                        attempt_id=binding.request_id,
                        receipt_id=result["receipt_id"],
                        specialist=result["specialist"],
                        tool_name=result["tool_name"],
                        source_version=result["source_version"],
                        completed_at=result["completed_at"],
                        document_id=result["payload"].get("document_id"),
                    )
                    for result in results
                ),
                specialists=(
                    SpecialistProof(
                        specialist="request_coordinator",
                        response_id=response_id,
                        summary="Scoped document and equipment investigations completed.",
                    ),
                    *(
                        SpecialistProof(
                            specialist=r.specialist, response_id=r.response_id, summary=r.summary
                        )
                        for r in report.specialists
                    ),
                ),
            ),
        )
        self.cached = (binding, registry, sources)
        return sources

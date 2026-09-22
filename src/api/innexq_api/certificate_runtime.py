"""Connect trusted private sources, actual OCR, specialist reasoning and controller."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol
from uuid import UUID

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import VersionRefIndicator
from innexq_contracts.certificates import (
    CertificateInvestigation,
    CertificateSource,
    CertificateSources,
    DocumentFieldProof,
    OwnershipSource,
    ServiceSource,
    SpecialistProof,
)
from innexq_contracts.customer_conversation import (
    CustomerInterpretation,
    CustomerMessage,
    CustomerReply,
    CustomerRequestContext,
)

from innexq_api.certificate_repository import PrivateCertificateRepository
from innexq_api.certificate_store import CosmosCertificateStore
from innexq_api.certificates import (
    CertificateController,
    CertificateEvidenceReader,
    EvidenceUnavailable,
)
from innexq_api.config import Settings
from innexq_api.controller import Denied
from innexq_api.customer_routes import CustomerRequest
from innexq_api.document_extraction import (
    DocumentExtraction,
    DocumentIntelligenceExtractor,
    require_exact_fields,
)


class CertificateTeam(Protocol):
    def investigate(self, packet: dict[str, Any]) -> tuple[SpecialistProof, ...]: ...
    def interpret(self, packet: dict[str, Any]) -> tuple[CustomerInterpretation, str]: ...


class CoverageCustomerPort(Protocol):
    """Optional Service Coverage Renewal pack; absence degrades to unsupported replies."""

    def outcome(
        self, customer_id: str, equipment_id: str
    ) -> "Literal['existing_pdf', 'renewal_required', 'unavailable']": ...

    def start(self, customer_id: str, equipment_id: str, request_id: UUID) -> dict[str, Any]: ...

    def progress(self, customer_id: str, request_id: UUID) -> dict[str, Any]: ...

    def download(self, customer_id: str, request_id: UUID) -> bytes: ...


class HostedCertificateTeam:
    def __init__(self, settings: Settings, credential: Any) -> None:
        if not settings.certificate_agent_name or not settings.certificate_agent_version:
            raise ValueError("an immutable certificate team deployment is required")
        self.settings, self.credential = settings, credential

    def interpret(self, packet: dict[str, Any]) -> tuple[CustomerInterpretation, str]:
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
                    agent_name=self.settings.certificate_agent_name, max_retries=0, timeout=90
                ) as client:
                    response = client.responses.create(
                        input=json.dumps(packet),
                        extra_body={"agent_session_id": session.agent_session_id},
                    )
                if response.status != "completed" or not response.id:
                    raise ValueError("interpretation did not complete")
                proposal = CustomerInterpretation.model_validate_json(response.output_text)
                if str(proposal.request_id) != packet["request_id"] or (
                    proposal.equipment_id is not None
                    and proposal.equipment_id not in packet["equipment_ids"]
                ):
                    raise ValueError("interpretation scope mismatch")
                return proposal, response.id
        except Exception:
            raise EvidenceUnavailable("customer interpretation unavailable") from None

    def investigate(self, packet: dict[str, Any]) -> tuple[SpecialistProof, ...]:
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
                    agent_name=self.settings.certificate_agent_name, max_retries=0, timeout=180
                ) as client:
                    response = client.responses.create(
                        input=json.dumps(packet),
                        extra_body={"agent_session_id": session.agent_session_id},
                    )
                if response.status != "completed" or not response.id:
                    raise ValueError("specialist invocation did not complete")
                data = json.loads(response.output_text)
                if (
                    set(data) != {"request_id", "intent", "specialists"}
                    or data["request_id"] != packet["request_id"]
                    or data["intent"] != packet.get("intent", "certificate_request")
                ):
                    raise ValueError("specialist request binding failed")
                proofs = tuple(SpecialistProof.model_validate(p) for p in data["specialists"])
                if len(proofs) != 2 or {p.specialist for p in proofs} != {
                    "document_analyst",
                    "equipment_service",
                }:
                    raise ValueError("both specialist results required")
                for proof in proofs:
                    source = (
                        packet["document_facts"]
                        if proof.specialist == "document_analyst"
                        else packet["equipment_facts"]
                    )
                    if proof.summary not in source:
                        raise ValueError("specialist citation does not match tool evidence")
                return (
                    SpecialistProof(
                        specialist="request_coordinator",
                        response_id=response.id,
                        summary="Investigation routed to document and equipment specialists.",
                    ),
                    *proofs,
                )
        except Exception:
            # No provider response text, prompt, document or bearer token in public errors.
            raise EvidenceUnavailable("certificate specialists unavailable") from None


class InvestigatedEvidence:
    def __init__(
        self,
        repository: PrivateCertificateRepository,
        extractor: DocumentIntelligenceExtractor,
        team: CertificateTeam,
        tenant_id: UUID,
        request_id: UUID,
        prompt: str,
        intent: str = "certificate_request",
    ) -> None:
        self.repository, self.extractor, self.team = repository, extractor, team
        self.tenant_id, self.request_id, self.prompt = tenant_id, request_id, prompt
        self.intent = intent
        self.cache: dict[tuple[str, str], DocumentExtraction] = {}

    def read(self, customer_id: str, equipment_id: str) -> CertificateSources:
        registry, version, _ = self.repository.registry()
        equipment = next(
            (
                e
                for e in registry.catalog.equipment
                if e.equipment_id == equipment_id and e.customer_id == customer_id
            ),
            None,
        )
        if equipment is None:
            raise EvidenceUnavailable("equipment not available in customer scope")
        documents = {d.document_id: d for d in registry.catalog.documents}
        fields: list[DocumentFieldProof] = []
        # A missing document is not fabricated. Stop; the controller creates the case.
        document_ids = (
            (equipment.service_document_id,)
            if self.intent == "service_status"
            else (equipment.service_document_id, equipment.certificate_document_id)
        )
        for document_id in document_ids:
            if document_id is None or document_id not in registry.artifacts:
                raise EvidenceUnavailable("required existing PDF missing")
            document = documents[document_id]
            if (
                document.kind == "service_report"
                and document.valid_until != equipment.service_valid_until
            ):
                raise EvidenceUnavailable("service validity conflicts with equipment record")
            artifact = registry.artifacts[document_id]
            pdf = self.repository.read(customer_id, artifact)
            cache_key = (document_id, artifact.sha256)
            extraction = self.cache.get(cache_key)
            if extraction is None:
                extraction = self.extractor.extract(
                    pdf,
                    document_id=document_id,
                    document_version=artifact.document_version,
                    expected_sha256=artifact.sha256,
                )
                self.cache[cache_key] = extraction
            expected = {
                "Document ID": document_id,
                "Customer ID": customer_id,
                "Equipment ID": equipment_id,
                "Recorded serial number": equipment.serial_number,
                "Issued on": document.issued_on.isoformat(),
                "Valid until": document.valid_until.isoformat(),
            }
            if document.kind == "service_report":
                expected["Next service due"] = equipment.service_valid_until.isoformat()
            matched = require_exact_fields(extraction, expected)
            for field in matched:
                for citation in field.citations:
                    fields.append(
                        DocumentFieldProof(
                            document_id=document_id,
                            document_version=artifact.document_version,
                            sha256=artifact.sha256,
                            label=field.key,
                            value=field.value,
                            page=citation.page_number,
                            polygon=tuple(
                                Decimal(str(coordinate)) for coordinate in citation.polygon
                            ),
                        )
                    )
        document_facts = list(
            dict.fromkeys(f"{f.document_id} page {f.page}: {f.label} = {f.value}" for f in fields)
        )
        equipment_facts = [
            f"Equipment ID = {equipment_id}",
            f"Customer ID = {customer_id}",
            f"Serial number = {equipment.serial_number}",
            f"In service = {registry.in_service.get(equipment_id)}",
            "Certificate revoked = "
            f"{registry.revoked.get(equipment.certificate_document_id or '')}",
        ]
        proofs = self.team.investigate(
            {
                "request_id": str(self.request_id),
                **({"intent": self.intent} if self.intent != "certificate_request" else {}),
                "tenant_id": str(self.tenant_id),
                "customer_id": customer_id,
                "equipment_id": equipment_id,
                "prompt": self.prompt,
                "document_facts": document_facts,
                "equipment_facts": equipment_facts,
            }
        )
        # Long OCR/model work must not refresh obsolete registry facts merely by
        # changing a timestamp. Re-read the authority and require the same version.
        current, current_version, observed = self.repository.registry()
        if version != current_version or current != registry:
            raise EvidenceUnavailable("source changed during investigation")
        stamp: dict[str, Any] = {
            "source_version": version,
            "observed_at": observed,
            "fresh_until": observed + timedelta(seconds=300),
        }
        service = documents[equipment.service_document_id]
        identity: dict[str, Any] = {
            "customer_id": customer_id,
            "equipment_id": equipment_id,
            "serial_number": equipment.serial_number,
        }
        certificate_source = None
        if self.intent != "service_status":
            certificate = documents[equipment.certificate_document_id or ""]
            artifact = registry.artifacts[certificate.document_id]
            certificate_source = CertificateSource(
                **stamp,
                **identity,
                **artifact.model_dump(),
                accessible=True,
                revoked=registry.revoked.get(certificate.document_id),
                valid_from=datetime.combine(certificate.issued_on, time.min, UTC),
                valid_until=datetime.combine(
                    certificate.valid_until + timedelta(days=1), time.min, UTC
                ),
            )
        return CertificateSources(
            ownership=OwnershipSource(**stamp, **identity),
            certificate=certificate_source,
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
                request_id=self.request_id,
                fields=tuple(fields),
                specialists=proofs,
            ),
        )


class CertificateApplication:
    def __init__(
        self,
        settings: Settings,
        repository: PrivateCertificateRepository,
        extractor: DocumentIntelligenceExtractor,
        team: CertificateTeam,
        store: CosmosCertificateStore,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        evidence_factory: Callable[[UUID, str, str], CertificateEvidenceReader] | None = None,
        coverage: CoverageCustomerPort | None = None,
    ) -> None:
        self.settings, self.repository, self.extractor = settings, repository, extractor
        self.team, self.store, self.now = team, store, now
        self.evidence_factory = evidence_factory
        self.coverage = coverage
        self.bindings = {UUID(k): v for k, v in settings.customer_bindings.items()}
        if UUID(settings.approver_user_id) in self.bindings:
            raise ValueError("Operations cannot have a customer binding")

    def _customer(self, tenant: UUID, actor: UUID) -> str:
        if str(tenant) != self.settings.tenant_id or actor not in self.bindings:
            raise Denied("customer is not assigned")
        return self.bindings[actor]

    def _controller(
        self, request_id: UUID, prompt: str, context: CustomerRequestContext | None = None
    ) -> CertificateController:
        tenant = UUID(self.settings.tenant_id)
        evidence = self.evidence(request_id, prompt)
        return CertificateController(
            tenant,
            self.bindings,
            UUID(self.settings.approver_user_id),
            evidence,
            self.repository,
            self.store,
            self.now,
            request_context=context,
        )

    def evidence(
        self, request_id: UUID, prompt: str, intent: str = "certificate_request"
    ) -> CertificateEvidenceReader:
        if self.evidence_factory is not None:
            return self.evidence_factory(request_id, prompt, intent)
        return InvestigatedEvidence(
            self.repository,
            self.extractor,
            self.team,
            UUID(self.settings.tenant_id),
            request_id,
            prompt,
            intent=intent,
        )

    def catalog(self, tenant_id: UUID, actor_id: UUID) -> dict[str, Any]:
        customer = self._customer(tenant_id, actor_id)
        registry, _, _ = self.repository.registry()
        return {
            "customer_name": next(
                c.name for c in registry.catalog.customers if c.customer_id == customer
            ),
            "equipment": [
                {"equipment_id": e.equipment_id, "name": e.label, "serial_number": e.serial_number}
                for e in registry.catalog.equipment
                if e.customer_id == customer
            ],
            "presets": [
                {"equipment_id": p.equipment_id, "prompt": p.text}
                for p in registry.catalog.presets
                if p.customer_id == customer and p.request_kind == "certificate_request"
            ],
        }

    def request(self, tenant_id: UUID, actor_id: UUID, body: CustomerRequest) -> dict[str, str]:
        self._customer(tenant_id, actor_id)
        controller = self._controller(
            body.request_id,
            body.prompt,
            CustomerRequestContext(
                customer_messages=(body.prompt,),
                equipment_id=body.equipment_id,
            ),
        )
        controller.request(tenant_id, actor_id, body.equipment_id, body.request_id)
        return controller.customer_status(tenant_id, actor_id, body.request_id)

    def message(self, tenant_id: UUID, actor_id: UUID, body: CustomerMessage) -> CustomerReply:
        from innexq_api.customer_conversation import CustomerConversation

        return CustomerConversation(self).message(tenant_id, actor_id, body)

    def confirm(self, tenant_id: UUID, actor_id: UUID, message_id: UUID) -> dict[str, str]:
        from innexq_api.customer_conversation import CustomerConversation

        return CustomerConversation(self).confirm(tenant_id, actor_id, message_id)

    def status(self, tenant_id: UUID, actor_id: UUID, request_id: UUID) -> dict[str, str]:
        return self._controller(request_id, "Certificate status").customer_status(
            tenant_id, actor_id, request_id
        )

    def coverage_progress(
        self, tenant_id: UUID, actor_id: UUID, request_id: UUID
    ) -> dict[str, Any]:
        customer = self._customer(tenant_id, actor_id)
        if self.coverage is None:
            raise KeyError(str(request_id))
        return self.coverage.progress(customer, request_id)

    def coverage_download(self, tenant_id: UUID, actor_id: UUID, request_id: UUID) -> bytes:
        customer = self._customer(tenant_id, actor_id)
        if self.coverage is None:
            raise KeyError(str(request_id))
        return self.coverage.download(customer, request_id)

    def download(self, tenant_id: UUID, actor_id: UUID, request_id: UUID) -> bytes:
        return self._controller(request_id, "Download my existing equipment certificate").download(
            tenant_id, actor_id, request_id
        )

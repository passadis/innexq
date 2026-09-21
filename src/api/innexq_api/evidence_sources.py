"""Read-only source tools for the candidate evidence broker; no policy decisions."""

import hashlib
from typing import Any

from innexq_api.certificate_repository import PrivateCertificateRepository
from innexq_api.document_extraction import DocumentIntelligenceExtractor, require_exact_fields
from innexq_api.evidence_broker import EvidenceBinding, EvidenceDenied


class CertificateEvidenceBackend:
    def __init__(
        self,
        repository: PrivateCertificateRepository,
        extractor: DocumentIntelligenceExtractor,
        policy_text: str,
    ) -> None:
        if not policy_text.strip() or len(policy_text) > 20000:
            raise ValueError("bounded standing-release policy required")
        self.repository, self.extractor = repository, extractor
        self.policy_text = policy_text
        self.policy_sha256 = hashlib.sha256(policy_text.encode()).hexdigest()

    def read(
        self, binding: EvidenceBinding, name: str, arguments: dict[str, str]
    ) -> dict[str, Any]:
        registry, version, _ = self.repository.registry()
        if version != binding.source_version or self.policy_sha256 != binding.policy_sha256:
            raise EvidenceDenied("evidence source version changed")
        equipment = next(
            (
                e
                for e in registry.catalog.equipment
                if e.equipment_id == binding.equipment_id and e.customer_id == binding.customer_id
            ),
            None,
        )
        if equipment is None:
            raise EvidenceDenied("equipment outside evidence scope")
        documents = {d.document_id: d for d in registry.catalog.documents}
        permitted = {equipment.service_document_id, equipment.certificate_document_id}
        for doc_id, digest in binding.document_hashes.items():
            doc = documents.get(doc_id)
            artifact = registry.artifacts.get(doc_id)
            if (
                doc_id not in permitted
                or doc is None
                or doc.customer_id != binding.customer_id
                or artifact is None
                or artifact.sha256 != digest
            ):
                raise EvidenceDenied("document outside evidence scope or changed")
        payload: dict[str, Any]
        if name == "get_equipment_record":
            payload = {
                "source_version": version,
                "equipment": equipment.model_dump(mode="json"),
                "in_service": registry.in_service.get(equipment.equipment_id),
                "certificate_revoked": registry.revoked.get(
                    equipment.certificate_document_id or ""
                ),
            }
        elif name == "list_equipment_documents":
            payload = {
                "source_version": version,
                "documents": [
                    {"document_id": doc_id, "kind": documents[doc_id].kind, "sha256": digest}
                    for doc_id, digest in binding.document_hashes.items()
                ],
            }
        elif name == "retrieve_policy":
            # Fixed applicable owner-approved policy, not a Search/IQ query or a
            # model-authored policy. The query cannot expand the source allowlist.
            payload = {
                "source_id": "certificate-release-policy-v1",
                "sha256": self.policy_sha256,
                "text": self.policy_text,
            }
        elif name == "analyze_document":
            doc_id = arguments["document_id"]
            if doc_id not in binding.document_hashes:
                raise EvidenceDenied("document outside evidence scope")
            document, artifact = documents[doc_id], registry.artifacts[doc_id]
            if (
                document.kind == "service_report"
                and document.valid_until != equipment.service_valid_until
            ):
                raise EvidenceDenied("service record conflicts with document")
            pdf = self.repository.read(binding.customer_id, artifact)
            extraction = self.extractor.extract(
                pdf,
                document_id=doc_id,
                document_version=artifact.document_version,
                expected_sha256=artifact.sha256,
            )
            if (
                extraction.document_id != doc_id
                or extraction.sha256 != artifact.sha256
                or extraction.document_version != artifact.document_version
            ):
                raise EvidenceDenied("extraction provenance mismatch")
            expected = {
                "Document ID": doc_id,
                "Customer ID": binding.customer_id,
                "Equipment ID": binding.equipment_id,
                "Recorded serial number": equipment.serial_number,
                "Issued on": document.issued_on.isoformat(),
                "Valid until": document.valid_until.isoformat(),
            }
            if document.kind == "service_report":
                expected["Next service due"] = equipment.service_valid_until.isoformat()
            fields = require_exact_fields(extraction, expected)
            payload = {
                "document_id": doc_id,
                "document_version": artifact.document_version,
                "sha256": artifact.sha256,
                "source_version": version,
                "model_id": extraction.model_id,
                "api_version": extraction.api_version,
                "fields": [f.model_dump(mode="json") for f in fields],
            }
        else:
            raise EvidenceDenied("tool unavailable")
        current, current_version, _ = self.repository.registry()
        if current_version != version or current != registry:
            raise EvidenceDenied("evidence source changed during tool execution")
        return payload

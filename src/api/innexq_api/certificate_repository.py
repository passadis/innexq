"""Private, read-only certificate source repository. No SAS or public URLs."""

import hashlib
import re
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from azure.core.exceptions import AzureError
from innexq_contracts.certificates import CertificateArtifact
from innexq_contracts.enterprise import EnterpriseDemoCatalog
from innexq_contracts.models import StrictContract
from pydantic import StrictBool, model_validator

from innexq_api.certificates import EvidenceUnavailable


class CertificateRegistry(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    # Explicit seed convention, not a guessed timezone for real customer data.
    date_convention: Literal["UTC-inclusive-calendar-date"]
    catalog: EnterpriseDemoCatalog
    artifacts: dict[str, CertificateArtifact]
    revoked: dict[str, StrictBool | None]
    in_service: dict[str, StrictBool | None]

    @model_validator(mode="after")
    def consistent(self) -> "CertificateRegistry":
        documents = {d.document_id for d in self.catalog.documents}
        equipment = {e.equipment_id for e in self.catalog.equipment}
        if not set(self.artifacts).issubset(documents):
            raise ValueError("unknown artifact")
        if not set(self.revoked).issubset(documents) or not set(self.in_service).issubset(
            equipment
        ):
            raise ValueError("unknown status record")
        for key, artifact in self.artifacts.items():
            if key != artifact.document_id or artifact.document_version != artifact.sha256:
                raise ValueError("artifact must use its content-addressed version")
        return self


class PrivateCertificateRepository:
    def __init__(
        self,
        endpoint: str,
        container: str,
        credential: Any,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not re.fullmatch(r"[a-z0-9]{3,24}\.blob\.core\.windows\.net", parsed.hostname)
            or parsed.netloc != parsed.hostname
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", container)
            or not 3 <= len(container) <= 63
        ):
            raise ValueError("exact private Blob origin/container required")
        self.origin = f"{endpoint.rstrip('/')}/{container}"
        self.credential, self.transport = credential, transport

    def _get(self, path: str, max_bytes: int) -> tuple[bytes, str]:
        if not re.fullmatch(r"registry\.json|pdf/[0-9a-f]{64}\.pdf", path):
            raise EvidenceUnavailable("private source path is not allowlisted")
        try:
            token = self.credential.get_token("https://storage.azure.com/.default").token
            with httpx.Client(
                timeout=20, follow_redirects=False, transport=self.transport, trust_env=False
            ) as client:
                with client.stream(
                    "GET",
                    f"{self.origin}/{path}",
                    headers={"Authorization": f"Bearer {token}", "x-ms-version": "2023-11-03"},
                ) as response:
                    if response.status_code != 200 or not response.headers.get("etag"):
                        raise EvidenceUnavailable("private source unavailable")
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        if len(content) + len(chunk) > max_bytes:
                            raise EvidenceUnavailable("private source size limit")
                        content.extend(chunk)
                    return bytes(content), response.headers["etag"]
        except (httpx.HTTPError, AzureError, ValueError):
            raise EvidenceUnavailable("private source read failed") from None

    def registry(self) -> tuple[CertificateRegistry, str, datetime]:
        content, version = self._get("registry.json", 512_000)
        try:
            registry = CertificateRegistry.model_validate_json(content)
        except ValueError:
            raise EvidenceUnavailable("invalid private registry") from None
        return registry, version, datetime.now(UTC)

    def read(self, customer_id: str, artifact: CertificateArtifact) -> bytes:
        registry, _, _ = self.registry()
        document = next(
            (d for d in registry.catalog.documents if d.document_id == artifact.document_id), None
        )
        if (
            document is None
            or document.customer_id != customer_id
            or registry.artifacts.get(artifact.document_id) != artifact
        ):
            raise EvidenceUnavailable("private artifact not in customer scope")
        content, _ = self._get(f"pdf/{artifact.sha256}.pdf", 10_000_000)
        if (
            not content.startswith(b"%PDF-")
            or hashlib.sha256(content).hexdigest() != artifact.sha256
        ):
            raise EvidenceUnavailable("private artifact changed")
        return content

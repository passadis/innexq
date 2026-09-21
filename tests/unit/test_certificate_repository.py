import hashlib
from datetime import date
from typing import Any

import httpx
import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from innexq_api.certificate_repository import CertificateRegistry, PrivateCertificateRepository
from innexq_api.certificates import EvidenceUnavailable
from innexq_contracts.certificates import CertificateArtifact
from innexq_gateway.demo_catalog import build_demo_catalog
from pydantic import ValidationError

ENDPOINT = "https://innexqtest.blob.core.windows.net"
PDF = b"%PDF-1.7\nrepository unit test fixture\n%%EOF"
SHA = hashlib.sha256(PDF).hexdigest()


class Credential:
    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        assert scopes == ("https://storage.azure.com/.default",)
        return AccessToken("unit-test-placeholder", 9999999999)


def registry() -> CertificateRegistry:
    catalog = build_demo_catalog(date(2026, 9, 11))
    document = next(d for d in catalog.documents if d.kind == "certificate")
    artifact = CertificateArtifact(
        document_id=document.document_id, document_version=SHA, sha256=SHA
    )
    return CertificateRegistry(
        date_convention="UTC-inclusive-calendar-date",
        catalog=catalog,
        artifacts={document.document_id: artifact},
        revoked={document.document_id: False},
        in_service={catalog.equipment[0].equipment_id: True},
    )


def repository(
    responses: list[httpx.Response],
) -> tuple[PrivateCertificateRepository, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    return PrivateCertificateRepository(
        ENDPOINT, "certificate-sources", Credential(), transport=httpx.MockTransport(handle)
    ), requests


def source_response(data: bytes) -> httpx.Response:
    return httpx.Response(200, content=data, headers={"etag": '"v1"'})


def test_reads_exact_private_customer_pdf_with_registry_provenance() -> None:
    data = registry()
    repo, requests = repository(
        [
            source_response(data.model_dump_json().encode()),
            source_response(PDF),
        ]
    )
    artifact = next(iter(data.artifacts.values()))
    assert repo.read("DEMO-FAB", artifact) == PDF
    assert str(requests[0].url) == ENDPOINT + "/certificate-sources/registry.json"
    assert str(requests[1].url) == ENDPOINT + f"/certificate-sources/pdf/{SHA}.pdf"
    assert requests[1].headers["Authorization"].startswith("Bearer ")
    assert all(request.method == "GET" for request in requests)


def test_registry_has_aware_observation_and_etag() -> None:
    data = registry()
    repo, _ = repository([source_response(data.model_dump_json().encode())])
    loaded, etag, observed = repo.registry()
    assert loaded == data and etag == '"v1"'
    assert observed.utcoffset() is not None


@pytest.mark.parametrize("customer", ["DEMO-NW", "DEMO-ALP", "unknown", ""])
def test_foreign_or_unknown_customer_never_fetches_pdf(customer: str) -> None:
    data = registry()
    repo, requests = repository([source_response(data.model_dump_json().encode())])
    with pytest.raises(EvidenceUnavailable):
        repo.read(customer, next(iter(data.artifacts.values())))
    assert len(requests) == 1


@pytest.mark.parametrize("mutation", ["document", "version", "hash"])
def test_changed_metadata_never_fetches_pdf(mutation: str) -> None:
    data = registry()
    original = next(iter(data.artifacts.values())).model_dump()
    original[
        {"document": "document_id", "version": "document_version", "hash": "sha256"}[mutation]
    ] = "0" * 64 if mutation == "hash" else "unknown"
    artifact = CertificateArtifact.model_validate(original)
    repo, requests = repository([source_response(data.model_dump_json().encode())])
    with pytest.raises(EvidenceUnavailable):
        repo.read("DEMO-FAB", artifact)
    assert len(requests) == 1


@pytest.mark.parametrize("content", [b"%PDF-wrongbytes", b"not PDF"])
def test_changed_pdf_hash_or_signature_is_denied(content: bytes) -> None:
    data = registry()
    repo, _ = repository(
        [source_response(data.model_dump_json().encode()), source_response(content)]
    )
    with pytest.raises(EvidenceUnavailable, match="changed"):
        repo.read("DEMO-FAB", next(iter(data.artifacts.values())))


@pytest.mark.parametrize(
    "endpoint,container",
    [
        ("http://innexqtest.blob.core.windows.net", "sources"),
        (ENDPOINT + ".evil.test", "sources"),
        (ENDPOINT + "/elsewhere", "sources"),
        (ENDPOINT + "?sig=secret", "sources"),
        (ENDPOINT + "#fragment", "sources"),
        (ENDPOINT.replace("https://", "https://user:pass@"), "sources"),  # pragma: allowlist secret
        (ENDPOINT + ":443", "sources"),
        (ENDPOINT, "../sources"),
        (ENDPOINT, "a"),
        (ENDPOINT, "a" * 64),
        (ENDPOINT, "double--dash"),
    ],
)
def test_endpoint_and_container_cannot_escape_configured_origin(
    endpoint: str, container: str
) -> None:
    with pytest.raises(ValueError):
        PrivateCertificateRepository(endpoint, container, Credential())


@pytest.mark.parametrize(
    "path",
    [
        "../registry.json",
        "/registry.json",
        "registry.json?sig=x",
        "https://evil.test/pdf",
        "pdf/../../a.pdf",
        "pdf/abc.pdf",
    ],
)
def test_only_registry_and_content_addressed_pdf_paths(path: str) -> None:
    repo, requests = repository([])
    with pytest.raises(EvidenceUnavailable):
        repo._get(path, 10)
    assert requests == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(301, headers={"Location": "https://evil.test"}),
        httpx.Response(403),
        httpx.Response(404),
        httpx.Response(200, content="missing etag"),
    ],
)
def test_unavailable_source_and_redirect_do_not_continue(response: httpx.Response) -> None:
    repo, requests = repository([response])
    with pytest.raises(EvidenceUnavailable):
        repo.registry()
    assert len(requests) == 1


def test_size_limit_before_return() -> None:
    repo, _ = repository([source_response(b"x" * 11)])
    with pytest.raises(EvidenceUnavailable, match="size limit"):
        repo._get("registry.json", 10)


def test_invalid_registry_is_sanitized() -> None:
    repo, _ = repository([source_response(b'{"secret":"never echo"}')])
    with pytest.raises(EvidenceUnavailable) as error:
        repo.registry()
    assert str(error.value) == "invalid private registry" and error.value.__suppress_context__


@pytest.mark.parametrize(
    "change",
    ["unknown-artifact", "unknown-revoked", "unknown-service", "wrong-key", "non-content-version"],
)
def test_registry_cannot_rebind_metadata(change: str) -> None:
    data = registry().model_dump()
    document_id = next(iter(data["artifacts"]))
    if change == "unknown-artifact":
        data["artifacts"]["unknown"] = data["artifacts"][document_id]
    elif change == "unknown-revoked":
        data["revoked"]["unknown"] = False
    elif change == "unknown-service":
        data["in_service"]["unknown"] = True
    elif change == "wrong-key":
        data["artifacts"][document_id]["document_id"] = "wrong"
    else:
        data["artifacts"][document_id]["document_version"] = "v1"
    with pytest.raises(ValidationError):
        CertificateRegistry.model_validate(data)


def test_unknown_status_is_preserved_not_converted_to_eligible() -> None:
    data = registry().model_dump()
    data["revoked"] = {key: None for key in data["revoked"]}
    data["in_service"] = {}
    result = CertificateRegistry.model_validate(data)
    assert all(value is None for value in result.revoked.values()) and result.in_service == {}


def test_credential_and_transport_errors_are_sanitized() -> None:
    class BrokenCredential(Credential):
        def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
            raise ClientAuthenticationError("sensitive authentication detail")

    repo = PrivateCertificateRepository(ENDPOINT, "sources", BrokenCredential())
    with pytest.raises(EvidenceUnavailable) as error:
        repo.registry()
    assert "sensitive" not in str(error.value) and error.value.__suppress_context__

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("sensitive timeout detail")

    repo = PrivateCertificateRepository(
        ENDPOINT, "sources", Credential(), transport=httpx.MockTransport(fail)
    )
    with pytest.raises(EvidenceUnavailable):
        repo.registry()

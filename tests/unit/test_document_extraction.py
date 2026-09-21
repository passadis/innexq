"""No live Azure calls: transport fixtures test OCR provenance and fail-closed bounds."""

import copy
import hashlib
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from innexq_api.certificates import EvidenceUnavailable
from innexq_api.document_extraction import (
    COGNITIVE_SCOPE,
    DocumentExtraction,
    DocumentIntelligenceExtractor,
    require_exact_fields,
)
from pydantic import ValidationError

ENDPOINT = "https://innexq-di.cognitiveservices.azure.com"
LOCATION = (
    ENDPOINT + "/documentintelligence/documentModels/prebuilt-layout/analyzeResults/"
    "00000000-0000-4000-8000-000000000001?api-version=2024-11-30"
)
PDF = b"%PDF-1.7\nunit fixture; never a real certificate\n%%EOF"
SHA = hashlib.sha256(PDF).hexdigest()
POLYGON = [0.0, 0.0, 2.0, 0.0, 2.0, 1.0, 0.0, 1.0]


class Credential:
    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        assert scopes == (COGNITIVE_SCOPE,)
        return AccessToken("unit-only-placeholder", 9999999999)


class Clock:
    current = 0.0

    def now(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += seconds


def payload() -> dict[str, Any]:
    return {
        "status": "succeeded",
        "analyzeResult": {
            "apiVersion": "2024-11-30",
            "modelId": "prebuilt-layout",
            "content": "Customer ID DEMO-FAB",
            "pages": [
                {
                    "pageNumber": 1,
                    "width": 8.5,
                    "height": 11.0,
                    "unit": "inch",
                    "lines": [{"content": "Customer ID DEMO-FAB", "polygon": POLYGON}],
                }
            ],
            "tables": [
                {
                    "columnCount": 2,
                    "rowCount": 1,
                    "cells": [
                        {
                            "rowIndex": 0,
                            "columnIndex": index,
                            "content": value,
                            "boundingRegions": [{"pageNumber": 1, "polygon": POLYGON}],
                        }
                        for index, value in enumerate(["Customer ID", "DEMO-FAB"])
                    ],
                }
            ],
        },
    }


def adapter(
    responses: list[httpx.Response], **options: Any
) -> tuple[DocumentIntelligenceExtractor, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    clock = Clock()

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    return DocumentIntelligenceExtractor(
        ENDPOINT,
        Credential(),
        transport=httpx.MockTransport(handle),
        monotonic=clock.now,
        sleep=clock.sleep,
        **options,
    ), requests


def accepted(location: str = LOCATION, retry: str = "1") -> httpx.Response:
    return httpx.Response(202, headers={"Operation-Location": location, "Retry-After": retry})


def extract(extractor: DocumentIntelligenceExtractor) -> DocumentExtraction:
    return extractor.extract(
        PDF, document_id="CERT-001", document_version="v1", expected_sha256=SHA
    )


def test_real_transport_shape_and_cited_table_comparison() -> None:
    extractor, requests = adapter([accepted(), httpx.Response(200, json=payload())])
    result = extract(extractor)
    assert result.sha256 == SHA and result.document_version == "v1"
    assert result.api_version == "2024-11-30" and result.model_id == "prebuilt-layout"
    assert result.pages[0].lines[0].citation.page_number == 1
    assert len(require_exact_fields(result, {"Customer ID": "DEMO-FAB"})[0].citations) == 2
    assert requests[0].method == "POST" and requests[0].content == PDF
    assert requests[0].headers["Content-Type"] == "application/pdf"
    assert "_overload" not in str(requests[0].url) and "pages=" not in str(requests[0].url)
    assert requests[1].method == "GET" and str(requests[1].url) == LOCATION
    assert requests[1].headers["Authorization"].startswith("Bearer ")


@pytest.mark.parametrize(
    "location",
    [
        LOCATION.replace("innexq-di", "other-resource"),
        LOCATION.replace("https:", "http:"),
        LOCATION.replace("prebuilt-layout", "other-model"),
        LOCATION + "&evil=true",
        LOCATION + "#fragment",
        LOCATION.replace("2024-11-30", "2023-07-31"),
        LOCATION.replace("/analyzeResults/", "/../analyzeResults/"),
        LOCATION.replace("00000000-0000-4000-8000-000000000001", "anything"),
        LOCATION.replace("https://", "https://user:password@"),  # pragma: allowlist secret
        "",
        "/relative/result",
    ],
)
def test_result_location_is_verified_before_bearer_get(location: str) -> None:
    extractor, requests = adapter([accepted(location)])
    with pytest.raises(EvidenceUnavailable, match="untrusted"):
        extract(extractor)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://innexq-di.cognitiveservices.azure.com",
        ENDPOINT + "/path",
        ENDPOINT + "?query",
        ENDPOINT + ".evil.test",
        "https://localhost",
        ENDPOINT + ":443",
    ],
)
def test_only_exact_configured_azure_https_origin(endpoint: str) -> None:
    with pytest.raises(ValueError):
        DocumentIntelligenceExtractor(endpoint, Credential())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"deadline_seconds": 0},
        {"deadline_seconds": 301},
        {"max_pdf_bytes": 0},
        {"max_pdf_bytes": 11 * 1024 * 1024},
        {"max_response_bytes": 0},
    ],
)
def test_invalid_bounds(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        adapter([], **kwargs)


@pytest.mark.parametrize(
    "source,sha,version",
    [
        (b"not a PDF", hashlib.sha256(b"not a PDF").hexdigest(), "v1"),
        (PDF, "0" * 64, "v1"),
        (PDF, SHA, " "),
    ],
)
def test_invalid_source_never_calls_service(source: bytes, sha: str, version: str) -> None:
    extractor, requests = adapter([])
    with pytest.raises(EvidenceUnavailable):
        extractor.extract(source, document_id="doc", document_version=version, expected_sha256=sha)
    assert requests == []


def test_source_and_result_size_caps() -> None:
    extractor, requests = adapter([], max_pdf_bytes=5)
    with pytest.raises(EvidenceUnavailable):
        extract(extractor)
    assert requests == []
    extractor, _ = adapter(
        [accepted(), httpx.Response(200, content=b"x" * 100)], max_response_bytes=50
    )
    with pytest.raises(EvidenceUnavailable, match="response limit"):
        extract(extractor)


@pytest.mark.parametrize("status", [301, 302, 401, 403, 429, 500, 503])
def test_submission_is_not_retried_or_redirected(status: int) -> None:
    extractor, requests = adapter([httpx.Response(status, headers={"Location": LOCATION})])
    with pytest.raises(EvidenceUnavailable):
        extract(extractor)
    assert len(requests) == 1


def test_poll_transient_and_running_then_success() -> None:
    extractor, requests = adapter(
        [
            accepted(),
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"status": "running"}),
            httpx.Response(200, json=payload()),
        ]
    )
    assert extract(extractor).sha256 == SHA
    assert len(requests) == 4


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403),
        httpx.Response(302, headers={"Location": LOCATION}),
        httpx.Response(200, json={"status": "failed"}),
        httpx.Response(200, content="not json"),
        httpx.Response(200, json={"status": "succeeded"}),
    ],
)
def test_poll_failure_is_closed(response: httpx.Response) -> None:
    extractor, _ = adapter([accepted(), response])
    with pytest.raises(EvidenceUnavailable):
        extract(extractor)


@pytest.mark.parametrize("retry", ["999", "31", "NaN", "-1", "Thu, 11 Sep 2026"])
def test_retry_intervals_are_bounded(retry: str) -> None:
    extractor, _ = adapter([accepted(retry=retry)])
    with pytest.raises(EvidenceUnavailable):
        extract(extractor)


def test_deadline_and_poll_count_are_bounded() -> None:
    extractor, requests = adapter([accepted()], deadline_seconds=1)
    with pytest.raises(EvidenceUnavailable, match="deadline"):
        extract(extractor)
    assert len(requests) == 1
    extractor, requests = adapter(
        [accepted()] + [httpx.Response(200, json={"status": "running"})] * 120, deadline_seconds=300
    )
    with pytest.raises(EvidenceUnavailable, match="polling limit"):
        extract(extractor)
    assert len(requests) == 121


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(apiVersion="2023-07-31"),
        lambda r: r.update(modelId="prebuilt-read"),
        lambda r: r.update(pages=[]),
        lambda r: r.update(pages=r["pages"] * 21),
        lambda r: r["pages"][0].update(pageNumber=2),
        lambda r: r["pages"][0].update(lines=[]),
        lambda r: r["pages"][0].update(lines=r["pages"][0]["lines"] * 1001),
        lambda r: r["pages"][0]["lines"][0].update(polygon=[0.0] * 7),
        lambda r: r["pages"][0]["lines"][0].update(polygon=[99.0] * 8),
        lambda r: r["tables"][0].update(rowCount=1000000000),
        lambda r: r["tables"][0]["cells"][0]["boundingRegions"][0].update(pageNumber=2),
        lambda r: r.update(content="x" * 200001),
    ],
)
def test_malformed_or_excessive_provenance_is_denied(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    data = copy.deepcopy(payload())
    mutate(data["analyzeResult"])
    extractor, _ = adapter([accepted(), httpx.Response(200, json=data)])
    with pytest.raises(EvidenceUnavailable):
        extract(extractor)


def test_exact_fields_reject_missing_mismatch_and_duplicate_labels() -> None:
    extractor, _ = adapter([accepted(), httpx.Response(200, json=payload())])
    result = extract(extractor)
    for expected in [{"Missing": "x"}, {"Customer ID": "DEMO-NW"}, {"Customer ID": "demo-fab"}]:
        with pytest.raises(EvidenceUnavailable):
            require_exact_fields(result, expected)
    assert require_exact_fields(result, {"Customer  ID": " DEMO-FAB "})
    duplicate = result.model_copy(update={"fields": result.fields * 2})
    with pytest.raises(EvidenceUnavailable):
        require_exact_fields(duplicate, {"Customer ID": "DEMO-FAB"})


@pytest.mark.parametrize(
    "change",
    [
        lambda table: table.update(columnCount=3),
        lambda table: table["cells"][0].update(columnSpan=2),
        lambda table: table.update(cells=table["cells"][:1]),
    ],
)
def test_ambiguous_tables_are_not_inferred(change: Callable[[dict[str, Any]], None]) -> None:
    data = payload()
    change(data["analyzeResult"]["tables"][0])
    extractor, _ = adapter([accepted(), httpx.Response(200, json=data)])
    result = extract(extractor)
    assert result.fields == ()
    with pytest.raises(EvidenceUnavailable):
        require_exact_fields(result, {"Customer ID": "DEMO-FAB"})


def test_authentication_and_transport_failures_are_sanitized() -> None:
    class BrokenCredential(Credential):
        def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
            raise ClientAuthenticationError("sensitive upstream detail")

    extractor = DocumentIntelligenceExtractor(ENDPOINT, BrokenCredential())
    with pytest.raises(EvidenceUnavailable) as error:
        extract(extractor)
    assert "sensitive" not in str(error.value)

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sensitive network detail")

    extractor = DocumentIntelligenceExtractor(
        ENDPOINT, Credential(), transport=httpx.MockTransport(fail)
    )
    with pytest.raises(EvidenceUnavailable) as error:
        extract(extractor)
    assert "sensitive" not in str(error.value)


def test_model_rejects_nonfinite_coordinates_and_extra_authority() -> None:
    extractor, _ = adapter([accepted(), httpx.Response(200, json=payload())])
    result = extract(extractor)
    data = result.model_dump()
    data["approved"] = True
    with pytest.raises(ValidationError):
        DocumentExtraction.model_validate(data)
    with pytest.raises(EvidenceUnavailable):
        extractor._remaining(-1)


@pytest.mark.parametrize("polygon", [[0.0] * 9, [float("inf")] * 8, [True] * 8])
def test_invalid_polygon_coordinate_pairs(polygon: list[Any]) -> None:
    extractor, _ = adapter([accepted(), httpx.Response(200, json=payload())])
    data = extract(extractor).model_dump()
    data["pages"][0]["lines"][0]["citation"]["polygon"] = polygon
    with pytest.raises(ValidationError):
        DocumentExtraction.model_validate(data)


def test_line_cannot_claim_a_different_valid_page() -> None:
    extractor, _ = adapter([accepted(), httpx.Response(200, json=payload())])
    data = extract(extractor).model_dump()
    second = copy.deepcopy(data["pages"][0])
    second["page_number"] = 2
    second["lines"][0]["citation"]["page_number"] = 2
    data["pages"] = (data["pages"][0], second)
    data["pages"][0]["lines"][0]["citation"]["page_number"] = 2
    with pytest.raises(ValidationError):
        DocumentExtraction.model_validate(data)

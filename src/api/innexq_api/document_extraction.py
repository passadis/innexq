"""Bounded, read-only Azure Document Intelligence extraction of exact PDF bytes.

OCR is evidence, never authority. Callers must compare cited fields with their
trusted source registry and apply the deterministic certificate policy separately.
"""

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

import httpx
from azure.core.credentials import TokenCredential
from azure.core.exceptions import AzureError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from innexq_api.certificates import EvidenceUnavailable

API_VERSION: Literal["2024-11-30"] = "2024-11-30"
MODEL_ID: Literal["prebuilt-layout"] = "prebuilt-layout"
COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
MODEL_PATH = "/documentintelligence/documentModels/prebuilt-layout"
Text = Annotated[str, Field(strict=True, min_length=1, max_length=20_000)]
Coordinate = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class ExtractionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PageCitation(ExtractionContract):
    page_number: int = Field(strict=True, ge=1, le=20)
    polygon: tuple[Coordinate, ...] = Field(min_length=8, max_length=64)

    @model_validator(mode="after")
    def coordinate_pairs(self) -> Self:
        if len(self.polygon) % 2:
            raise ValueError("polygon must contain coordinate pairs")
        return self


class ExtractedLine(ExtractionContract):
    content: Text
    citation: PageCitation


class ExtractedPage(ExtractionContract):
    page_number: int = Field(strict=True, ge=1, le=20)
    width: float = Field(strict=True, gt=0, allow_inf_nan=False)
    height: float = Field(strict=True, gt=0, allow_inf_nan=False)
    unit: Literal["inch", "pixel"]
    lines: tuple[ExtractedLine, ...] = Field(min_length=1, max_length=1000)


class ExtractedField(ExtractionContract):
    key: Text
    value: Text
    citations: tuple[PageCitation, ...] = Field(min_length=2, max_length=40)


class DocumentExtraction(ExtractionContract):
    document_id: Text
    document_version: Text
    sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    api_version: Literal["2024-11-30"] = API_VERSION
    model_id: Literal["prebuilt-layout"] = MODEL_ID
    content: str = Field(strict=True, min_length=1, max_length=200_000)
    pages: tuple[ExtractedPage, ...] = Field(min_length=1, max_length=20)
    fields: tuple[ExtractedField, ...] = Field(max_length=1000)

    @model_validator(mode="after")
    def citations_reference_pages(self) -> Self:
        pages = {page.page_number: page for page in self.pages}
        if sorted(pages) != list(range(1, len(self.pages) + 1)):
            raise ValueError("extraction must contain every sequential page")
        citations = [line.citation for page in self.pages for line in page.lines]
        citations.extend(citation for field in self.fields for citation in field.citations)
        for page in self.pages:
            if any(line.citation.page_number != page.page_number for line in page.lines):
                raise ValueError("line belongs to another page")
        for citation in citations:
            cited_page = pages.get(citation.page_number)
            if cited_page is None or any(
                coordinate > (cited_page.width if index % 2 == 0 else cited_page.height)
                for index, coordinate in enumerate(citation.polygon)
            ):
                raise ValueError("citation is outside its source page")
        return self


def require_exact_fields(
    extraction: DocumentExtraction, expected: Mapping[str, str]
) -> tuple[ExtractedField, ...]:
    """Return source citations only for unique, exact trusted field comparisons.

    Only OCR whitespace is normalized. No case folding, fuzzy dates, model
    inference or identifier correction is permitted. Duplicate labels fail even
    when values agree. A missing table is not replaced by catalog or prose text.
    """
    matched: list[ExtractedField] = []
    for key, value in expected.items():
        fields = [field for field in extraction.fields if _space(field.key) == _space(key)]
        if len(fields) != 1 or _space(fields[0].value) != _space(value):
            raise EvidenceUnavailable("extracted document fields do not match trusted evidence")
        matched.append(fields[0])
    return tuple(matched)


def _space(value: str) -> str:
    return " ".join(value.split())


class DocumentIntelligenceExtractor:
    def __init__(
        self,
        endpoint: str,
        credential: TokenCredential,
        *,
        transport: httpx.BaseTransport | None = None,
        deadline_seconds: float = 120,
        max_pdf_bytes: int = 10 * 1024 * 1024,
        max_response_bytes: int = 4 * 1024 * 1024,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Configuration is the exact resource origin; never accept a caller URL.
        if not re.fullmatch(
            r"https://[a-z0-9][a-z0-9-]*\.cognitiveservices\.azure\.com/?", endpoint
        ):
            raise ValueError("Document Intelligence requires an exact Azure HTTPS resource origin")
        if not 1 <= deadline_seconds <= 300 or not 1 <= max_pdf_bytes <= 10 * 1024 * 1024:
            raise ValueError("invalid extraction bounds")
        if not 1 <= max_response_bytes <= 4 * 1024 * 1024:
            raise ValueError("invalid extraction response bound")
        self.endpoint = endpoint.rstrip("/")
        self.credential = credential
        self.transport = transport
        self.deadline_seconds = deadline_seconds
        self.max_pdf_bytes = max_pdf_bytes
        self.max_response_bytes = max_response_bytes
        self.monotonic, self.sleep = monotonic, sleep

    def extract(
        self, pdf: bytes, *, document_id: str, document_version: str, expected_sha256: str
    ) -> DocumentExtraction:
        """Synchronous adapter; run in a worker thread from an async HTTP route."""
        if (
            not pdf.startswith(b"%PDF-")
            or len(pdf) > self.max_pdf_bytes
            or hashlib.sha256(pdf).hexdigest() != expected_sha256
            or not document_id.strip()
            or not document_version.strip()
        ):
            raise EvidenceUnavailable("source PDF identity or integrity is invalid")
        deadline = self.monotonic() + self.deadline_seconds
        try:
            token = self.credential.get_token(COGNITIVE_SCOPE).token
            with httpx.Client(
                transport=self.transport, follow_redirects=False, trust_env=False
            ) as client:
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/pdf"}
                status, response_headers, _ = self._request(
                    client,
                    "POST",
                    f"{self.endpoint}{MODEL_PATH}:analyze?api-version={API_VERSION}"
                    "&outputContentFormat=text&stringIndexType=unicodeCodePoint",
                    headers,
                    deadline,
                    pdf,
                )
                # Do not retry POST: an ambiguous failure may already have started a billable job.
                if status != 202:
                    raise EvidenceUnavailable("document extraction submission failed")
                location = response_headers.get("operation-location", "")
                self._validate_location(location)
                for _ in range(120):
                    self._pause(response_headers, deadline)
                    status, response_headers, body = self._request(
                        client, "GET", location, headers, deadline
                    )
                    if status in {429, 502, 503, 504}:
                        continue
                    if status != 200:
                        raise EvidenceUnavailable("document extraction result unavailable")
                    result = json.loads(body)
                    if result["status"] in {"notStarted", "running"}:
                        continue
                    if result["status"] != "succeeded":
                        raise EvidenceUnavailable("document extraction did not succeed")
                    extraction = self._parse(
                        result["analyzeResult"], document_id, document_version, expected_sha256
                    )
                    self._remaining(deadline)
                    return extraction
                raise EvidenceUnavailable("document extraction polling limit exceeded")
        except (httpx.HTTPError, AzureError, ValueError, KeyError, TypeError):
            raise EvidenceUnavailable("document extraction unavailable or invalid") from None

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self.monotonic()
        if remaining <= 0:
            raise EvidenceUnavailable("document extraction deadline exceeded")
        return min(remaining, 30)

    def _request(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        headers: dict[str, str],
        deadline: float,
        content: bytes | None = None,
    ) -> tuple[int, httpx.Headers, bytes]:
        with client.stream(
            method, url, headers=headers, content=content, timeout=self._remaining(deadline)
        ) as response:
            data = bytearray()
            for chunk in response.iter_bytes():
                self._remaining(deadline)
                if len(data) + len(chunk) > self.max_response_bytes:
                    raise EvidenceUnavailable("document extraction response limit exceeded")
                data.extend(chunk)
            return response.status_code, response.headers, bytes(data)

    def _pause(self, headers: httpx.Headers, deadline: float) -> None:
        retry = headers.get("retry-after", "1")
        if not re.fullmatch(r"\d{1,3}", retry):
            raise EvidenceUnavailable("invalid document extraction retry interval")
        seconds = max(1, int(retry))
        if seconds > 30 or seconds >= deadline - self.monotonic():
            raise EvidenceUnavailable("document extraction retry exceeds deadline")
        self.sleep(seconds)

    def _validate_location(self, location: str) -> None:
        parsed = urlsplit(location)
        if (
            f"{parsed.scheme}://{parsed.netloc}" != self.endpoint
            or parsed.fragment
            or parsed.query != f"api-version={API_VERSION}"
            or not re.fullmatch(
                re.escape(MODEL_PATH) + r"/analyzeResults/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}"
                r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                parsed.path,
            )
        ):
            raise EvidenceUnavailable("untrusted document extraction result location")

    @staticmethod
    def _parse(
        result: dict[str, Any], document_id: str, version: str, sha256: str
    ) -> DocumentExtraction:
        if not 1 <= len(result["pages"]) <= 20 or len(result.get("tables", [])) > 100:
            raise EvidenceUnavailable("document extraction structure limit exceeded")
        if any(not 1 <= len(page["lines"]) <= 1000 for page in result["pages"]):
            raise EvidenceUnavailable("document extraction line limit exceeded")
        pages = tuple(
            ExtractedPage(
                page_number=page["pageNumber"],
                width=page["width"],
                height=page["height"],
                unit=page["unit"],
                lines=tuple(
                    ExtractedLine(
                        content=line["content"],
                        citation=PageCitation(
                            page_number=page["pageNumber"], polygon=line["polygon"]
                        ),
                    )
                    for line in page["lines"]
                ),
            )
            for page in result["pages"]
        )
        fields: list[ExtractedField] = []
        for table in result.get("tables", []):
            if not 0 <= table["rowCount"] <= 1000 or len(table["cells"]) > 2000:
                raise EvidenceUnavailable("document extraction table limit exceeded")
            if table["columnCount"] != 2:
                continue
            for row in range(table["rowCount"]):
                cells = sorted(
                    (cell for cell in table["cells"] if cell["rowIndex"] == row),
                    key=lambda cell: cell["columnIndex"],
                )
                if (
                    len(cells) != 2
                    or [cell["columnIndex"] for cell in cells] != [0, 1]
                    or any(
                        cell.get("rowSpan", 1) != 1 or cell.get("columnSpan", 1) != 1
                        for cell in cells
                    )
                ):
                    continue
                fields.append(
                    ExtractedField(
                        key=cells[0]["content"],
                        value=cells[1]["content"],
                        citations=tuple(
                            PageCitation(
                                page_number=region["pageNumber"], polygon=region["polygon"]
                            )
                            for cell in cells
                            for region in cell["boundingRegions"]
                        ),
                    )
                )
        return DocumentExtraction(
            document_id=document_id,
            document_version=version,
            sha256=sha256,
            api_version=result["apiVersion"],
            model_id=result["modelId"],
            content=result["content"],
            pages=pages,
            fields=tuple(fields),
        )

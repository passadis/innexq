"""Seed synthetic Foundry IQ knowledge using Azure AI Search's GA REST API.

Review locally with --dry-run; omit it to seed the selected new Search service.
Authentication is explicitly Azure CLI or managed identity, never an API key.
Search Service Contributor and Search Index Data Contributor are needed for seeding.
Optional corpus archival requires Storage Blob Data Contributor on its container.

API references:
https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-create-knowledge-base
https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-search-index
https://learn.microsoft.com/rest/api/searchservice/documents/?view=rest-searchservice-2026-04-01
https://learn.microsoft.com/rest/api/storageservices/put-blob

GA retrieval is minimal/extractive and has no configurable reasoning-effort field.
Source URLs in the corpus are synthetic stable identifiers, not fetched web pages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from azure.core.credentials import TokenCredential
from azure.identity import AzureCliCredential, ManagedIdentityCredential

API_VERSION = "2026-04-01"
SEMANTIC_CONFIG = "innexq-semantic"
REQUIRED_IDS = {"contract", "pricing", "authority", "sla", "playbook", "template"}
FIELDS = ("id", "title", "content", "url", "version", "valid_until")
DEFAULT_CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "blob" / "phase1.json"


def endpoint_url(value: str, suffix: str) -> str:
    """Never send an Entra bearer token to an arbitrary or redirected host."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(suffix)
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Expected an HTTPS Azure service endpoint ending in {suffix}")
    return value.rstrip("/")


def resource_name(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,126}[a-z0-9]", value):
        raise ValueError("Resource names must be 3-128 lowercase letters, digits or hyphens")
    return value


def load_corpus(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"documents"}:
        raise ValueError("Expected a documents corpus object")
    raw = data["documents"]
    if not isinstance(raw, list) or not 6 <= len(raw) <= 100:
        raise ValueError("The Phase 1 corpus requires 6-100 synthetic documents")
    documents: list[dict[str, str]] = []
    ids: set[str] = set()
    for document in raw:
        if not isinstance(document, dict) or set(document) != set(FIELDS):
            raise ValueError("Unexpected corpus document fields")
        if any(not isinstance(document[key], str) or not document[key].strip() for key in FIELDS):
            raise ValueError("Corpus fields must be nonempty strings")
        if document["id"] in ids or not re.fullmatch(r"[a-z0-9-]+", document["id"]):
            raise ValueError("Duplicate or invalid document ID")
        if not document["content"].startswith("SYNTHETIC HACKATHON FIXTURE."):
            raise ValueError("Only explicitly synthetic fixture documents may be seeded")
        if not document["url"].startswith("https://schemas.innexq.invalid/corpus/"):
            raise ValueError("Corpus source identifiers must remain explicitly synthetic")
        valid_until = datetime.fromisoformat(document["valid_until"].replace("Z", "+00:00"))
        if valid_until.tzinfo is None or valid_until <= datetime.now(UTC):
            raise ValueError("Expired or timezone-naive corpus validity")
        ids.add(document["id"])
        documents.append(document)
    if not REQUIRED_IDS <= ids:
        raise ValueError("A required Phase 1 evidence document is missing")
    return documents


def definitions(index: str, source: str, knowledge_base: str) -> dict[str, Any]:
    """Return the reviewed GA Search resource definitions, without SDK guesswork."""
    fields: list[dict[str, Any]] = []
    for name in FIELDS:
        field: dict[str, Any] = {
            "name": name,
            "type": "Edm.DateTimeOffset" if name == "valid_until" else "Edm.String",
            "retrievable": True,
            "searchable": name in ("title", "content"),
            "filterable": name in ("id", "version", "valid_until"),
        }
        if name == "id":
            field["key"] = True
        fields.append(field)
    return {
        "index": {
            "name": resource_name(index),
            "fields": fields,
            "semantic": {
                "defaultConfiguration": SEMANTIC_CONFIG,
                "configurations": [
                    {
                        "name": SEMANTIC_CONFIG,
                        "prioritizedFields": {
                            "titleField": {"fieldName": "title"},
                            "prioritizedContentFields": [{"fieldName": "content"}],
                        },
                    }
                ],
            },
        },
        "source": {
            "name": resource_name(source),
            "kind": "searchIndex",
            "description": "InnexQ Phase 1 synthetic Contract Renewal evidence only",
            "searchIndexParameters": {
                "searchIndexName": index,
                "semanticConfigurationName": SEMANTIC_CONFIG,
                "searchFields": [{"name": "title"}, {"name": "content"}],
                "sourceDataFields": [{"name": name} for name in FIELDS],
            },
        },
        "knowledge_base": {
            "name": resource_name(knowledge_base),
            "description": "InnexQ synthetic Phase 1 corpus; GA minimal extractive retrieval",
            "knowledgeSources": [{"name": source}],
        },
    }


def request_json(
    client: httpx.Client,
    credential: TokenCredential,
    method: str,
    url: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    response = client.request(
        method,
        url,
        params={"api-version": API_VERSION},
        headers={
            "Authorization": f"Bearer {credential.get_token('https://search.azure.com/.default').token}",
            "Prefer": "return=representation",
        },
        json=body,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError("Search returned an unexpected response shape")
    return result


def archive_corpus(
    client: httpx.Client,
    credential: TokenCredential,
    account: str,
    container: str,
    name: str,
    payload: bytes,
) -> str:
    account = endpoint_url(account, ".blob.core.windows.net")
    resource_name(container)
    if not name or name.startswith("/") or ".." in name.split("/"):
        raise ValueError("Invalid corpus blob name")
    url = f"{account}/{container}/{quote(name, safe='/')}"
    headers = {
        "Authorization": f"Bearer {credential.get_token('https://storage.azure.com/.default').token}",
        "x-ms-version": "2023-11-03",
        "x-ms-date": format_datetime(datetime.now(UTC), usegmt=True),
    }
    response = client.put(
        url,
        headers={
            **headers,
            "Content-Type": "application/json",
            "x-ms-blob-type": "BlockBlob",
            "If-None-Match": "*",
        },
        content=payload,
    )
    if response.status_code == 412:
        # A repeated seed can reuse identical bytes, but cannot overwrite old evidence.
        existing = client.get(url, headers=headers)
        existing.raise_for_status()
        if existing.content != payload:
            raise RuntimeError(
                "Corpus blob exists with different bytes; choose a new versioned name"
            )
    else:
        response.raise_for_status()
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search-endpoint", required=True)
    parser.add_argument("--auth", choices=("cli", "managed"), default="cli")
    parser.add_argument("--tenant-id", help="Required tenant for explicit Azure CLI authentication")
    parser.add_argument("--managed-identity-client-id")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--index-name", default="innexq-phase1")
    parser.add_argument("--source-name", default="innexq-phase1-source")
    parser.add_argument("--knowledge-base-name", default="innexq-phase1")
    parser.add_argument("--blob-account-url")
    parser.add_argument("--blob-container", default="corpus")
    parser.add_argument("--blob-name", help="Optional archive name; defaults to the corpus SHA-256")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and print without Azure calls"
    )
    args = parser.parse_args()
    endpoint = endpoint_url(args.search_endpoint, ".search.windows.net")
    documents = load_corpus(args.corpus)
    payload = json.dumps({"documents": documents}, sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )
    digest = hashlib.sha256(payload).hexdigest()
    resources = definitions(args.index_name, args.source_name, args.knowledge_base_name)
    if args.blob_name and not args.blob_account_url:
        parser.error("--blob-name requires --blob-account-url")
    if args.dry_run:
        print(
            json.dumps(
                {
                    "resources": resources,
                    "document_ids": sorted(REQUIRED_IDS),
                    "corpus_sha256": digest,
                },
                indent=2,
            )
        )
        return
    credential: AzureCliCredential | ManagedIdentityCredential
    if args.auth == "managed":
        credential = ManagedIdentityCredential(client_id=args.managed_identity_client_id)
    else:
        if not args.tenant_id:
            parser.error("--tenant-id is required with --auth cli")
        credential = AzureCliCredential(tenant_id=args.tenant_id)
    with credential, httpx.Client(timeout=60, follow_redirects=False) as client:
        archive = None
        if args.blob_account_url:
            archive = archive_corpus(
                client,
                credential,
                args.blob_account_url,
                args.blob_container,
                args.blob_name or f"phase1/{digest}.json",
                payload,
            )
        request_json(
            client,
            credential,
            "PUT",
            f"{endpoint}/indexes('{args.index_name}')",
            resources["index"],
        )
        uploaded = request_json(
            client,
            credential,
            "POST",
            f"{endpoint}/indexes('{args.index_name}')/docs/search.index",
            {"value": [{"@search.action": "upload", **document} for document in documents]},
        )
        results = uploaded.get("value", [])
        if (
            not isinstance(results, list)
            or len(results) != len(documents)
            or any(not isinstance(item, dict) or item.get("status") is not True for item in results)
            or {item.get("key") for item in results} != {doc["id"] for doc in documents}
        ):
            raise RuntimeError("One or more corpus documents were not indexed successfully")
        request_json(
            client,
            credential,
            "PUT",
            f"{endpoint}/knowledgesources('{args.source_name}')",
            resources["source"],
        )
        request_json(
            client,
            credential,
            "PUT",
            f"{endpoint}/knowledgebases('{args.knowledge_base_name}')",
            resources["knowledge_base"],
        )
    print(
        json.dumps(
            {
                "knowledge_base": args.knowledge_base_name,
                "documents_indexed": len(documents),
                "corpus_sha256": digest,
                "archive_url": archive,
            }
        )
    )


if __name__ == "__main__":
    main()

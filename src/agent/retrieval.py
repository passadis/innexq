"""Read-only GA Foundry IQ REST adapter, isolated from the model and executor."""

from typing import Any

import httpx
from azure.core.credentials import TokenCredential

from contracts import Citation

API_VERSION = "2026-04-01"


def parse_references(payload: dict[str, Any]) -> list[Citation]:
    """Partial results, source errors and empty evidence are always blocking."""
    if payload.get("error") or any(item.get("error") for item in payload.get("activity", [])):
        raise ValueError("Foundry IQ returned an evidence error")
    citations = []
    for reference in payload.get("references", []):
        if reference.get("type") != "searchIndex":
            raise ValueError("Unexpected knowledge source type")
        source = reference.get("sourceData", {})
        citations.append(
            Citation(
                source_id=source["id"],
                title=source["title"],
                excerpt=source["content"],
                url=source["url"],
            )
        )
    if not citations:
        raise ValueError("Foundry IQ returned no source evidence")
    return citations


async def retrieve(
    credential: TokenCredential,
    endpoint: str,
    knowledge_base: str,
    source_name: str,
    query: str,
) -> list[Citation]:
    token = credential.get_token("https://search.azure.com/.default").token
    async with httpx.AsyncClient(timeout=70, follow_redirects=False) as client:
        response = await client.post(
            f"{endpoint}/knowledgebases('{knowledge_base}')/retrieve",
            params={"api-version": API_VERSION},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "intents": [{"type": "semantic", "search": query}],
                "includeActivity": True,
                "maxRuntimeInSeconds": 60,
                "maxOutputSizeInTokens": 12000,
                "knowledgeSourceParams": [
                    {
                        "kind": "searchIndex",
                        "knowledgeSourceName": source_name,
                        "includeReferences": True,
                        "includeReferenceSourceData": True,
                    }
                ],
            },
        )
        if response.status_code != 200:
            raise ValueError(f"Foundry IQ retrieval failed with HTTP {response.status_code}")
        return parse_references(response.json())

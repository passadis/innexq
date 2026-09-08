# ADR-010: GA Foundry IQ knowledge-base adapter

Status: Accepted in the owner-approved Phase 1 plan on 2026-09-07.

Provision one synthetic search index, one search-index knowledge source and one
knowledge base through Azure AI Search REST API 2026-04-01. This GA surface is
extractive: the Hosted Agent reasons over returned evidence. It does not provide
preview query planning, answer synthesis or configurable reasoning effort. Those
capabilities must not be claimed or enabled silently.

The corpus is explicitly synthetic. The seed operator uploads immutable Blob
source material and populates the index; the Hosted Agent has read-only Search
RBAC, not ingestion permissions. The controller checks citations and deterministic
business truth before making an executable brief. Search results are evidence,
not instructions or authorization. Permission failures and evidence gaps stop.

The approved service SKU is Free. Incoming Search RBAC supports any tier and
Sweden Central supports Free agentic retrieval. A Search-owned outbound managed
identity requires Basic or higher, however. On 2026-09-08 the owner approved
continuing with Free and removing the unused outbound identity/model role.
Terraform now implements that correction. Incoming Hosted Agent RBAC remains
unchanged. No replacement key credential or tier upgrade is authorized.

References:

- [GA and preview distinctions](https://learn.microsoft.com/en-us/azure/search/whats-new)
- [Knowledge-base API](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-create-knowledge-base)
- [Incoming role-based access](https://learn.microsoft.com/en-us/azure/search/search-security-rbac)
- [Regional Free-tier support](https://learn.microsoft.com/en-us/azure/search/search-region-support)
- [Outbound managed identity requirements](https://learn.microsoft.com/en-us/azure/search/search-how-to-managed-identities)

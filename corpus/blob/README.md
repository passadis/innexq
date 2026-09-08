# Phase 1 synthetic Foundry IQ corpus

`phase1.json` contains six explicitly synthetic Contract Renewal documents. The
minimal slice uses a 12-month term and unchanged Gold service level. This is not
a commercial offer or evidence of real customer terms.

The `url` fields are stable synthetic identifiers in the reserved `.invalid`
domain, not public pages or claims of third-party attribution. Resolve an ID to
its exact document in this repository or the private archived corpus blob.
`version` and `valid_until` accompany the retrieved content for evidence checks.
The controller must reject missing, conflicting, expired or inaccessible evidence.

`scripts/seed_knowledge.py` creates a Search index, uploads these documents and
creates the Foundry IQ search-index knowledge source and knowledge base using
the GA `2026-04-01` API. It uses minimal extractive retrieval; query planning and
answer synthesis are not enabled. The script's `--dry-run` validates the corpus
and prints resource definitions without contacting Azure.

Optional private Blob archival uses a content-addressed name by default. Repeated
seeding accepts an identical existing archive but never overwrites different
content. Corpus seeding uses the operator's explicitly selected Entra identity;
the Hosted Agent needs only Search Index Data Reader at runtime.

Sources: [GA knowledge-base creation](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-create-knowledge-base),
[search-index knowledge sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-search-index),
[retrieve API](https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-retrieve).

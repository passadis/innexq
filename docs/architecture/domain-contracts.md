# Domain contract conventions

Version 1 contracts are immutable Pydantic models under `src/contracts/innexq_contracts` and generated JSON schemas under `src/contracts/schemas/v1`.

- Unknown fields are rejected to prevent silent contract drift.
- Contract timestamps must be timezone-aware and are normalized to UTC in canonical JSON.
- IDs are UUIDs unless the upstream authority defines a stable business identifier.
- Hashes are lowercase 64-character SHA-256 hex values.
- Monetary/calculated values are deterministic tool outputs represented without binary floating-point arithmetic.
- An Action Manifest accepts only the three MVP action types.
- `actor_context` records retrieval identity context without embedding credentials.

Schema changes that break consumers require a new schema version rather than an in-place change.

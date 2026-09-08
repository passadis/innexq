# ADR-003: Deterministic gateway facts override model output

- **Status:** Accepted
- **Date:** 2026-08-30

## Decision

The contract register, asset and service records, pricing calculations, margin calculations and authority checks are versioned deterministic tools. Their normalized outputs are authoritative over generated prose.

## Consequences

Disagreement, missing data or stale/conflicting sources produces an Evidence Hold. No financial arithmetic or authority decision is accepted from model output.

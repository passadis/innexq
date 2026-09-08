# ADR-006: Cosmos DB event-oriented Run state and idempotent transitions

- **Status:** Accepted
- **Date:** 2026-08-30

## Decision

Use Cosmos DB in later phases for the Run aggregate, append-only Run Events, brief versions, approvals and idempotency records. State changes require optimistic concurrency and an allowed transition.

## Consequences

Retries and duplicate callbacks must be observable and must not duplicate actions. The event log is append-only; current state is a controlled projection, not agent memory.

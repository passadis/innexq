# ADR-004: Approval binds to an immutable brief and action manifest

- **Status:** Accepted
- **Date:** 2026-08-30

## Decision

Compute SHA-256 over UTF-8 canonical JSON containing the Decision Brief and Action Manifest. Approval records the exact brief version and hash. Any edit creates a new version and invalidates the prior approval.

Canonical JSON uses sorted object keys, compact separators, preserved list order, explicit nulls and JSON-mode model serialization. Contracts prohibit binary/non-JSON values; monetary values are decimal strings.

## Consequences

The controller must reject version/hash mismatch before execution. An action's `artifact_hash` identifies that action's generated content and is distinct from the approval envelope hash, avoiding a circular hash definition.

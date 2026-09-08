# ADR-007: Graph mutations are isolated behind the approved executor

- **Status:** Accepted
- **Date:** 2026-08-30

## Decision

Retrieval surfaces and the hosted agent receive no SharePoint-write or mail-send capability. An isolated controller path may execute only allowlisted manifest actions after validating state, hash, verified actor authority and idempotency.

## Consequences

Graph permission grants must be the minimum required and separately reviewed. A Run Event is written for every denial, attempted duplicate and execution outcome.

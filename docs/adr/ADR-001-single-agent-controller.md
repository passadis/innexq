# ADR-001: One hosted agent with a deterministic workflow controller

- **Status:** Accepted
- **Date:** 2026-08-30

## Decision

Use one Foundry Hosted Agent for retrieval planning and evidence synthesis. A deterministic controller exclusively owns durable state, transition guards, approval validation and execution eligibility.

## Consequences

The agent may recommend but cannot mutate Run state or contact customers. Multi-agent topology is excluded until a concrete requirement justifies a superseding ADR.

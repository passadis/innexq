# ADR-005: Container Apps hosts experience and controller

- **Status:** Accepted
- **Date:** 2026-08-30

## Decision

Host `innexq-web` and `innexq-api` in Azure Container Apps. Host agent code in Microsoft Foundry Agent Service. Keep the deterministic gateway inside the API for the MVP unless isolation or independent scaling proves necessary.

## Consequences

Azure Functions, AKS and additional middleware are not introduced for the business workflow. Phase 0 creates configuration placeholders only and performs no deployment.

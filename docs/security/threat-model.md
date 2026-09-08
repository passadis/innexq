# Phase 0 threat model

| Threat | Required control |
|---|---|
| Prompt or retrieved content requests an external action | Agent has no mutation tool; executor accepts only controller-created allowlisted manifests. |
| Browser claims an approver role | Resolve actor and scenario role server-side from Entra identity and authoritative mapping. |
| Brief is edited after approval | Re-version and re-hash; stored approval no longer matches. |
| Duplicate callback or retry | Idempotency key and completed-action record prevent repeated writes. |
| Unauthorized/restricted evidence | Do not expose content; record an inaccessible gap and enter Evidence Hold. |
| Model invents a value or action | Validate strict schemas; deterministic gateway remains authoritative; reject unknown action types. |
| Cross-user work context leakage | Work IQ is delegated/OBO and retrieval records actor context. |
| Telemetry leaks source/customer content | Structured allowlist logging and redaction; no default prompt/body logging. |
| Credential is committed | Ignore local secret files and run secret scanning locally and in CI. |

Phase 1 must expand this model with concrete Entra registrations, Graph permissions, network boundaries, Cosmos authorization and abuse cases before deployment.

# Configuration conventions

## Sources and precedence

1. Code contains safe, non-sensitive defaults only.
2. Local development may use an uncommitted `.env` derived from `.env.example`.
3. CI uses short-lived workload identity and protected environment values.
4. Azure Container Apps receives non-secret settings as environment variables and accesses Azure services with managed identity.
5. Unavoidable secrets are referenced from Key Vault; secret values never pass through `azure.yaml`, Terraform variables, source files, logs or outputs.

Application variables use the `INNEXQ_` prefix and upper snake case. `AZURE_*` names are reserved for `azd`/Azure tooling. Terraform consumes `AZURE_ENV_NAME`, `AZURE_LOCATION` and `AZURE_SUBSCRIPTION_ID` through `infra/main.tfvars.json`; no concrete subscription or region is committed.

## Environment rules

- `local`: synthetic fixtures, no live external writes.
- `dev`: synthetic or explicitly approved test data; writes limited to designated test surfaces.
- `demo`: replayable synthetic tenant data; reset is authenticated and environment-gated.
- No production environment is defined for the hackathon MVP.

Configuration must fail closed when an execution dependency, identity or allowlist is absent. Feature flags may disable integrations but may not bypass approval, evidence or state guards.

## Telemetry

Log correlation IDs, stable identifiers, state transitions, verdicts, hashes, durations and safe error categories. Do not log access tokens, prompts, evidence excerpts, source content, customer-language drafts or email bodies by default.

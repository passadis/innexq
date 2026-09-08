# InnexQ hosted agent

One Python 3.12 container exposes the Foundry Responses protocol. It has precisely
two read-only tools: Foundry IQ evidence retrieval and a controller-bound pricing /
authority call. There are no Graph, state-mutation, approval or execution tools.

The model chooses six exact source citations and an extractive summary copied
verbatim from one citation. The middleware buffers output until tool success and
provenance checks pass. The controller independently verifies those citations,
eligibility, freshness and financial rules before constructing any approval.
Synthetic corpus URLs are internal provenance identifiers, not live document links.

## Reproducible offline verification

From the repository root:

```console
uv run --directory src/agent --frozen python -m pytest
uv run --directory src/agent --frozen ruff check .
uv run --directory src/agent --frozen ruff format --check .
```

This is a separate uv project, not part of the API environment. `--directory`
matters: `--project` alone does not change pytest's working directory. Tests use
offline transport doubles and are not evidence of a successful live model Run.

`uv.lock` fixes transitive dependencies. `requirements.txt` is the hash-locked,
runtime-only export consumed by the non-root Docker image. After intentional
dependency changes regenerate it with:

```console
uv export --project src/agent --frozen --no-dev --no-emit-project --format requirements-txt --output-file src/agent/requirements.txt
```

## Deployment contract

The root `azure.yaml` owns the single `innexq-agent` service. Terraform owns the
approved Foundry project/model; do not add a competing provisioning service.
The container path preserves the repository's Python 3.12 requirement.
`FOUNDRY_PROJECT_ENDPOINT` is injected by the platform and must not be overridden.
Other environment values resolve from approved Terraform / azd outputs.
`INNEXQ_API_AUDIENCE` receives the `api://<client-id>/.default` scope, while the API
validates the v2 token's GUID audience.

Foundry supplies a dedicated agent identity at deployment. Grant that actual
identity only Search Index Data Reader on this Search service and the API's
`Pricing.Read` application role. Never grant Graph writes, Cosmos writes or the
executor identity to it. Verify actual deployed identity and role assignments
before enabling workflow readiness. No credential is stored in this source tree.

The Python hosting integration is prerelease; the lock and tests intentionally
contain its compatibility risk. A representative local invocation against the
real project, deployed smoke test and three governed Runs remain deployment gates.

Primary references checked 2026-09-08:

- [Agent Framework Foundry hosting](https://learn.microsoft.com/en-us/agent-framework/hosting/foundry-hosted-agent)
- [Hosted agent azure.yaml reference](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/azure-yaml-reference)
- [Foundry agent identity](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agent-identity)

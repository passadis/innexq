# InnexQ Control Room

Deployed 2026-09-08: [Open Control Room](https://ca-innexq-dev-web.delightfulstone-498e0b81.swedencentral.azurecontainerapps.io/).
Use `superuser@alfacloud.gr`. Live health, security headers and PKCE popup are
verified; the owner confirms the UI works.

Read-only React/TypeScript/Fluent UI experience for the real Run store. Sign-in
uses MSAL v5 authorization code + PKCE, a dedicated `/redirect.html` bridge and
memory-only token caching. The browser requests only `Runs.Read`; the API still
checks tenant, user and ownership. No approval, reset, assembly, Graph or Search
call is made by this application. Viewing a Run never re-executes it.

## Verify

Node.js 24 is required. From the repository root:

```powershell
npm ci --prefix src/web --ignore-scripts
npm run verify --prefix src/web
uv run python scripts/tasks.py verify
```

TypeScript contracts are generated from the Pydantic v1 JSON schemas. After a
deliberate domain change, run `npm run contracts --prefix src/web` and review the
generated diff. `contracts:check` fails on drift. Browser/component fixture data
exists only in tests; no sample/live switch or auth bypass is shipped.

## Hosting and configuration

The multi-stage Dockerfile builds assets and runs a non-root Node static server
with no production npm dependencies. Only static assets, `/config.json` and
`/health/live` are served. It is not an API proxy. API authorization remains the
security boundary; the public sign-in shell contains no Run data.

Runtime variables: `INNEXQ_WEB_TENANT_ID`, `INNEXQ_WEB_CLIENT_ID`,
`INNEXQ_WEB_API_ORIGIN`, `INNEXQ_WEB_API_SCOPE` (the API's exact `Runs.Read` scope).
These are public configuration, never credentials. Terraform owns the production
Entra registration, exact redirect URI, API origin/CORS and image-pull-only web
identity. Do not add wildcard origins, Graph permissions, or use the executor's
identity. No localhost redirect is granted in the live registration.

When deploying an explicit image with `azd deploy --from-package`, first push the
validated tag to ACR and verify its registry digest. The command can report success
for a revision whose image is absent; always verify the latest **ready** revision
and application endpoints, not just the deployment command exit status.

## Acceptance boundaries

The UI shows persisted current brief content and version/hash, evidence identity,
policy/calculation provenance, exact action parameters, event history and receipts.
It does not calculate commercial values or claim to cryptographically reverify
them in the browser. Mail accepted by Graph is not proof of delivery. All business
data is synthetic. Work IQ, delegated source ACL enforcement, exception routing,
translations and a full WCAG audit remain separate increments.

Compact Teams cards link to the exact Run/version/hash decision. Invalid, missing
or stale links do not silently substitute another decision. New HTML email actions
have an isolated, non-interactive layout preview and expandable exact source.
The navy/teal InnexQ text wordmark needs no remote image; the labelled document
button uses normal SharePoint permissions, not anonymous sharing. Rendering occurs
before hashing and approval. Legacy Text actions stay Text and are never resent.

References: [MSAL bridge](https://learn.microsoft.com/en-us/entra/msal/javascript/browser/redirect-bridge),
[MSAL initialization](https://learn.microsoft.com/en-us/entra/msal/javascript/browser/initialization).

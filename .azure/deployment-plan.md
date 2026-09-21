# InnexQ Azure Deployment Plan

## ADR-017 supervised customer pilot — 2026-09-20

Status: Pilot deployed and healthy; owner-confirmed customer acceptance recorded.
The owner subsequently approved a procedural demo freeze and presentation prep.
See [accepted baseline](../docs/demo/ACCEPTED-BASELINE-2026-09-20.md) and
[demo runbook](../docs/demo/README.md). No locks, release tag or deployment were
created by that documentation-only freeze.
Owner explicitly approved enabling v6 for the
supervised Customer Portal pilot after three fresh isolated evidence passes.
Same AzureDev / Sweden Central / innexq-dev, existing images and identities.
Recipe: azd + Terraform. Change only the API's certificate version 3 -> 6 and
evidence-runtime flag false -> true. Broker remains true. No new resources,
permissions, policy changes, source resets or Customer Portal deployment.

- [x] Validate exact plan, existing roles, health and unchanged policy findings.
- [x] Apply only reviewed API settings; retain v3 and accepted images for rollback.
- [x] Verify readiness and fail-closed agent-only MCP access.
- [x] Owner confirms authenticated customer release/hold/Operations acceptance.

This accepts the supervised certificate pilot, not every expansion workflow.
Rollback: certificate version 3, evidence runtime false; broker may stay staged.
The approved source/ownership rules and all human-approval boundaries remain.

### 7. Pilot validation proof

Preparation: v6 active, same approved principal. Full verification passes (1,029
tests); actual framework tool-loop and malformed/forged-output tests pass.
Three fresh sequential DEMO-PT-001 evidence-only attempts each produced five
controller-verified receipts including both actual PDF extractions:
`b8bac3ee-2f33-4eee-ba44-890ff8937b23`,
`3028675f-c1f0-4128-89fc-f679597b212c`,
`64a3cd26-5ef9-4796-a20f-1f38db7f151b`.
No business records or source data were reset/deleted and no receipt was reused.
Three sampled v6 session log windows contained zero scope-shaped matches. This
is a bounded log check, not certification of all upstream storage/telemetry.
Anonymous MCP=401, delegated Operations MCP=403; API/employee health=200.

Candidate agent image:
`acrinnexq40f415af.azurecr.io/innexq/innexq-certificate-team-innexq-dev:azd-deploy-1789874942`.
API revision `ca-innexq-dev-api--azd-1789849978`, image
`innexq-api:evidence-tools-1789849541`, digest
`sha256:9680557ec1374836a59f77aa6205c01de5d68e235cbea6b3002dc79314fa287f`.
Employee revision `ca-innexq-dev-web--azd-1789874224`, image
`innexq-web:evidence-tools-1789849554`, digest
`sha256:c4e764de4835434ee5b3c114855b2826046057534bf98065439b846a4d7af716`.
Customer Portal remains `ca-innexq-dev-customer--azd-1789737918` (case-progress).
Evaluation-suite setup was offered; not started without an owner choice.
Validation readback: azd auth check confirms the existing deployment identity;
preview confirms AzureDev / Sweden Central. Terraform validate passes. Saved plan
contains exactly 0 additions, 1 API update, 0 deletions. JSON review confirms only
INNEXQ_CERTIFICATE_AGENT_VERSION (3 -> 6) and INNEXQ_EVIDENCE_TOOLS_ENABLED
(false -> true) differ; image and every other setting are unchanged. Live Graph
confirms the exact Evidence.Read assignment to the approved certificate principal.
Policy readback remains 24 audit + 22 audit-if-not-exists, covered by owner acceptance.

All pilot validation checks:

- [x] Existing azd installation, environment, auth and subscription/location.
- [x] Unchanged official-schema-validated azure.yaml and Docker contexts/packages.
- [x] Terraform validate, static role scope and exact provisioning preview.
- [x] Live identity/role and accepted policy findings rechecked.
- [x] Builds and 1,029 tests pass; no app source change in this settings-only pilot.
- [x] Final secret scan completed; no potential secrets detected. Full verify passed.
- Aspire, SQL, new resources/models/capacity and image-pull changes: not applicable.

Pilot apply completed: 0 added, 1 changed, 0 destroyed. New API revision
`ca-innexq-dev-api--0000011` has certificate version=6, evidence tools=true,
broker=true and the unchanged API image. Azure reports latest=ready=0000011,
Healthy, Succeeded and 100% traffic. API and Customer Portal return 200;
anonymous MCP=401 and delegated Operations MCP=403 after cutover.

### Owner acceptance and read-only correlation — 2026-09-20

The owner reports "all actions went as planned" after the requested customer
release/hold and Operations visibility checks. Read-only Cosmos inspection on
the active API revision independently confirms these fresh requests:

| Equipment | Request | Persisted outcome |
| --- | --- | --- |
| DEMO-PT-001 | `45e314bf-5963-4764-843f-c06e947c90df` | All three checks pass; release ready and download prepared at 14:18:43 UTC. |
| DEMO-PT-002 | `0f17d100-980f-4504-8033-58eab8ad928e` | Service not current; held and Operations case created at 14:20:21 UTC. |
| DEMO-PT-003 | `f2ffdb6c-a62b-49a0-adab-779727057590` | Missing evidence; held and Operations case created at 14:20:42 UTC. |

Both held requests' Teams notification outbox records are `delivered`.
Customer browser success and Operations visibility are owner-reported; persisted
events corroborate the decisions and download preparation, not receipt of PDF
bytes by themselves. Closure-update acceptance was not separately exercised in
this pilot. This verification makes no deployment, permission or source changes
and does not reset records or impersonate a customer.

## ADR-017 controlled runtime rollout — 2026-09-19

Status: Validated for broker-only staging and immutable candidate deployment.
Owner approved controlled candidate deployment,
live identity/privacy verification and three fresh end-to-end attempts before
promotion. Same AzureDev / Sweden Central / innexq-dev and existing services.

- [x] Confirm staging switches keep accepted customer routing unchanged.
- [x] Validate packages, identity permissions, policy disposition and rollback.
- [x] Deploy candidate API MCP surface and immutable certificate-agent version.
- [ ] Verify published-agent identity, private-header handling and real MCP/OCR.
- [ ] Three fresh end-to-end attempts and negative authorization cases.
- [ ] Promote only after acceptance; record actual results and remaining gates.

No new agent identity, broad permissions, workflow authority or project-identity
fallback. Preserve accepted records, source PDFs, renewal v2 and certificate v3.
Owner accepted the unchanged 46 Azure-resource audit findings for this limited
rollout. No broader policy exemption. The earlier identity-only validation is
not application-deployment validation.

Staging: broker enabled, candidate customer routing disabled, certificate version
still 3. API MCP tools require both the assigned agent identity and a private
controller-issued scope. A local operator-only probe in the API container uses
existing separate managed identities and writes only evidence attempt receipts,
never workflow/case/release/Graph/email state. A never-issued transport marker is
used before real scopes to check logs; expected rejection alone is not proof of
transport success. Candidate agent is a new immutable version of the same agent.

All rollout validation checks pass:

- [x] Existing azd environment, auth, subscription/location and unique targets.
- [x] Official azure.yaml schema, Terraform format/validate and exact preview.
- [x] Repository checks, source builds, Docker contexts and targeted packages.
- [x] Static and live image-pull/read identity roles.
- [x] Owner disposition of existing audit findings.
- Aspire, SQL and new regional resource capacity: not applicable.

Research: retained existing Container Apps/Foundry container deployment patterns,
managed identity only and bounded scopes. No new service, model, network or SDK
upgrade. API evidence endpoint availability and customer cutover are independent.

### 7. Runtime staging validation proof

`uv run python scripts/tasks.py verify` passed: 764 API/domain, 156 agent,
104 UI and 3 server tests (1,027 total). All format/lint/types/schema/secret checks
passed. Terraform validate and official azure.yaml schema passed. API package
innexq/innexq-api-innexq-dev:azd-deploy-1789849541 and employee package
innexq/innexq-web-innexq-dev:azd-deploy-1789849554 built successfully. API packaged
probe and setup import offline; candidate agent image built and imported in the
previous validated increment, with no agent source changes since then.
Existing Foundry project and API/web identities have AcrPull; no roles changed.
Environment preflight passed (generic no-agent detection is inaccurate; direct
agent show confirms certificate v3 active and the approved principal).
Broker-only provisioning preview: 0 add, 1 API update, 0 destroy. Five evidence
environment values added, all existing values/secret references unchanged after
null/empty normalization, certificate version remains 3 and image unchanged.
No Customer Portal deployment, new identity, service or resource is in this stage.

Runtime staging applied: 0 added, 1 API changed, 0 destroyed. API candidate
`evidence-tools-1789849541` is healthy at revision `azd-1789849978`; anonymous MCP
returns 401. Broker=true, customer evidence tools=false, certificate version=3.
Certificate v4 and diagnostic v5 were deployed with the unchanged approved agent
principal. Never-issued canaries reached candidate dispatch and failed closed.
Available log samples contain no canary marker, but App Insights has no recent
rows; sampled logs do not establish platform-wide privacy. The diagnostic increment
logs a fixed phase and allowlisted
failure category, never provider bodies, headers or exception text. Local real-SDK
MCP/host roundtrip tests and all 1,028 repository tests pass with that increment.
The secret scanner flagged the literal dummy marker in a negative test; it is
explicitly annotated as non-secret and the full verification rerun passed.
No infrastructure, model, permissions, toolbox or customer routing changes.

2026-09-20 UTC live v5 evidence-only sequence: pass, fail, fail, pass. Successful
attempts `1b1b561e-4cbd-438a-a870-3e8176c67ba9` and
`59a5a3f5-5eb5-447a-8313-59318f6485a6` each have five verified receipts (discovery,
two PDF analyses, equipment and policy). Failed attempt
`054df14a-1bad-4e65-9cac-baa09db56295` also has all five receipts, but both scopes
were revoked; failure was after tool execution. Attempt
`7d6b0dc7-8c4c-4d7c-a9c7-047ad50a110c` returned a failed agent response. Three
consecutive passes are NOT met. Delegated Operations MCP access returns 403.
API and Control Room health return 200. Employee image
`innexq-web:evidence-tools-1789849554` is deployed; Customer Portal is unchanged.

Next candidate hardens the coordinator handoff: model-led branch selection stays;
code assembles exact specialist provenance from completed calls instead of asking
the model to recopy summaries/UUIDs. Public API report shape and all controller
receipt, source, scope and authorization checks remain unchanged. This removes a
known fragile copying requirement; exact cause of each v5 failure is not claimed.
Targeted actual-framework tool-loop/dispatch tests and full repository verification
pass: 764 API/domain, 158 agent, 104 UI and 3 server tests (1,029 total), including
format/lint/types/schema/build and secret scan. Existing validated infrastructure,
identity and package configuration are unchanged; new immutable agent packaging
is the only deployment delta. Candidate remains excluded from customer routing.

## ADR-017 scoped evidence MCP integration — 2026-09-19

Status: Identity-only setup deployed and verified, 2026-09-19 (validated by
azure-validate before azure-deploy). Application rollout not performed.
Owner approved the exact topology and creation
of one connection/toolbox and the certificate agent Evidence.Read grant.
Target remains AzureDev / Sweden Central / innexq-dev; recipe remains azd with
Terraform. This approval does not promote a new live agent or change certificate
release policy. Preserve all accepted images, agent versions and workflow records.

Scope: a read-only MCP adapter on the existing API process, using the existing
certificate-reader identity for sources/OCR; only the certificate agent receives
Evidence.Read. One version-pinned Foundry toolbox and agent-identity connection.
No direct Graph, Blob, Cosmos or OCR roles for the agent, project-MI fallback,
new business workflow or automatic release authority. Shared-process limitation
remains explicit. The controller issues and verifies durable request-bound scopes
and receipts, and remains the sole workflow/authorization owner.

- [x] Local SDK proof and 820-test baseline recorded in ADR-017.
- [x] Owner approved precise topology, role and connection/toolbox creation.
- [x] Implement durable broker, authenticated MCP adapter and source adapters.
- [x] Wire candidate specialists without exposing scope handles to model/telemetry.
- [x] Add scoped activity receipts and controller validation; preserve legacy path.
- [x] Verify repository and prepare exact infrastructure/configuration delta.
- [x] Azure validation and targeted identity/connection setup.
- [ ] Separate immutable candidate deployment and live acceptance before promotion.

Unproven platform gate: transport request-bound scope outside model-visible input
and verify published-agent identity forwarding. Stop on a material security or
platform mismatch; do not silently weaken the design.

Identity-only validation scope: `evidence_identity_enabled=true`, verified existing
agent principal, `evidence_runtime_enabled=false`. The plan must contain only the
API application role addition and its assignment; no API/container/agent changes,
deletions or replacement. Existing Azure-resource audit findings do not authorize
runtime rollout and are not changed by this Entra-only increment.

All identity-setup validation checks pass:

- [x] azd installation, authentication, existing environment and target verified.
- [x] Configuration/schema and Terraform format/validate checks.
- [x] Provision preview reviewed for exact Entra-only delta.
- [x] Local builds, Docker contexts and repository verification.
- [x] Static identity/role scope verification.
- [x] Policy review for the exact proposed resources.
- Aspire, SQL, regional capacity and Container Apps AcrPull changes: not applicable
  to this identity-only setup. No application images will be deployed.

### 7. ADR-017 validation proof

2026-09-19: connection `innexq-evidence` created with AgenticIdentityToken and exact
API audience. Toolbox `innexq-evidence-tools` version 1 created with only the four
allowlisted MCP tools. Foundry CLI returned the version-pinned endpoint. These are
metadata configuration only; live identity forwarding is not yet verified.
Local API Docker build passed, including MCP dependencies and the policy file.
Agent Docker build and offline imports in both images passed. No image push.
`uv run python scripts/tasks.py verify` passed: 739 API/domain, 156 agent,
104 UI and 3 server tests (1,002 total), format/lint/types/schema/TF format/build
and secret scanning. Official azure.yaml JSON-schema validation passed.
`terraform -chdir=infra validate` passed. `azd provision --preview --no-prompt`
with only the approved identity flag enabled saved a reviewed plan: 1 add,
1 update, 0 destroy; only azuread_application.api and the new evidence_read
assignment. JSON plan review confirmed Pricing.Read retained, all delegated
scopes unchanged, no Azure resource/Container App or agent changes. Deployment
login remains passadis@outlook.com on the confirmed tenant/AzureDev/Sweden Central.
Static role review: Application-only Evidence.Read -> certificate principal
0bbe2604-5ae0-4463-97ff-3d06b37a749f -> API service principal
2ca03c49-5303-472b-a231-22edea92dea4. No direct source/executor roles added.
Azure Policy query still lists 46 Azure-resource audit findings. The saved
plan modifies only Entra objects, outside those Azure resource policy targets;
no exemption or acceptance is inferred for a later application deployment.

Identity apply completed: 1 added, 1 changed, 0 destroyed. Initial direct apply
stopped before mutation because it did not select azd's local state; the same
saved plan succeeded with the existing `.azure/innexq-dev/infra/terraform.tfstate`
explicitly selected. No import, state replacement, force unlock or refresh bypass.
Live Microsoft Graph GET verified exactly the Evidence.Read assignment for the
certificate principal on the API; Pricing.Read still exists. Foundry toolbox GET
verified version 1 and all four exact tools. Container App API, employee and
customer latest-ready revisions and image tags match the accepted baseline.
Local environment persists identity enabled, evidence runtime disabled and agent
candidate flag false. No credentials, raw state or private scope handles committed.
Post-apply drift check initially proposed removing the grant: azd did not forward
the saved TF_VAR inputs unless mapped in main.tfvars.json. That preview was never
applied. Explicit mappings and a regression test were added; the next ordinary
`azd provision --preview --no-prompt` succeeded with **No changes**. Connection
metadata GET independently confirmed RemoteTool / AgenticIdentityToken and the
exact API endpoint. No project-managed-identity fallback was configured.

## ADR-016 customer-visible case progress — 2026-09-18

Status: Deployed (2026-09-18); owner confirmed live closure test 2026-09-19.
Owner accepted unchanged policy findings for this limited rollout and requested
API and Customer Portal deployment and
live closure verification. Recipe: Azure Developer CLI with Terraform.

Scope: replace only the two existing application images, API first. Preserve the
employee Control Room, agent versions, identities, roles, source documents and
all existing workflow records. No reset, new authorization, customer impersonation
or automatic Operations action. Verify live closure using the customer's own
session and an Operations action by the authorized reviewer.

All validation checks must pass:

- [x] azd installation, existing environment and authentication verified.
- [x] Existing AzureDev / Sweden Central target and unique service tags verified.
- [x] Terraform validation and provisioning preview: no changes.
- [x] Frozen Docker build contexts and package validation for both target services.
- [x] Static roles and existing API/customer AcrPull assignments verified.
- [x] Official azure.yaml schema and final repository verification.
- [x] Owner disposition of unchanged Azure Policy audit findings.
- Aspire/SQL checks not applicable. No new capacity or service is needed.

### 7. Validation proof

2026-09-18: `terraform -chdir=infra validate` passed. Authenticated deployment
profile and azd are passadis@outlook.com, tenant 35de4c50-7dcd-4871-8685-61789c017da2,
subscription c6e08b90-7ae0-4f00-8478-a1d4e73991d2. Existing environment
cae-innexq-dev is Succeeded; service tags uniquely identify the API and customer.
`azd provision --preview --no-prompt` succeeded with **No changes**.

`azd package innexq-api --no-prompt` and `azd package innexq-customer --no-prompt`
passed. Local packages: `innexq/innexq-api-innexq-dev:azd-deploy-1789736910` and
`innexq/innexq-customer-innexq-dev:azd-deploy-1789736917`.
Non-root Docker runtimes, locked dependencies and scoped Cosmos role reviewed.
API and customer identities have AcrPull at the exact ACR scope; ACR admin remains
disabled. The prior bootstrap is complete; no infrastructure delta is required.

Policy-state read still reports 24 audit and 22 auditIfNotExists noncompliant
evaluations, plus 13 compliant. No deny returned. This is a point-in-time read,
not a new compliance scan. Owner explicitly replied "Proceed with this limited
rollout"; leave these findings unchanged and track hardening separately. This is
not a policy exemption or certification. Azure validation gate is complete.

Official Microsoft Draft-7 azure.yaml schema validation returns zero errors.
`uv run python scripts/tasks.py verify` passes all 779 tests, schema/type/lint/
format checks, production build and secret scan. Network-disabled packaged API
check confirms UID 10001 and the five public status fields. Customer image uses
the node non-root user. Existing SDK preview/deprecation and bundle-size warnings
remain non-failing. No application dependency was changed by schema validation.

Pre-deployment baseline: API revision azd-1789709635; customer azd-1789709685;
employee azd-1789709704. API image conversation-20260918-v1, both web images
conversation-20260918-v1. Preserve these rollback images and all prior revisions.

### Completed rollout and live acceptance

Published tag `case-progress-20260918-v1` for both images. Registry digests matched
the validated local packages:

- API `innexq-api`: `sha256:5cd1db63ad4ca8cb20adfad288e525418f9e75499718e519c8500eb89c9e5e74`.
- Customer `innexq-web`: `sha256:221b1c86415b75d66b8b8f12c508b7451f1d77c89c88e22847a57c4eb9460c49`.

Targeted `azd deploy --from-package` succeeded for API then customer. No provision,
permission update, agent deployment, reset or Operations action was performed.
API `ca-innexq-dev-api--azd-1789737879` and customer
`ca-innexq-dev-customer--azd-1789737918` were Healthy/Provisioned with 100% traffic;
latest and latest-ready matched. Employee revision remains azd-1789709704.

`azd show` confirmed endpoints:

- https://ca-innexq-dev-api.delightfulstone-498e0b81.swedencentral.azurecontainerapps.io/
- https://ca-innexq-dev-customer.delightfulstone-498e0b81.swedencentral.azurecontainerapps.io/

API readiness returned ready. Initial customer GET timed out during revision
transition; repeat root and health reads passed (200), serving main-CllJoXKm.js
with the new closed-case and stale-status labels. Public configuration retains
the existing customer client ID and Certificates.Request scope. API and customer
AcrPull were reverified; API Cosmos Data Contributor remains scoped only to
`/dbs/innexq/colls/runs`. Customer status rejects anonymous requests (401) and
employee tokens (403); no customer identity was impersonated.

Read-only Operations checks confirmed the prior closed PT-003 request
073c9262-768f-4218-88d8-95cefd721b73 remains closed_without_release/revision 3,
with notification delivered. The other two prior case review revisions were
unchanged (1 and 0). All three baseline renewal record revisions were 15;
the follow-up nested state/hash check was not completed due to a tool usage
limit. A final read-only provisioning preview was started, but its completion
output was not recovered after the session ended; do not claim a post-deploy
no-drift result. The successful pre-deploy no-change preview remains recorded.

2026-09-19 owner reply "Yes the test works as you describe" confirms the requested
live customer-page closure update after Operations closes a new PT-003 case.
No new request ID or browser trace supplied; this is owner-reported acceptance,
not independent browser observation or three consecutive release successes.

## ADR-015 bounded customer conversation — 2026-09-17

Status: Deployed (2026-09-18); live customer/browser acceptance pending.
Owner explicitly replied "Yes deploy" to the
ADR-015 audit-finding disposition and subsequently requested continuation.
Existing audit findings remain unchanged; this is not a policy exemption or
compliance certification. API and both portals now use the new images; the API
is pinned to tested certificate Hosted version 3. Renewal remains version 2.

Scope: existing certificate Hosted team, API, Customer Portal and Control Room.
Deploy a new immutable certificate team version, smoke both packet modes, then pin
the API and update the three existing Container Apps. Preserve renewal agent v2,
all legacy Runs, identities, permissions and resources. No service booking, new
commercial workflow, email authority, policy exemption or reset is authorized.

### 7. Validation proof

- Deployment identity verified as passadis@outlook.com in AzureDev / Sweden Central.
- Existing certificate Hosted version 1 remains active; no new version yet.
- Terraform validate passes. `azd provision --preview --no-prompt` reports **No
  changes**, with no new resource, permission, replacement or deletion.
- Current policy-state read: 46 noncompliant evaluations (24 audit, 22
  auditIfNotExists), 23 distinct definitions; 13 compliant. No deny evaluation
  returned. This matches the previous counts, not proof of compliance or a fresh
  compliance scan. Owner accepted these findings unchanged for this rollout.
- Full repository verification passes: 616 API/domain, 53 agent, 93 web-client
  and 3 server tests (765 total); schemas, types, formatting, lint and secret scan
  pass. Existing SDK preview/deprecation and web bundle-size warnings remain.
- Added opt-in `src/agent/scripts/conversation_smoke.py`: real existing Foundry
  model, synthetic scoped packets, no workflow records or Microsoft 365 writes.
  Initial probe passed 10/12 interpretation cases and all three two-specialist
  investigation modes. Missing-ID and selection-conflict model outputs missed
  desired clarification; existing deterministic controller guards still fail safe.
  Clarification instruction precedence tightened; repeat probe passes all 12/12
  interpretation cases and all three investigation modes with two real specialist
  responses each. This is one finite synthetic test pass, not proof of universal
  model accuracy or live customer acceptance. Final repository verify rerun passes.
- Existing API, employee and customer host AcrPull assignments verified at the
  exact ACR scope. Foundry local/key auth is disabled and ACR admin user is disabled.

- 2026-09-18 preflight: deployment login/tenant/subscription reverified; Terraform
  validate and fresh azd preview pass with no changes. One existing healthy
  Container Apps environment and unique service tags. All four targeted azd
  packages succeed (certificate remote build is deferred to deployment).
  API package `innexq/innexq-api-innexq-dev:azd-deploy-1789708677`; employee
  package `innexq/innexq-web-innexq-dev:azd-deploy-1789708745`; customer package
  `innexq/innexq-customer-innexq-dev:azd-deploy-1789708780`.
- Container Dockerfiles/context and frozen dependency locks reviewed; application
  schema parsing succeeds through scoped azd packaging. Static source-reader,
  Cosmos and image-pull roles remain unchanged. No Aspire or SQL checks apply.
- Registry precheck: project/account connection lists remain empty, as in the
  accepted E1 baseline. Preserve the working project-managed-identity AcrPull and
  explicit ACR image path; do not add a new connection contrary to approved scope.
  Remote smoke must prove image/model access before API pinning.

Remaining acceptance: real customer/employee browser checks. Three fresh
customer certificate successes are not claimed by model probes or offline tests.

### Rollout checkpoint — 2026-09-18

Hosted version 2 is active with the same principal as v1. New conversation packet
smoke succeeds in 4.462s. Legacy investigation packet stops at the evidence guard;
the API remains pinned to v1. Doctor: 11 passed, 0 failed, 2 skipped. Investigation
found the legacy packet's default intent was validated in code but absent from
the message visible to the model. Canonicalize the validated packet (without
mutating the caller's message); add a regression test. 54 agent tests pass. Real
model smoke with the actual legacy omission is being rerun before a new version.
No authorization or evidence guard is relaxed, and v2 is not promoted to the API.

Corrected version 3 is active with the same identity. Hosted legacy-packet smoke
passes with both exact specialist proofs (34.177s); conversation smoke passes
(3.167s). Image digest
`sha256:65d2916839b40aacaf911e4353226e0d8b43998cf14e00c166f3d62cf89e5bb7`.
Real-model local regression passes all 12 intent cases and all three investigation
modes. Full verify passes 766 tests; six additional offline browser checks pass.
Evaluation-suite source offered to owner; no evaluation suite generated or run.
API pin change 1 -> 3 passed preview and apply; legacy renewal pin remains 2.

Published verified API digest:
`sha256:c41e2e8c94d00ae6b31723fffb78ec77d66a896ed49eb39573473fa7cc2cafb7`.
Shared web digest:
`sha256:883854109fe5c14d7326d1c086e7bd92ccd1c91fa1491f71baa2bb817f7480cc`.
Both use tag `conversation-20260918-v1`. Employee and customer package IDs differ
but hashes of server.mjs, index.html and all built JS/CSS files are identical.
All three accepted renewal Runs rechecked: EXECUTED, revision 15, exact original
brief hashes. No Run, approval, SharePoint file or email was modified by probes.

### Completed rollout and verification — 2026-09-18

`azd provision --no-prompt`: 0 added, 1 changed, 0 destroyed. Only API certificate
version changed from 1 to 3. Existing API/web/customer AcrPull assignments rechecked
before targeted `azd deploy --from-package` calls. All three deploys succeeded.
Latest and latest-ready match, each serving 100% latest-revision traffic:

- API `ca-innexq-dev-api--azd-1789709635`.
- Customer `ca-innexq-dev-customer--azd-1789709685`.
- Employee web `ca-innexq-dev-web--azd-1789709704`.

`azd show` confirms endpoints:

- https://ca-innexq-dev-api.delightfulstone-498e0b81.swedencentral.azurecontainerapps.io/
- https://ca-innexq-dev-customer.delightfulstone-498e0b81.swedencentral.azurecontainerapps.io/
- https://ca-innexq-dev-web.delightfulstone-498e0b81.swedencentral.azurecontainerapps.io/

API `/health/ready` returns ready. Both web roots and health endpoints return 200;
both serve `main-DIzhXWIl.js`. Public configuration retains distinct employee and
customer client IDs and Runs.Read / Certificates.Request scopes respectively.
API source-reader and executor identities unchanged. Live Cosmos role is still
Data Contributor only on `/dbs/innexq/colls/runs`; source-reader has Blob Data Reader
on certificate-sources and Cognitive Services User on Document Intelligence.
Certificate agent has no direct Azure role assignments or Graph app roles.

Using the real Operations login, all three accepted renewal Runs remain EXECUTED
at revision 15 with their original brief hashes. Existing held-case review reads
as acknowledged/revision 1, can_manage=true; this rollout submitted no case action.
Empty customer-message requests are rejected: anonymous 401, employee token 403.
No customer sign-in was impersonated. No fresh certificate release, Teams case or
email is claimed by this deployment verification. Three consecutive real-customer
certificate successes and interactive Manager/Operations acceptance remain pending.

Final post-deployment `azd provision --preview --no-prompt` succeeds with **No
changes**. No cleanup/deletion/reset was performed. Previous images and agent
versions remain available; version 2 was never promoted to the API.

## ADR-014 employee visibility and case review — 2026-09-15

Status: Deployed (2026-09-16); live Manager/Operations browser acceptance pending.

Owner explicitly approved Manager read-only access to both workflow packs and
Operations acknowledgement, internal notes and closure without release. MODIFY
the existing azd/Terraform application in AzureDev / Sweden Central. No new Azure
service, agent, model, workflow pack, customer permission or external write is added.

- API: explicit Manager object ID binding, GET-only employee access to configured
  Operations-owned Runs/cases. New `Cases.Manage` delegated permission for Operations
  only. Existing `Runs.Read` and renewal authorization remain unchanged.
- Cosmos: additive case-review snapshot plus immutable events in the existing
  certificate partition; ETag CAS, expected revision and UUID command deduplication.
  No migration, reset or replacement of existing records. Closure never releases PDF.
- Employee SPA: overview case panel plus exact-linked case actions and internal audit.
  Manager gets read-only audit; Operations requests a write token on explicit action.
- IaC delta: custom API scope, existing employee SPA preauthorization, API Manager
  binding. No Graph consent, new secret or managed identity role required.
- Planned rollout: API and employee web only, after validation and Terraform preview.
  Preserve customer image, certificate Hosted version 1 and renewal Hosted version 2.

Validation gates:

- [x] Full repository verify, schemas and new negative authorization/lifecycle tests.
- [x] Offline browser checks of Operations actions and Manager read-only behavior.
- [x] Azure context and exact Manager/Operations object IDs reverified read-only.
- [x] Terraform validate and azd provision preview; no deletion or replacement.
- [x] Owner disposition of existing audit-only Azure Policy findings: deploy this
  limited update; leave findings unchanged and track hardening separately.
- [x] Build images, verify ACR digests, scoped deployment and health/role verification.
- [ ] Real Manager/Operations browser acceptance; no claim from simulated tests.

### 7. Validation proof for ADR-014

### Deployment and live verification — 2026-09-16

`azd provision --no-prompt` completed: 0 added, 4 changed, 0 destroyed. ACR login
used the deployment user's Entra identity; admin credentials remain disabled.
Both previously verified packages were pushed and their registry digests checked:

- API `innexq-api:case-review-20260916-v1` —
  `sha256:8ffb3d725baf40894906acf3a979149a3c11dfab3bb0b3f402e570d88de7b8c3`.
- Employee web `innexq-web:case-review-20260916-v1` —
  `sha256:071ff0c29847b5bf0ed235a82dd97514ce924f8d67db9abb5a5334bd44a79765`.

Targeted `azd deploy <service> --from-package <registry-image> --no-prompt`
deployed API first (19s) then employee web (17s). Latest and latest-ready match:
`ca-innexq-dev-api--azd-1789591906` and `ca-innexq-dev-web--azd-1789592005`,
with 100% latest-revision traffic. API revision Healthy/Provisioned, readiness
returns ready. Web health and root return HTTP 200; root serves verified bundle
`main-DrIhlaBo.js`. Public web config retains the employee client, exact API origin
and `Runs.Read`; action-time `Cases.Manage` is separate.

`azd show` confirms deployed endpoints:

- https://ca-innexq-dev-api.delightfulstone-498e0b81.swedencentral.azurecontainerapps.io/
- https://ca-innexq-dev-web.delightfulstone-498e0b81.swedencentral.azurecontainerapps.io/

Live scopes/preauthorization retain all old grants and add only Cases.Manage to
the employee SPA. Customer and CLI preauthorizations remain unchanged. API/web
AcrPull and API Cosmos Data Contributor on `/dbs/innexq/colls/runs` verified.

Using the existing real Operations sign-in, read-only API checks return the one
held request `75b08b0a-76b1-4387-8886-2e0704df9dad`, review state open/revision 0,
can_manage=true. No acknowledgement/note/closure command was submitted. Anonymous
case reads return 401; an empty invalid action POST with the legacy delegated scope
returns 403 (no valid business command or authorization). All three previously
accepted renewal Runs remain EXECUTED/revision 15 with their exact baseline hashes.
Repository `verify` rerun succeeds: 691 tests and clean schema/type/lint/format/secret
checks. Earlier five offline browser tests remain the action-UI evidence; they are
not a real Manager sign-in or live action acceptance claim.

Next acceptance: sign out/in to the Control Room as Manager for read-only Runs/cases,
and as Operations to acknowledge or add an internal note to the existing held case.
Closing without release remains terminal and never makes its PDF eligible.

Final post-deployment `azd provision --preview --no-prompt` succeeds with **No
changes**. API managed identities and both agent version pins are preserved.
Customer image/revision remain `certificate-e1-v1` /
`ca-innexq-dev-customer--azd-1789118905`. No customer deployment occurred.

Deployment authorization: owner replied `deploy` to the explicit request to deploy
this limited update with existing audit findings unchanged. This is not a policy
exemption or compliance certification. Azure validation accepts that explicit owner
disposition for this rollout only; all technical validation gates below passed.

Fresh preflight on 2026-09-16 confirms Azure CLI/azd deployment identity and the same
AzureDev/Sweden Central environment. Repeated `azd provision --preview --no-prompt`
succeeds (0 add, 4 update, 0 destroy); filtered plan JSON is guarded against any
other address/action. Both API and web AcrPull assignments are visible at the ACR
scope. Previously verified local packaged images remain available; customer image
and ready revision match the pre-rollout baseline. No source change since verify.

2026-09-15 local verification: 572 API/domain, 41 agent, 75 UI/client and 3 server
tests pass (691 total), with 97.48% API/domain coverage. Schema synchronization,
typing, lint and formatting pass. Five offline Edge tests pass, including mobile
Operations acknowledgement/note/closure, Manager read-only audit and existing
customer download/held-case surfaces. Browser artifacts: `.test-artifacts/case-review-20260915`.

Read-only identity check: Azure CLI and azd use passadis@outlook.com / AzureDev
`c6e08b90-7ae0-4f00-8478-a1d4e73991d2`, existing Sweden Central environment.
Microsoft Graph v1.0 exact object-ID reads confirm Manager and Operations UPNs,
enabled=true and Member type. Existing certificate infrastructure/runtime flags
remain true. `terraform -chdir=infra validate` succeeds. No identities, permissions,
resources, legacy Runs or customer requests have been mutated in this increment.

Azure validation on 2026-09-16:

- `azd provision --preview --no-prompt` succeeds: 0 add, 4 update, 0 destroy.
  Saved plan `.azure/innexq-dev/infra/main.tfplan` inspected via filtered Terraform
  JSON. Exactly API registration, employee SPA registration, its preauthorization
  and API Container App change. All old delegated scopes remain enabled; Manager
  is the only added API environment variable. No identity replacement, data-plane
  role change, customer deployment or agent/model update.
- `azure.yaml` passes Microsoft's published Draft-7 schema (zero errors), using
  an isolated validation-only jsonschema dependency; project dependencies unchanged.
- `azd package innexq-api --no-prompt` and `azd package innexq-web --no-prompt`
  succeed. Local image tags: `innexq/innexq-api-innexq-dev:azd-deploy-1789591368`
  and `innexq/innexq-web-innexq-dev:azd-deploy-1789591488`. Not pushed or deployed.
- Docker 29.4.0 available. Docker contexts, locked dependencies, non-root runtime
  users and schema checks reviewed. Existing resource group/environment confirmed;
  exactly one resource tagged for each target service. CLI tag query syntax needed
  a local JSON projection fallback; this was read-only and then passed.
- Static roles reviewed: API retains Cosmos Data Contributor on only the existing
  runs container and its existing external-write grants; employee host only AcrPull.
  Separate certificate reader retains source-container Blob Data Reader and scoped
  Document Intelligence access. No additional managed-identity rights needed.
- Aspire checks not applicable; net resource/model/replica capacity increase zero.
- `git diff --check` passes. Five Edge screenshots inspected including mobile
  terminal closure with audit history. Full verify includes a clean secret scan.

### Existing policy findings — owner accepted unchanged for this scoped rollout

`az policy assignment list --scope <AzureDev> --disable-scope-strict-match` returns
four initiatives (Managedops, UK OFFICIAL/UK NHS, HITRUST/HIPAA, EU AI Act).
`az policy state list --resource-group rg-innexq-dev-swc` returns 46 noncompliant
evaluations: 24 audit and 22 auditIfNotExists, across 23 distinct policy definitions.
Thirteen evaluations are compliant. No deny effect or Container Apps evaluation
was returned. This is a point-in-time policy-state read, not a fresh compliance scan
or a claim of certification under those standards.

Existing findings include private-link/network restrictions for Storage, Cosmos,
AI, Search and ACR; missing diagnostic logs/settings; and the registry-image
vulnerability policy. No CVEs or severity have been inspected and new local images
have not been assessed by Defender. These resources are unchanged in this preview.
The azure-validate policy gate initially paused rollout for an owner decision, not
an Azure deployment denial. The owner's subsequent `deploy` explicitly permitted
this limited update with those findings tracked separately. No policy assignment,
exemption or network security setting was changed. Only the approved app scope,
configuration and two application images changed as recorded above.

The earlier 2026-09-14 discoverability-only scope below is superseded by this
owner-approved increment; its local browser evidence remains valid historically.

## Control Room certificate discoverability correction — 2026-09-14

Owner reports one customer PDF download and one held request with a visible
Operations case and received Teams notification. This is owner acceptance of
those two paths, not the three-consecutive-positive-run gate. Exact request IDs
were not supplied in the report; no cases or receipts were replayed.

The current employee landing page fetches only Contract Renewal Runs. A local
web-only correction adds a distinct held-certificate case panel using the existing
Operations GET API and exact request links. It is scoped to the already-authorized
Operations identity; no new endpoint, backend state change, manager permission,
source upload or release override is included. Successful downloads are explicitly
not represented by this held-case endpoint. Manager visibility and case lifecycle
actions remain owner permission/policy decisions, not inferred defaults.

Local changes add search, newest-first display within the returned set, refresh,
safe empty/error states, account-change cancellation and clear read-only guidance.
Exact renewal/Operations deep links retain their no-substitution behavior.
Validation: `uv run python scripts/tasks.py verify` passes:555 API/domain,
41 agent,68 UI/client and3 server tests (667), plus schema/type/lint/format and
secret checks. Three additional offline Edge tests pass, including desktop/mobile
overview, exact case links, no horizontal overflow and GET-only case reads.
This correction is not deployed. A subsequent
web-only rollout must use Azure validation/deploy gates and preserve the existing
customer/API/agent versions and all accepted workflow records.

### Previous E1 deployment baseline

> **Status:** Deployed — E1 integration enabled; live customer acceptance pending. Source/OCR/team preflight and scoped access checks passed. Three customer releases and Operations delivery are not yet accepted.

## E1 connection increment — 2026-09-11

Owner requested connecting Customer Portal, document extraction, agents and live
Operations notifications under ADR-013 and CERT-RELEASE-001. MODIFY the existing
azd/Terraform project in AzureDev / Sweden Central; preserve accepted renewal Runs.

- Customer-only API and portal: verified tenant/object-ID mapping, dedicated
  delegated customer scope, no employee permissions or browser-selected identity.
- Private version/hash-bound PDFs and explicit authoritative equipment/service
  records; real Document Intelligence extraction with page provenance.
- Bounded Foundry specialist investigation with trusted request scope; model
  output cannot grant release or replace deterministic source validation.
- Cosmos atomic certificate decision/events/Operations case plus notification
  outbox; scoped Teams notification through the existing installed bot.
- Local negative/isolation tests and full verify, then identity/resource review,
  Azure validation/preview and deployment gates. Never reset accepted Runs.

Implementation is scoped by the owner's E1 connection request. Concrete deployable
bindings below were statically reviewed against ADR-013 and the supplied users.
No additional business rule, mail destination, public sharing or E2/E3 authority
is approved by this increment. A material unresolved security choice blocks live
enablement; pending integration must never be reported as a working live flow.

### E1 progress

- [x] Inspect runtime and finalize concrete component/identity delta.
- [x] Implement authenticated portal, extraction, specialist and outbox adapters.
- [x] Verify locally and record validation proof (660 tests and secret scan pass).
- [x] Validate infrastructure and deploy only the reviewed delta.
- [x] Prove live managed-identity PDF extraction and specialist investigation.
- [ ] Prove real customer sign-in/releases and Operations notification acceptance.

### Concrete E1 deployment delta

Existing AzureDev subscription `c6e08b90-7ae0-4f00-8478-a1d4e73991d2`, tenant
`35de4c50-7dcd-4871-8685-61789c017da2`, Sweden Central, `innexq-dev`.
Synthetic small hackathon workload; no production certification claim.
Preserve hand-maintained azd/Terraform resources, not an AVM/Bicep migration.

| Addition | Binding / least privilege |
|---|---|
| `innexq-customer` Container App | Existing web image; separate single-tenant SPA; PKCE, exact redirect, memory token cache; host MI only AcrPull |
| Customer SPA/API scope | Only `Certificates.Request`; assignment required for Frank/Fabrikam and Kostas/Northwind exact verified object IDs; no Alpine, employee, Graph or email permission |
| Certificate source reader MI | New MI attached to API, selected explicitly for source reads; only new private container Blob Data Reader and DI-resource Cognitive Services User; no Graph/Cosmos/business writes |
| Document Intelligence | New `FormRecognizer` S0, custom subdomain, key auth disabled; GA 2024-11-30 prebuilt-layout on exact PDF bytes |
| Private source container | New `certificate-sources` in existing account; no SAS/public access; create-only publisher verifies all 25 PDF hashes before publishing registry last |
| `innexq-certificate-team` Hosted Agent | New deployment using existing project/model; coordinator invokes Document Analyst and Equipment & Service as distinct real Agent Framework agents/tools; no write tools or API pricing role |
| Existing API / employee web | Add certificate controller, atomic Cosmos case/outbox, staff-only case view using existing read scope; short notice in pinned existing Teams channel; no approval button |

Reader/executor identities are separate but share the API process; this is not
process-level isolation. Agent runtime is separate and receives scoped facts only.
Three certificate specialists share one new Hosted Agent container, with separate
model invocation/response IDs. This does not claim three portal agent resources or
implementation of the two later commercial specialists, Work IQ, vectors or MCP.

The runtime and infrastructure flags default off. Persist reviewed TF_VAR values
for subsequent provisions; enable runtime only after private source publication,
new immutable Hosted version pin and identity checks. Existing renewal agent stays
at version 2. Never deploy all services: target the new team/customer and API/web
explicitly. API min replicas becomes 1 only when the outbox worker is enabled.

Synthetic source convention: inclusive calendar dates in UTC normalize to an
exclusive next-midnight end; source freshness is 300 seconds after an actual final
registry read/version comparison. Missing statuses never become false/true. Source
generator explicitly authors fictional not-revoked/in-service records. OCR must
independently match IDs, serial, dates and next service due; no seeded OCR results.
Notification timeout/crash is ambiguous, never auto-retried; staff sees that state.

### E1 capacity and research evidence

- Foundry prerequisite scripts pass: azd1.33, existing extensions/auth/project/agent.
- Microsoft.App quota CLI: 3 existing environments / limit20; adding zero
  environments. One customer app reuses the existing Consumption environment.
- CognitiveServices quota CLI returns unsupported BadRequest, not unlimited quota.
  Inventory: five accounts in Sweden Central; one FormRecognizer addition. Provider
  `list-skus --kind FormRecognizer --location swedencentral` returns unrestricted S0.
- Existing `gpt-5.4-mini` deployment capacity10 reused, no model/quota upgrade.
  Real local hosted-protocol specialist smoke succeeded in 16.268 seconds, using a
  clearly labelled fixture (not real OCR/customer release). Both specialist response
  IDs were returned and checked. Fixed unsupported tuple/prefixItems output schema.
- New regional resources: one Container App, two user-assigned identities, one DI
  account; one container under existing Storage. No new Cosmos/Search/storage
  accounts, networks, AKS, Functions, APIM or messaging services.
- Reference pattern: Microsoft Foundry samples `agent-framework/responses/05-workflows`;
  current official Document Intelligence REST/layout and managed identity guidance.
  Terraform MCP best-practice tool unavailable; preserved existing provider patterns
  and checked provider schema with `terraform validate` rather than migrating IaC.

### E1 validation proof

- `uv run python scripts/tasks.py verify` passed 2026-09-11: 555 API/domain,
  41 agent, 61 web and 3 server tests (660); API/domain97.85%, new hosted team100%
  measured coverage. Secret scan clean after audited allowlisting of three
  intentionally invalid Basic Auth URL test fixtures.
- Two offline Edge tests pass; actual browser API client with intercepted synthetic
  API/token only. Desktop/mobile, preset/typed submission, exact download bytes,
  held requests, staff citations and missing-link refusal; screenshots inspected.
- `terraform -chdir=infra validate`, schema export/check, types, lint and format pass.
- `scripts/seed_certificates.py` dry run independently validated25 exact local PDFs;
  no upload, live OCR or customer release is claimed by the dry run.
- Local smoke initially inherited unauthorized App Insights export settings; a
  clean local-only run disabled telemetry. Cloud MI telemetry remains unchanged;
  production telemetry permissions must be validated separately.

### Azure validation checklist

- [x] azd configuration parsed by preview; three Docker builds and isolated imports pass.
- [x] AzureDev/tenant/Sweden Central/auth confirmed; inherited Owner and effective
  wildcard resource actions verified; scoped/inherited policy assignment list empty.
- [x] `azd provision --preview --no-prompt` passes: 14 adds, 2 changes, 0 destroy.
  Filtered saved-plan JSON confirms only the reviewed delta; API retains its
  presentation image and min replicas 0, runtime false; legacy web/agent unchanged.
- [x] Static role review: customer/source-reader/host/executor capability separation.
- [x] API/web/team Docker builds pass. API local image index digest
  `sha256:478210ceb35a560c211bf8a11a7f7da2a4e1d243310dcc8cab46a865e0c9f3a5`;
  agent team module included in Docker allowlist and import-smoked. New regression
  test checks explicit azd TF_VAR mapping and team build context. Runtime pin empty
  intentionally blocks enablement until Hosted deployment and its identity checks.
- [x] Preview/build proof recorded by azure-validate before azure-deploy.

## Historical deployed baseline

### E1 staged deployment proof, 2026-09-11

- Infrastructure apply succeeded: 14 added, 2 changed, 0 destroyed. DI S0 is
  `di-innexq-40f415af`, key authentication disabled. Reader client
  `7d309f96-228c-4357-8edb-18ee29451e99`, principal
  `dde0ac1d-2a3d-4185-942e-f71671b49682`: exactly container-scoped Blob Data Reader
  and DI-scoped Cognitive Services User confirmed live.
- Customer SPA `ac838872-2074-464f-ac34-ed7e0bfcdea8` requires assignment; exactly
  the two approved customer object IDs are assigned. Customer host principal
  `d457e6e8-c197-4c4e-822b-fd405d103fe7` has registry-scoped AcrPull. Existing API
  and web image-pull identities also passed the live AcrPull gate.
- Create-only seed publication verified/uploaded all25 PDFs and registry; no source
  overwrite, SharePoint write, email or Teams notification was performed.
- Hosted `innexq-certificate-team:1` active, principal
  `0bbe2604-5ae0-4463-97ff-3d06b37a749f`, no direct Azure role or Graph app-role
  assignments. Existing platform/project model identity path works without adding
  a new Foundry connection. Runtime image digest
  `sha256:7683435538df11b5931052b45772b3735c1e04a4bcc0e177bfc431974c7435d8`.
  Real remote fixture invocation passed in14.489s with both specialist response IDs.
  Foundry evaluation-suite source offered to owner; no suite run is implied.
- API/web images explicitly pushed, registry digests checked, targeted azd deploys
  succeeded. Web/customer share image digest
  `sha256:a2e8ab0273306bfa1d8915b1d9280f0bdd1f22b874f587af7a3ec1479469adae`.
  Healthy ready revisions: API `ca-innexq-dev-api--azd-1789118794`, web
  `ca-innexq-dev-web--azd-1789118885`, customer
  `ca-innexq-dev-customer--azd-1789118905`. `azd show` resolves all endpoints.
- Exact `/health/live` routes return200 on all three apps; customer config exposes
  only tenant/client/API-origin/Certificates.Request scope. Earlier probes used an
  incorrect `/health` path and stale PowerShell result variable; those are not
  accepted health evidence.
- Read-only diagnostic inside deployed API used the distinct reader and controller
  managed identities, actual private PDFs, actual DI and actual Hosted team. It
  verified26 field/page evidence entries and returned all3 specialist proofs for
  DEMO-PT-001. No customer record/release or Operations notification was created.
- Customer execution was disabled throughout these stages. Enabling it requires
  the next preview to contain only the API runtime flag, team version1 and minimum
  replica1 update. Real customer sign-in/three fresh releases and negative-case
  Teams delivery acceptance remain pending.
- Enablement validation: actual `azd provision --preview --no-prompt` succeeded;
  saved-plan inspection confirms exactly one API update, same deployed image,
  certificate runtime true, team version1 and min replicas1. Existing accepted
  renewal Runs remain EXECUTED/revision15/two receipts by Operations-authenticated
  GET-only checks. No replay or new notification was attempted.
- Enablement apply succeeded: 0 added, 1 changed, 0 destroyed. API latest and
  latest-ready both `ca-innexq-dev-api--0000007`, healthy, min replicas1 and100%
  latest traffic. Operations-authenticated inbox GET now returns200 (zero cases
  at readiness check); an earlier503 was during the old-to-new revision handover.
  Anonymous customer access401, Operations token on customer endpoint403,
  exact customer-origin POST preflight accepted and untrusted origin denied.
- Owner prompted to sign in as Frank through the separate live Customer Portal.
  Suggested first positive request DEMO-PT-001, then missing-certificate DEMO-PT-003
  for the held-case/Teams path. No customer is impersonated by deployment scripts.
  Runtime is ready for those tests, not yet three-consecutive-run accepted.

## Compact Teams and email presentation increment

Modify the existing API/web only, in the existing AzureDev/Sweden Central context.
Compact Teams cards link to the authenticated Control Room with exact Run/version/
hash binding; a stale or invalid link must not silently show another decision.
Keep existing human identity, expiry, hash, state and idempotency checks unchanged.
Build escaped, Outlook-friendly HTML email before approval, with the existing
navy/teal text wordmark and a labelled normal SharePoint document link. No URL
shortener, anonymous sharing grant, tracking pixel or remote logo download.
Store HTML and explicit content type in the hashed manifest; legacy Text actions
retain Text semantics. Preview HTML in a scriptless/networkless sandbox plus exact
source inspection. Existing accepted Runs are immutable and will not be replayed.
No new service, identity, Graph permission, agent or retrieval integration.
Validate compact payload size, hash/content-type tampering, HTML escaping, link
binding, preview isolation and full repository verify; then existing Azure
prepare/validate/deploy flow. A new live mail requires a fresh real Teams approval.

Presentation release proof, 2026-09-09 00:02 Athens:

- Provisioning applied exactly **0 add / 1 change / 0 destroy**. Both existing
  managed identities passed the resource-scoped AcrPull gate before image rollout.
- Explicit `presentation-v1` tags pushed and registry digests verified: API
  `sha256:8993a309655a61cc6842676fe42c49d219a8719db101ee5b9302c7945cd506a7`,
  web `sha256:0bfe58b42040933aadf6f20a8478109fc1a126ddcd431efd96cc72721da0819f`.
- `azd deploy innexq-web --from-package ...` then API completed; `azd show
  --output json` resolves both existing HTTPS endpoints. Latest equals latest-ready:
  web `ca-innexq-dev-web--azd-1788901167`, API `ca-innexq-dev-api--azd-1788901187`.
  Both healthy and serving 100% traffic. Web serves new `main-FgsyzmwB.js` asset.
- Web health/config and API live/ready return 200; anonymous Runs remain 401.
  Exact Output folder URL verified. Web still uses its separate image-pull-only
  identity; no new role, permission or source integration was deployed.
- GET-only checks confirm all three accepted Runs retain EXECUTED/revision 15,
  15 events, two receipts and their original hashes. An initial PowerShell property
  count assertion was incorrect; explicit array counting confirmed persisted state
  was unchanged. No Run was replayed and no new Teams message/email was sent.
- New presentation is validated locally and deployed, but its rendering inside the
  real Teams/Outlook clients remains a fresh-Run owner acceptance step. Old approved
  Text email actions remain unchanged. No Teams app reinstall is required.

## Control Room increment — approved sequence, 2026-09-08

The owner approved bringing the read-only Web UI forward after Phase 1 and
confirmed all three fresh approvals worked without client errors. The completed
harness exited 0: Runs `0ed13c9f-b9bd-5362-90bc-447d80054903`,
`664de11b-7380-5cd2-b07a-06ef487f1608`, `93f6e080-47b0-5716-b7ac-f0acb55bd36f`
each EXECUTED, 15 ordered/correlated events, exact approved hash/version and two
completed action receipts. Graph mail acceptance is not proof of recipient delivery.

Implementation scope: React/TypeScript/Fluent UI `innexq-web`, separate Container
App per ADR-005; Run list, state timeline, exact current brief, cited evidence,
deterministic calculation/policy provenance and receipts. No browser write controls,
no automatic retrieval on open, no Work IQ, no customer translation generation.
Use a single-tenant public SPA registration, MSAL authorization-code + PKCE, no
client secret, and only a new delegated `Runs.Read` scope. API enforces read scope
on GET routes only, existing configured user/ownership checks unchanged; write
routes still require the existing operator scope. No Graph/Search permissions for
the web application. Exact origin/redirect allowlists, no wildcard CORS or tokens
in URLs/logs. AzureDev/Sweden Central and existing environment/registry are retained.
Validate schema-generated TypeScript, UI behavior/accessibility/security, API
read-scope denial on writes, complete repository verify, then deployment preview.
Browser sign-in remains a real owner action; no credentials are automated.

Live Control Room: https://ca-innexq-dev-web.delightfulstone-498e0b81.swedencentral.azurecontainerapps.io/
Sign in as the configured approver `superuser@alfacloud.gr`. Viewing or refreshing
Runs never assembles, resets, approves, sends mail or creates files.

Post-deployment proof (23:32 Athens):

- Latest and latest-ready match: API `ca-innexq-dev-api--azd-1788899018`, web
  `ca-innexq-dev-web--azd-1788899038`. `azd show --output json` resolves both URLs.
- Verified ACR digests: API `control-room-readonly`
  `sha256:4bb488aa9cff872d8caf1c8706268b0c50ac67ab079499eaef37923ce723d2c7`;
  web `control-room-v1`
  `sha256:9dbd62782207730ff4b0b131df4fda8c94e6ab008d74ba49593b64454e353971`.
- Web health/config/redirect HTTP 200 and no-store; bridge has no COOP header.
  API live/ready 200, anonymous Runs 401 with no-store. Exact web CORS preflight
  200/GET-only; untrusted origin 400 with no allowed-origin header.
- Existing approver operator token used for GET-only post-release checks: all
  three accepted Runs remain EXECUTED/revision 15, 15 events, two receipts and
  matching approved/current hashes. This is not a browser Runs.Read token proof.
- Web UAMI `ecdc8875-991d-49f0-845b-a9fdcd1c50de` has only AcrPull on the project
  registry; Container App and registry binding use that identity, not the executor.
  SPA `67322ec6-5ebc-4f4f-a2d9-0608f358dbe4` is single-tenant with exactly the
  approved redirect and delegated Runs.Read permission, zero passwords.
- Isolated live Edge check reached the real Microsoft sign-in popup and verified
  Runs.Read, S256 PKCE and exact redirect. No credentials entered. The first browser
  attempt overlapped rollout and timed out; the final DOM-ready check succeeded.
  A missing favicon produces a non-blocking 404 console resource message.
- Real user sign-in, authorized screen rendering and sign-out remain owner
  acceptance steps. No further Teams approval or commercial action was requested.

Integration verification: live project connections are empty; the Hosted Agent's
custom tool calls GA `knowledgebases('innexq-phase1')/retrieve`, not `docs/search`.
The knowledge base selects `innexq-phase1-source`, whose searchIndexParameters
select index `innexq-phase1` and semantic configuration `innexq-semantic`.
No vectorSearch configuration or knowledge-base model exists. This matches ADR-010,
not the preview portal/MCP integration or the full delegated multi-source target.

Generated: 2026-09-05

## 1. Project overview

**Goal:** Implement and deploy Phase 1 only: one complete, governed Contract Renewal Run from synthetic evidence through deterministic pricing, human Teams approval, approved SharePoint/mail execution, and append-only audit events. Prove three consecutive successes after reset without code changes or manual data repair.

**Path:** MODIFY. Phase 0 already supplies the Python 3.12 repository, framework-independent contracts, transition guards, canonical hashing, tests, and an azd/Terraform foundation.

### Frozen boundaries

- The Hosted Agent retrieves and proposes; it cannot approve, mutate Run state, write SharePoint, or send mail.
- The FastAPI workflow controller alone validates evidence, owns transitions, records approvals, checks authority/hash/idempotency, and invokes the allowlisted executor.
- Pricing and authority results use deterministic `Decimal` code and authoritative fixture/policy inputs; model output is never accepted as arithmetic or authority.
- Graph mutation executes only from `APPROVED`, for the stored brief/manifest hash, using an allowlist and one idempotency key per external action.
- Work IQ, the 12% exception path and later-phase evaluation remain excluded. On 2026-09-08 the owner approved bringing forward the read-only web Control Room after the Phase 1 three-Run gate; approval remains in Teams.
- Durable Functions/Durable Task Scheduler remain excluded by the authoritative blueprint. The generic workflow recipe was reviewed but does not override the frozen Container Apps controller decision.

## 2. Requirements and Azure context

| Attribute | Selected value |
|---|---|
| Classification | Synthetic hackathon MVP / proof of concept |
| Scale | Small; one tenant, one region, one Hosted Agent, one workflow pack |
| Budget | Cost-optimized development SKUs |
| Subscription | AzureDev (`c6e08b90-7ae0-4f00-8478-a1d4e73991d2`) |
| Azure tenant | `35de4c50-7dcd-4871-8685-61789c017da2` |
| Primary location | Sweden Central |
| Bot location | West Europe, because Azure Bot local data residency is not offered in Sweden Central |
| azd environment | `innexq-dev` |
| Resource group | New `rg-innexq-dev-swc` |

The signed-in user has inherited Owner and User Access Administrator rights and is a Global Administrator. Azure CLI and azd authentication are valid. Existing subscription policy assignments are Managedops, UK OFFICIAL/NHS, HITRUST/HIPAA, and EU AI Act initiatives in enforcement mode; their assignment parameters contain no location, SKU, or required-tag restriction. Pre-deployment validation will still evaluate the generated plan against policy.

## 3. Confirmed Microsoft 365 targets

| Target | Value |
|---|---|
| SharePoint site | `https://passadisoutlook498.sharepoint.com/sites/InnexQ` |
| Document library | `InnexQDocs` (corrected and confirmed by owner on 2026-09-08) |
| Output folder | `Output` |
| Team | `VISUALSTUDIO-MCT` (`ee42f3fa-d2aa-4033-99ef-bddea5363b46`) |
| Teams channel | `InneQ` (`19:f87553c02fda46978cf84bf2e965dcf3@thread.tacv2`) |
| Sender mailbox | `superuser@alfacloud.gr` |
| Test recipient | `passadis@outlook.com` |
| Phase 1 approver mapping | `superuser@alfacloud.gr`, object ID `11b101d5-96dd-4d25-ad68-38b54de937bf`, mapped to scenario role `account_manager` |

Read-only Graph checks verified the Team and channel in the same tenant. An earlier
CLI-user SharePoint lookup returned HTTP 403 (cause not established). The owner has
since resolved the exact targets and granted the executor site access; executor
managed-identity GETs now return 200. See the binding update below for current proof.

## 4. Components detected and to be implemented

| Component | Type | Technology | Path / host |
|---|---|---|---|
| `innexq-api` | API, controller, Teams adapter, isolated executor module | Python 3.12, FastAPI, Microsoft Teams SDK | `src/api`; Azure Container Apps |
| `innexq-agent` | Single reasoning/retrieval agent | Python 3.12, Microsoft Agent Framework, Responses protocol | `src/agent`; Foundry Hosted Agent container |
| deterministic gateway | Pricing and authority tool | Framework-independent Python `Decimal` logic | `src/gateway`; invoked through API read-only surface |
| contracts | Domain boundary | Pydantic + synchronized JSON Schema | `src/contracts` |
| Foundry IQ seed | Synthetic durable knowledge | Short text policy, contract, matrix, playbook, SLA and template documents | `corpus/blob`; Blob + Azure AI Search knowledge base |
| test/reset harness | Repeatability | Python tasks and pytest | `scripts`, `tests/integration`, `tests/e2e`, `tests/demo` |

## 5. Recipe and architecture

**Selected recipe:** Azure Developer CLI with Terraform. Existing code was adapted from the official Foundry IQ Responses sample. Terraform is hand-maintained in the established repository; no CLI Terraform eject has been run or claimed. AzureRM resources are used where supported; AzAPI is limited to the Foundry project and ARM Blob containers. There is no Bicep deployment path.

**Stack:** Containers plus managed Azure data/AI services.

| Component/resource | Azure service and SKU | Purpose |
|---|---|---|
| API/controller | Azure Container Apps Consumption, min replicas 0/max 1 | External Bot/API ingress, state controller, deterministic gateway and guarded executor |
| Container images | Azure Container Registry Basic | New API and Hosted Agent images; admin account disabled |
| Run store | Azure Cosmos DB for NoSQL Serverless | Run snapshots, brief/approval records, idempotency records and append-only Run Events |
| Telemetry | Workspace-based Application Insights + Log Analytics pay-as-you-go | OpenTelemetry traces, safe event/error/latency signals; 30-day retention |
| Seed/artifacts | StorageV2 Standard LRS | Synthetic corpus source and pre-publication artifacts; shared-key access disabled |
| Durable knowledge | Azure AI Search Free, one index/source/knowledge base | Minimum Foundry IQ corpus with citations; stop rather than silently upgrade if Free capacity is unavailable |
| Foundry | New AIServices S0 account + project | Hosts one agent and its model deployment |
| Model | `gpt-5.4-mini` `2026-03-17`, GlobalStandard, 10K TPM | Agent reasoning; GA extractive IQ retrieval does not call a planning model |
| Hosted Agent | One Foundry Hosted Agent container, Python 3.12 | Strict structured proposal output; no mutation tools |
| Teams approval | Azure Bot Service F0 in West Europe + new regional user-assigned managed identity | Secretless bot authentication and Adaptive Card callback |
| M365 mutation | Microsoft Graph + Exchange Online application RBAC | Site-scoped SharePoint file create and mailbox-scoped send only after approval |

### Identity and permissions

- A new Sweden Central user-assigned managed identity is attached to `innexq-api` and used by Azure Bot Service. No bot client secret is created.
- The API identity receives Cosmos DB Built-in Data Contributor on the runs container, Storage Blob Data Contributor on the artifact container, AcrPull on ACR, project-scoped Foundry invocation access, and telemetry ingestion access required by the SDK.
- SharePoint uses Microsoft Graph `Sites.Selected` plus a `write` grant only on the confirmed InnexQ site. The permission grants no access to other sites.
- Mail uses Exchange Online Application RBAC role `Application Mail.Send` scoped only to `superuser@alfacloud.gr`; the broad tenant-wide Graph `Mail.Send` application role is not granted.
- The Foundry-managed agent identity receives Search Index Data Reader on the new search service and permission to call only the API's read-only pricing/authority surface. It receives no Graph write role.
- Approval callback tokens are validated by the official Teams SDK. The controller records the verified tenant/user IDs and compares the user ID to the configured Phase 1 approver mapping.
- Application Insights records correlation IDs, states, hashes, tool/action outcomes and timings, not full retrieved documents, prompts, or email bodies.

### New architecture decisions requiring this plan approval

- **ADR-009:** Use the current Microsoft Teams SDK for Python as the Azure Bot/Adaptive Card adapter, with `Action.Execute` and a user-assigned managed identity. This is an adapter only; it does not own workflow state or authority.
- **ADR-010:** Provision Foundry IQ programmatically from the official Azure AI Search knowledge-base APIs, preferring the GA `2026-04-01` surface and isolating any capability that remains preview behind one adapter. No unsupported or invented Microsoft capability is used.

## 6. Provisioning limit checklist

All counts are for AzureDev and were checked on 2026-09-05. Providers supported by Azure Quotas were queried with `az quota`; unsupported providers use read-only inventory plus current Microsoft service-limit documentation.

| Resource type | New | Total after | Limit/quota | Evidence and result |
|---|---:|---:|---:|---|
| Resource groups | 1 | 18 | 980/subscription | Inventory + ARM documented limit; pass |
| `Microsoft.App/managedEnvironments` | 1 | 3 | 20 in Sweden Central | Azure Quotas `ManagedEnvironmentCount`, usage 2; pass |
| `Microsoft.App/containerApps` | 1 | 6 in Sweden Central | Not count-quota-gated | Inventory; one app in new environment; pass |
| `Microsoft.Storage/storageAccounts` | 1 | 5 in Sweden Central | 250 | Azure Quotas `StorageAccounts`, usage 4; pass |
| `Microsoft.DocumentDB/databaseAccounts` | 1 | 4/subscription | 250 default | Quota API returns `BadRequest`; inventory 3 + Cosmos documented limit; pass |
| `Microsoft.Search/searchServices` Free | 1 | 1 Free/subscription; 2 all tiers in region | 1 Free/subscription | Inventory shows one existing Basic and no Free service; pass, subject to regional capacity |
| `Microsoft.Search/searchServices` knowledge bases | 1 | 1 on new service | 3 on Free | Current Search documented limit; pass |
| `Microsoft.ContainerRegistry/registries` Basic | 1 | 3 in Sweden Central | Not exposed by Quota API | Inventory 2; Basic per-registry capacity is far above two small images; pass |
| `Microsoft.ManagedIdentity/userAssignedIdentities` | 1 | 3 in Sweden Central | Entra object/service limits, not regional quota API | Inventory 2; pass |
| `Microsoft.CognitiveServices/accounts` AIServices | 1 | 5 in Sweden Central | Provider/model quota governs deployment | Inventory 4; pass |
| `gpt-5.4-mini` GlobalStandard | 1 at 10K TPM | 10K TPM allocated | 10,000K TPM available in Sweden Central | Foundry capacity discovery; pass |
| `Microsoft.OperationalInsights/workspaces` | 1 | 5 in Sweden Central | Not quota-gated at this scale | Inventory 4; pass |
| `Microsoft.Insights/components` | 1 | 3 in Sweden Central | Not quota-gated at this scale | Inventory 2; pass |
| `Microsoft.BotService/botServices` F0 | 1 | 1/subscription | Not exposed by Quota API | Inventory 0; pass |

**Capacity status:** all planned resources are within reported limits. Free Search creation can still fail because regional free-tier capacity is best-effort; the approved behavior is to stop and report rather than incur Basic-tier cost silently.

## 7. Phase 1 workflow and acceptance

### Validation Proof — presentation increment, 2026-09-08/09 Athens

- Owner confirms the deployed Control Room works; this increment keeps it read-only.
- `uv run python scripts/tasks.py verify`: 239 API/domain, 27 agent, 24 frontend
  and 2 web-server tests pass (292 total). Python/TypeScript typing, lint/format,
  synchronized schemas, Terraform formatting and secret scan pass.
- Two offline Playwright checks pass: Control Room and real email desktop/mobile
  layout, including hostile HTML whose scripts and outbound resources are blocked.
- Compact card size, exact decision links, stale-link refusal, escaped HTML,
  manifest binding of content/format and legacy Text compatibility are tested.
- `terraform -chdir=infra validate`, `azd package innexq-api --no-prompt` and
  `azd package innexq-web --no-prompt` pass. Both explicit presentation-v1 Docker
  images build with non-root runtimes. Existing Vite bundle-size warning remains.
- `azd provision --preview --no-prompt`: **0 add, 1 change, 0 destroy**. Saved plan
  inspected: only API Output folder URL added; telemetry secret reference unchanged.
  No identity, RBAC, agent, Search, Cosmos or M365 permission change.
- AzureDev/approved tenant, innexq-dev, Sweden Central, existing resource group and
  Container Apps environment verified. Deployment login and azd auth check pass;
  no duplicate service tags. Existing policy assignments unchanged.
- Deployment sequence: provision setting; live API/web AcrPull gate; explicitly
  push validated tags; deploy web then API; verify ready revisions and endpoints.
  No existing Run is reset, re-approved or replayed. A fresh live email still
  requires a fresh human Teams approval; no new test message sent in this increment.

### Validation Proof — Control Room increment, 2026-09-08 23:21 Athens

Deployment observation: provisioning completed with exactly 6 add / 2 update /
0 destroy. `azd deploy --from-package` accepted the explicit tags but did not push
them; live endpoints remained on the previous API / public web placeholder.
System revision events and ACR queries confirmed MANIFEST_UNKNOWN, not an RBAC
failure. Recovery explicitly pushes the already validated local tags, verifies
registry digests and restarts only the two new non-serving revisions. No workflow
is replayed, source changed or permission broadened. Command success alone is
not deployment readiness.

- [x] `azd version`, `azd auth login --check-status`, `azd show --output json`:
  azd 1.33.0, authenticated deployment user, three approved service definitions parse.
- [x] Existing context verified: AzureDev / approved tenant, innexq-dev environment,
  rg-innexq-dev-swc / Sweden Central, existing healthy cae-innexq-dev. No duplicate
  service tags. Previously confirmed subscription/location reused, no new environment.
- [x] `terraform -chdir=infra validate` and format checks pass. Template inputs
  resolved successfully by azd; no unresolved Go-style expressions.
- [x] `azd provision --preview --no-prompt`: **6 add, 2 change, 0 destroy**.
  Saved plan inspected: only web registration/SP/API preauthorization, web UAMI,
  web AcrPull and web Container App added; existing API scope and CORS setting updated.
  No agent, Search, Cosmos, M365 destination or execution permissions change.
- [x] `uv run python scripts/tasks.py verify`: **230 API/domain, 27 agent,
  19 frontend, 2 web-server tests pass**; coverage 96.35% API/domain, 98.12% agent.
  TypeScript/Python typing, synchronized JSON/TypeScript schemas, lint/format and
  secret scan pass. Synthetic rejected-credential fixtures explicitly annotated.
- [x] Offline Edge Playwright desktop/mobile/keyboard checks pass; no external
  requests, write controls, console errors or mobile overflow. Fixtures are test-only.
- [x] Both Docker images build with non-root runtimes. API image smoke confirms
  Runs.Read code present, health 200, anonymous Runs 401 and Cache-Control no-store.
  `azd package innexq-api --no-prompt` and `azd package innexq-web --no-prompt` pass.
  Deployment will use explicit validated image tags, not an implicit cached package.
- [x] Static role review: web UAMI has only resource-scoped AcrPull; SPA has only
  delegated API Runs.Read; no Graph/Search/Cosmos permission. Existing workload
  roles remain unchanged. Precreated UAMI avoids the system-identity bootstrap
  cycle; public placeholder then image deployment with live AcrPull propagation gate.
- [x] Four subscription policy assignments rechecked; unchanged from resolved
  definitions below, no applicable blocking policy identified for this increment.
  Regulatory audit/manual policies are not certification; server enforcement applies.
- [x] No Aspire/SQL/model deployment checks apply to this increment. Existing
  Hosted Agent v2 and its earlier validated package are deliberately not redeployed.
- Non-blocking: Vite main bundle exceeds its 500 kB advisory threshold; existing
  Teams SDK preview/deprecation warnings. Real Entra popup sign-in is owner-only
  post-deployment validation, not claimed by offline browser tests.

### Assembly diagnosis follow-up — 2026-09-08

- Version-pin apply completed: **0 added, 1 changed, 0 destroyed**. API latest and
  ready revision both `ca-innexq-dev-api--0000003`; live environment pin is `2`.
  The diagnostic API image is unchanged. Final validation: **223 API/domain + 27
  agent tests pass**, coverage 96.26% / 98.12%, all aggregate verify checks pass.
  No completed Run was replayed and no automatic approval was granted.
  The first HTTP probe timed out during revision transition; after Azure reported
  the new revision ready, liveness/readiness returned 200 and anonymous Runs 401.
  The fresh three-Run human-approval harness was then started on this frozen release.
  Run 1/3 `0ed13c9f-b9bd-5362-90bc-447d80054903` assembled successfully and its
  Teams approval was issued. It is awaiting the real human decision; this is not
  yet a completed acceptance Run. Final aggregate verify again passes all 250 tests.

- Hosted `innexq-agent:2` deployed and active via azd, image
  `acrinnexq40f415af.azurecr.io/innexq/innexq-agent-innexq-dev:azd-deploy-1788893716`.
  Instance principal remains `ea6b8f06-d106-4a7e-973b-c0687e6a269e`.
  Explicit API environment release pin `INNEXQ_FOUNDRY_AGENT_VERSION=2` is prepared
  in Terraform; local Settings default remains 1 and is not relied on in Azure.
- Version-pin validation: `azd provision --preview --no-prompt` passes with
  **0 add, 1 change, 0 destroy**: only API environment insertion (the displayed
  subsequent list shifts preserve existing values and the telemetry secret reference).
  Azure roles read back unchanged: agent Search reader, API registry/telemetry/
  artifact/Foundry access at existing resource scopes. No RBAC or SKU change.
  Existing API image/package proof remains valid; no API source change since its
  diagnostic deployment. Terraform formatting corrected and full verification rerun.
  Generated Foundry evaluation suites remain deferred by the approved Phase 1 scope.

- API diagnostic image deployed successfully; ready revision
  `ca-innexq-dev-api--azd-1788892704`, liveness/readiness 200, anonymous Runs 401.
- Diagnostic-only Runs `2244a50d-52ea-5bfa-bd09-28436f6cdcd7` and
  `09c49a48-9bcc-50c5-b8c7-c6da3278dc42` reached POLICY_VERIFIED. Run
  `f03fcbec-b592-5faa-a30d-f99ec709afb3` reproduced EVIDENCE_HOLD at revision 4.
  All three have zero approval/execution receipts. Safe correlated telemetry shows
  `hosted_tool_evidence_failed`, before citation/summary guards, not a proven
  summary-instruction failure. Session `0059307a8657c0f500YjvsrHJdM8t5VseGOQMw2XKg1fnYSSdQ`.
- At 18:51 UTC, six parallel developer-identity Search probes returned HTTP 200
  but playbook/template had zero references/count and zero reasoning tokens,
  without activity errors. All six immediately sequential probes returned 2–4
  references. A prior parallel batch also lost two categories. This supports a
  concurrency-related retrieval symptom, not proof of the service's internal
  cause or exact Free-tier concurrency limit. Corpus/configuration were unchanged.
- Scoped agent remediation serializes retrieval per proposal. No retry, evidence
  fallback, score threshold, API version, corpus, model, SKU or permission change.
  It is not a cross-session/global rate limiter. All material evidence failures
  still hold the entire proposal, including after a later successful query.
- Validation: **222 API/domain + 27 agent tests pass**, coverage 96.26% / 98.12%;
  format/lint/types/schema/Terraform formatting/secret scan pass. New tests prove
  one in-flight retrieval, no retries, preserved eight-call cap and fail-closed
  behavior after empty evidence. One local streaming model/Search probe passed
  all six categories and exact summary, using the explicit local pricing fixture;
  this does not prove hosted identity or count as live acceptance. Foundry skill
  environment/authentication preflight passes. Agent-only azd deploy is underway.

Validation proof: `uv run python scripts/tasks.py verify` passes **222 API/domain
+ 24 agent tests**, coverage 96.26% / 98.10%, with format/lint/type/schema/Terraform
format/security checks passing. New tests cover fixed labels, unsafe identifier
rejection, no payload export and unchanged fail-closed/no-write behavior.
`azd provision --preview --no-prompt` under deployment-auth reports **No changes**;
AzureDev, tenant, Sweden Central and azd authentication match approved context.
Existing static role/policy review remains applicable with no IaC changes; live
API AcrPull, telemetry, artifact and Foundry roles are unchanged.
Docker build, network-disabled packaged diagnostics/non-root smoke and
`azd package innexq-api --no-prompt` pass. Explicit image:
`innexq-api:phase1-assembly-diagnostics`, manifest list
`sha256:8213ac622942ab5775ce413f4d4204aeb73d85e3a5186ee02f2b52546dfa9557`.

- Fresh Run `f8899002-3810-53fd-8b31-b9999a6e786c` passed `verify_run`: EXECUTED,
  15 ordered events and two receipts. Owner confirmed no Teams client error.
  The next Run `151ee024-2597-5e72-8a1c-218373a997b1` stopped in EVIDENCE_HOLD,
  revision 4, after pricing_completed; zero approvals or external receipts.
  The harness stopped. The three-consecutive gate must restart after remediation.
- Hosted version 1 remains active. Failed session
  `065de9f78efd3b0100ztdNvz0RdJ0JRWks5hRAP0u7Rge2WmVl` reports six retrieval tools,
  one pricing tool and seven outbound HTTP 200 responses. Its console tail is
  dominated by periodic metrics and no longer exposes the decisive earlier error.
  Session file listing is denied (`session_not_accessible`); no permission was added.
- Code review found competing summary instructions (no financial/authority claims
  versus copying an entire excerpt that may contain them). This is a hypothesis,
  not the established cause. No prompt, guard, corpus or agent image change yet.
- Owner approved proceeding. Prepared API-only fixed diagnostic labels for assembly
  stage and known evidence failures, plus correlated session/response IDs and
  response status. Arbitrary error/model/tool content is never logged. The SDK's
  local failure emitter carries the exception message, so exact allowlisted matches
  can identify a hosted guard without exporting that message. Unknown errors stay
  unclassified. No new state transitions, action capability or retry behavior.

### Validation Proof — Teams status response, 2026-09-08

- `uv run python scripts/tasks.py verify`: **212 API/domain + 24 agent tests**
  pass, coverage 96.19% / 98.10%. Format, lint, types, synchronized schemas,
  Terraform formatting and secret scan pass. Existing SDK preview/deprecation
  and sandbox pytest-cache warnings remain non-failing.
- Tests cover persisted status/receipt cards without executable actions, SDK
  processor and actual HTTP JSON envelope serialization, incomplete sends without
  sensitive logging, and production-style lifespan startup/authenticated ingress.
  Token validation is mocked only in the offline serialization test; real missing
  and invalid token checks still return 401. No production authentication bypass.
- `azd provision --preview --no-prompt`: **No changes** under deployment-auth.
  AzureDev/tenant/Sweden Central, azd 1.33.0 authentication, existing environment,
  unique API service tag and unchanged policy assignments verified. Static role
  review and live API resource-scoped roles pass, including AcrPull and telemetry.
  The earlier two-phase infrastructure bootstrap remains complete; no reprovision.
- `docker build -f src/api/Dockerfile -t innexq-api:phase1-teams-status .` passes.
  Manifest list: `sha256:d893687bdefc6c224b3a5daea635be6ec0190e5bcb5fae9d6515b5d081bc787b`.
  Network-disabled packaged-code, non-root UID 10001 and health smoke pass.
  `azd package innexq-api --no-prompt` passes. Deploy the explicit checked image,
  not a cached azd tag. No lock/dependency or infrastructure edit in this update.
- Foundry dependency check passes; `azd ai agent show --output json` confirms
  existing `innexq-agent:1` active, unchanged image and isolated instance identity.
  The requested acceptance uses the application harness, not a direct agent call,
  so deterministic validation, real Teams approval and guarded writes stay in path.
- Live Teams rendering is still pending. No timeout cause or three-Run success is
  claimed from offline response tests. Prior completed Run/artifacts are preserved.
- `azd deploy innexq-api --from-package innexq-api:phase1-teams-status --no-prompt`
  succeeded; `azd show` confirms the unchanged HTTPS API endpoint. Latest/ready
  revision `ca-innexq-dev-api--azd-1788880173` serves 100% of traffic with the intended
  image. Liveness/readiness return 200; anonymous Run access returns 401. Live API
  roles, including Cosmos Data Contributor on only the runs container, are unchanged.
- Post-deploy read-only verification confirms prior Run `b71a5212-720b-5a56-b465-36c14f8f091f`
  remains `EXECUTED`, revision 15, with two receipts and its original ordered events.
  Nothing was reapproved or resent. Full verification and `git diff --check` pass.
- The unchanged-code `scripts/live_run.py --runs 3` sequence has posted its first
  fresh approval card: Run `f8899002-3810-53fd-8b31-b9999a6e786c`. It is waiting
  for the real human decision; count remains 0/3 until execution proof passes.

### Validation Proof — Teams context compatibility, 2026-09-08

- Owner approved implementing and deploying the missing-team-metadata fix. The
  adapter accepts a missing group ID only after the existing tenant, user, channel
  and platform checks pass, the connector/conversation reference is validated, and
  the authenticated Teams bot API resolves the exact team to the configured Entra
  group. Conflicting metadata is never overwritten. Timeout/access denial or an
  absent/conflicting lookup result blocks authorization before the controller.
- Uses existing SDK `ctx.api.teams.get_by_id(team_id)` with a validated path ID and
  3-second timeout. No new Graph permission, identity, cache, service or dependency.
  [Microsoft Teams context API](https://learn.microsoft.com/microsoftteams/platform/bots/how-to/get-teams-context?tabs=python).
- `uv run python scripts/tasks.py verify`: **204 API/domain + 24 agent tests** pass,
  coverage 94.39% / 98.10%; all format/lint/type/schema/Terraform/secret checks pass.
  New tests cover successful server-side resolution, no mutation of callback data,
  missing/conflicting IDs, invalid paths, wrong actors/destinations, untrusted
  connector references and lookup failures. Existing hash/version/authority and
  authenticated SDK ingress tests remain green.
- `azd provision --preview --no-prompt` under isolated deployment-auth: **No changes**.
  AzureDev, tenant and Sweden Central match owner-approved scope. Unique service tag,
  existing Container Apps environment and live resource-scoped AcrPull/telemetry roles
  rechecked. Existing policy review remains applicable: only API code changes.
- Docker build and network-disabled packaged-code/non-root check pass for
  `innexq-api:phase1-teams-context`, manifest list
  `sha256:e0bd1a8412d9ad416fc54ff280a3684b72517bf194344adb541cd964a8731946`.
  `azd package innexq-api --no-prompt` passes; deployment will use this explicit image.
- No live approval or execution is synthesized. Previously interrupted Runs are
  preserved; restart the three-Run acceptance sequence after the fix is verified.
- API-only deployment succeeded using `--from-package innexq-api:phase1-teams-context`.
  Revision `ca-innexq-dev-api--azd-1788878591` is Healthy and is both latest/ready,
  with 100% latest-revision traffic. `azd show` confirms the unchanged API URL.
  An initial health GET timed out during revision transition; repeat checks return
  liveness 200, readiness 200 and anonymous Run access 401. Authenticated GET confirms
  existing Run b71a5212-720b-5a56-b465-36c14f8f091f remains revision 8,
  AWAITING_APPROVAL, with no approval or receipts. Owner was asked to click once.
- Web UI remains the blueprint's Phase 3 (React/TypeScript/Fluent UI Control Room),
  followed by Phase 4 hardening/evaluation and Phase 5 submission. Bringing a small
  read-only Run/evidence UI forward after Phase 1 acceptance was recommended, not
  approved or started; the original phase scope remains authoritative.

### Validation Proof — Teams diagnostics, 2026-09-08

- Owner approved fixed-label callback diagnostics only. No authorization relaxation,
  new role, service, agent update, corpus change, reset or automatic approval is in scope.
- `uv run python scripts/tasks.py verify`: **183 API/domain + 24 agent tests** pass;
  coverage 94.26% / 98.10%. Fifteen new cases verify missing/mismatched checks,
  callback failure stages and absence of identity/payload/exception data in logs.
  Format, lint, type, schema, Terraform format and secret checks all pass.
- `azd provision --preview --no-prompt` under isolated deployment-auth: **No changes**.
  AzureDev, tenant, Sweden Central, existing environment and unique API service tag
  match the approved plan. No infrastructure provisioning is needed for this update.
- `docker build -f src/api/Dockerfile -t innexq-api:phase1-teams-diagnostics .` passes.
  Image manifest list: `sha256:4cbf7322cd1598049d3946d2fac7576ca4db46e5f7941b69490e4ce211bf75f8`.
  Network-disabled container check confirms diagnostic source and non-root UID 10001.
- `azd package innexq-api --no-prompt` passes. Deploy the explicitly verified image
  using `--from-package innexq-api:phase1-teams-diagnostics`, not a cached package tag.
  Hosted Agent packaging/deployment is excluded from this API-only change.
- Static and live role checks confirm unchanged resource-scoped AcrPull and Monitoring
  Metrics Publisher, plus existing artifact and project access. No missing role is
  established. Subscription policy assignments are unchanged; no SKU, region, network,
  identity or tag change is proposed. Existing SDK warnings remain.
- Log message `teams_callback_rejected` carries only `failed_checks`: fixed
  missing/mismatch labels or a fixed callback-stage label. No raw exception or
  traceback, Run/card payload, token or actor value is logged. All prior guards remain.
- `azd deploy innexq-api --from-package innexq-api:phase1-teams-diagnostics --no-prompt`
  completed at approximately 14:34 UTC. `azd show` confirms the existing API endpoint.
  Revision `ca-innexq-dev-api--azd-1788878050` is active/Healthy with 100% latest-revision
  traffic and the exact diagnostic image; previous revision is inactive/stopped.
  Liveness/readiness return 200; unauthenticated Run access remains 401. Existing Run
  b71a5212-720b-5a56-b465-36c14f8f091f remains AWAITING_APPROVAL at revision 8 with
  no approval or action receipts. Owner was asked to click once to capture the failure.
- At **14:35:29 UTC**, Application Insights recorded `teams_callback_rejected` with
  **`failed_checks=team_group.missing`**. The authenticated callback passed platform,
  tenant, actor and channel equality checks but omitted `channelData.team.aadGroupId`.
  This confirms the actual failure, rather than just the earlier local hypothesis.
  No fallback or guard relaxation has been implemented. Next proposal is to validate
  missing team metadata through trusted Teams context while retaining every boundary.

1. Reset returns a fresh, idempotent synthetic attempt namespace. Existing Runs, events, files and mail are preserved. It grants no approval and requires no delete permission. This replaces the earlier deletion-based reset text to preserve audit evidence.
2. Detect creates a Fabrikam Run and `DETECTED` event.
3. Assemble invokes the single Hosted Agent, which retrieves cited synthetic Foundry IQ evidence and calls the deterministic 8% pricing/authority tool.
4. Deterministic result for the EUR 180,000 fixture is EUR 14,400 discount and EUR 165,600 net annual value; required role is `account_manager`.
5. The controller validates the structured Decision Brief and allowlisted Action Manifest, hashes them, persists every event and moves to `AWAITING_APPROVAL`.
6. The bot posts a basic Adaptive Card to the confirmed channel. The first deployment requires the owner to upload/install the generated Teams app package so the bot receives a channel conversation reference.
7. Only an approval from the configured user/tenant for the stored hash transitions to `APPROVED` and invokes execution.
8. Execution creates one Run-ID-tagged file under `InnexQDocs/Output`, sends one Run-ID-tagged test email from the scoped mailbox, records per-action idempotency, and reaches `EXECUTED`.
9. The same reset/start/approve procedure must reach `EXECUTED` three consecutive times, producing exactly one file and email per Run and a complete ordered event history.

## 8. Execution checklist

### Planning

- [x] Read authoritative scenario and blueprint.
- [x] Analyze and scan the Phase 0 workspace.
- [x] Confirm AzureDev, Sweden Central, tenant and Microsoft 365 targets.
- [x] Verify Team/channel and deployment/admin access read-only.
- [x] Check policies, quotas, resource counts and model capacity.
- [x] Select azd + Terraform and define least-privilege identities.
- [x] Owner approved this complete plan on 2026-09-07, including ADR-009, ADR-010, West Europe Bot placement and Phase 1 approver mapping.

### Preparation after approval

- [x] Update ADRs, dependencies and synchronized contracts/schemas.
- [x] Implement Cosmos persistence, controller endpoints, deterministic tool, Teams adapter, guarded Graph executor, reset/seed and safe telemetry.
- [x] Add the synthetic corpus and Foundry IQ seeding script.
- [x] Scaffold/adapt the official Foundry IQ Hosted Agent sample, retain one agent, containerize it with Python 3.12, and keep Terraform as the only IaC provider.
- [x] Add Dockerfiles, Terraform resources/RBAC, azd services and Teams package generator/assets.
- [ ] Run one representative local agent invocation plus unit/integration/safety tests and `uv run python scripts/tasks.py verify`.
- [x] Set this plan to `Ready for Validation`.

### Validation and deployment

- [x] Run the `azure-validate` infrastructure workflow and record proof below.
- [ ] Deploy through the `azure-deploy` workflow only.
- [x] Apply the SharePoint site grant and mailbox-scoped Exchange application RBAC. Positive access/scope checks pass; negative isolation checks and actual approved execution remain pending.
- [x] Owner uploads/installs the generated Teams package in the confirmed Team/channel; owner confirmed the authenticated bot reply on 2026-09-08.
- [x] Seed Foundry IQ and validate citations.
- [x] Complete three post-reset approved Runs and verify ordered Cosmos events and file/mail acceptance receipts. Recipient delivery is not inferred from Graph acceptance.
- [ ] Set status to `Deployed` only after the exit criterion succeeds.

## 9. Validation proof

Infrastructure validation passed, 2026-09-08. Provisioning is authorized within the approved plan. Hosted Agent deployment remains gated on a representative live local invocation once the new Foundry project exists. M365 activation and three-run acceptance are separate post-provisioning gates, not claimed by this validation.

- Both API and agent Linux Docker images built successfully, using Python 3.12 and non-root runtime users.
- Local API container: `/health/live` 200, `/health/ready` 503 when unconfigured, `/api/runs` 401 without an Entra token.
- `uv run python scripts/tasks.py verify`: 163 API/domain tests pass, 94.17% coverage; 19 agent tests pass, 98.10% coverage. Formatter, lint, typing, Terraform formatting, eight synchronized schemas and secret scan pass. These are offline tests, not the three live acceptance Runs.
- API rebuilt after retry/version/history fixes: local image manifest `sha256:1f7fc6711b8cc3aac5e4993f3ed8a7547e5bccfc8fa9ddb23d41e652e5e111cf`. Both Dockerfiles use non-root Python 3.12 runtimes and locked dependencies.
- `azd show --output json` parses both services; `azd auth login --check-status` succeeds. The Foundry dependency/environment checks pass. Local azd environment resolves to innexq-dev / AzureDev / swedencentral. No Aspire checks apply.
- `azd provision --preview --no-prompt` succeeded: **35 create, 0 change, 0 destroy**. Saved local plan is ignored by Git. `azd package --no-prompt` succeeds but reports no artifacts because both services use remote builds; actual Docker builds, not that message, provide image-build proof.
- `az account show` rechecked the approved tenant/subscription and interactive-user identity; `az group exists` returned false for the new target. No existing-RG environment/tag conflicts apply.
- Policy definitions and all four assigned initiatives were resolved read-only. Effective deny rules cover legacy Data Lake Store encryption and GatewaySubnet NSGs, neither present in this plan. Modify/deploy rules target VM/Arc/network resources outside this plan. Audit/manual regulatory controls are not a certification of this synthetic public-endpoint MVP. No applicable deployment-blocking policy was found; server-side enforcement remains authoritative.
- Static RBAC review: API Cosmos data role is container-scoped; artifact role container-scoped; ACR pull, project invocation and telemetry roles resource-scoped. Project identity has model access and ACR pull. Deployer seed roles cover only the new corpus/Search resources. Agent Search reader and Pricing.Read assignments are deferred until its real principal exists. No Graph Mail.Send/global SharePoint role or client secret is created. Live propagation checks remain mandatory after provisioning.
- Search Free correction approved by owner: omit unused outbound Search identity and model role. Incoming agent Entra RBAC stays enabled. No keys/tier change.
- Read-only Azure check found the new RG absent and SharePoint site lookup returned403. No cause for the403 is asserted; IDs still require authorized administrative resolution.
- Teams API registration/package and approved administrator bootstrap scripts are prepared; installation and site/mailbox grants have not run.

Azure validation checklist:
- [x] AZD configuration parsing and environment validation
- [x] Authentication/subscription/location recheck
- [x] Provision preview (Terraform plan)
- [x] Local image builds and Docker context checks
- [x] azd package validation
- [x] Static RBAC and applicable Azure policy checks complete
- [ ] Live representative model invocation (after new project exists, before agent deployment)
- [ ] Three real post-reset human-approved Runs

## 10. Planned files

### Provisioning/recovery record (2026-09-08)

- First apply partially succeeded. Resource group, API registration/service principal, API managed identity, Search Free, model/account, ACR, Application Insights, Log Analytics, Storage, Cosmos/database/container and Container Apps environment were created. No existing resource was deleted, no Teams app installed, no site/mailbox grant applied, and no file/mail executed.
- Apply stopped on a Foundry child-write conflict and the renamed `Azure AI User` display name. Recovery serializes project creation after model deployment and pins the **same built-in role ID**, `53ca6127-db72-4b80-b1b0-d745d6d5456d`, now displayed as Foundry User. Scopes and permissions are not broadened. [Microsoft confirms the rename preserves IDs/core permissions](https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry).
- Synthetic seeding succeeded: six documents in `innexq-phase1`; immutable Blob archive SHA-256 `82ea9b7024d930dea7c9187428bf0fec5fbadcd5cd8434cd4214d959c659ae2e`. No SharePoint source uploads are required for this Phase 1 corpus.
- Live retrieval returned HTTP 502 with an explicit Semantic Search disabled error. Recovery explicitly enables the **free** semantic plan, without changing the Search tier or consenting to paid semantic usage. [Microsoft documents the free plan on all tiers](https://learn.microsoft.com/azure/search/semantic-how-to-enable-disable).
- Local source checkpoint: `349bdc7` (no push). Recovery changes are subsequent working-tree edits.
- Fresh `azd provision --preview --no-prompt` passed: **8 add, 1 update, 0 destroy**. The only existing-resource update enables Search's free semantic plan. An intermediate preview exposed unwanted removal of the API identifier URI and Azure-created Consumption profile; explicit ownership/profile configuration now preserves both. Terraform formatting passes; application verification remains 161 + 19 passing tests. Static role IDs/scopes were rechecked against the live built-in definition.
- Recovery created the remaining Foundry project, roles, API Container App and Bot/Teams channel registration. AzureRM 4.81 rejected Free-tier semantic configuration during apply despite a passing preview. The service still reports semanticSearch=disabled and knowledgeRetrieval=free; retrieval remains blocked. The narrow setting is moved to an AzAPI Terraform PATCH using Microsoft's documented 2026-03-01-preview management API, retaining the same service, tier and free billing. This extends AzAPI use to an unsupported AzureRM property, not a new Azure service or an application data-plane preview migration. API code/agent are not yet deployed.
- Final recovery preview passes: **1 add, 0 change, 0 destroy** (the added Terraform object performs the narrow PATCH on the existing Search service). No API/environment drift remains. Full verification passes with **162 API/domain tests + 19 agent tests**, formatting/lint/types/schemas and source secret scan. Generated secret-bearing Terraform state remains ignored; a new verification guard rejects any attempt to track it.

### Current live checkpoint (2026-09-08)

- Final Search semantic patch applied successfully. Six targeted live retrievals through the actual agent retrieval adapter collectively returned contract, pricing, authority, SLA, playbook and template citations. This proves retrieval, not agent/model execution.
- API deployed through `azd deploy innexq-api --no-prompt`; revision `ca-innexq-dev-api--azd-1788851973` runs the ACR image tagged `azd-deploy-1788851961`. The temporary Microsoft bootstrap image is replaced. `azd show` confirms the target and endpoint.
- Endpoint: `https://ca-innexq-dev-api.delightfulstone-498e0b81.swedencentral.azurecontainerapps.io`. Public checks: `/health/live` 200, `/health/ready` 503 for missing workflow configuration, `/api/runs` 401 without a token. Startup logs confirm completion, including the managed-identity Cosmos ping. A first HTTP client request timed out; subsequent independent requests succeeded without configuration changes.
- API packaging now uses local Docker because azd's remote context walker encountered a Windows cache ACL failure. An incorrectly indented edit was corrected and a new offline test parses both service blocks and verifies their Dockerfiles and Terraform provider.
- Live API role assignments match resource/container scopes: ACR pull, artifact Blob contributor, project Foundry User, App Insights publisher, runs-container Cosmos contributor. Its sole Graph application assignment is Sites.Selected; no Graph Mail.Send assignment exists. Site access and Exchange authorization remain separate pending checks.
- Foundry CLI project resolution required the `FOUNDRY_PROJECT_ENDPOINT` alias in addition to `AZURE_AI_PROJECT_ENDPOINT`. The local azd alias is set to the same new project; Terraform now exports both. No extra project or identity was selected.
- Teams package is prepared locally at `.azure/innexq-teams-phase1.zip`. Owner installation and an authenticated channel mention are pending. SharePoint target IDs/site grant and Exchange mailbox-scoped authorization remain pending. No new administrative consent was requested.
- **0/3 live acceptance Runs.** Hosted Agent deployment/identity and its representative local model invocation remain pending. No persisted Run-event write, telemetry ingestion proof, SharePoint file or test email is claimed by the health checks.

| Area | Planned change |
|---|---|
| `.azure/deployment-plan.md` | Phase 1 source of truth |
| `azure.yaml`, `infra/**` | azd services/hooks and Terraform-only infrastructure/RBAC |
| `src/api/**`, `src/gateway/**` | Controller, persistence, tool, Teams and Graph adapters |
| `src/agent/**` | One Hosted Agent and container metadata |
| `src/contracts/**` | Phase 1 request/result/event contracts and synchronized schemas |
| `corpus/blob/**`, `corpus/fixtures/**` | Synthetic Foundry IQ evidence and deterministic transaction truth |
| `teams/**` | Teams manifest and generated package inputs |
| `scripts/**`, `tests/**` | Seed/reset/preflight and local/live acceptance automation |
| `docs/adr/ADR-009*`, `docs/adr/ADR-010*`, `docs/security/**`, `README.md` | Decisions, permissions and operating instructions |

## 11. SharePoint binding update (2026-09-08)

Owner approved proceeding with the configuration update and read-only executor checks.
Owner supplied the successful site grant response (`write` for executor client
`4e0966f1-2cdc-4574-abd5-db7b7a67918f`) and exact target metadata:

- Site: `passadisoutlook498.sharepoint.com,a92e98c1-fd9e-41a8-907c-b5cb3ede772c,e7615067-f1af-4a69-8807-99b338942378`
- Library: `InnexQDocs`, drive `b!wZguqZ79qEGQfLXLPt53LGdQYeev8WlKiAeZsziUI3jxUEiyhHOwTY8Pdas9aRJ1`
- Folder: `Output`, item `01SS7JAFKSTXGPZHTDX5FZ7UQYOKEJ4KXN`
- URL: `https://passadisoutlook498.sharepoint.com/sites/InnexQ/InnexQDocs/Output`

Only the three existing API destination settings will change. No new service,
identity, Graph permission, file, email or Run is created by this update.
The site-level read/write grant remains wider than the controller's folder allowlist.
Runtime Graph API remains v1.0. Executor access and provisioning proof follow below.

### Binding validation proof

- Executor managed identity performed Graph v1.0 GETs inside the running API container:
  site, library and folder all returned 200 with matching IDs/URLs and a folder facet.
  No token was printed; no content write or send was attempted. The diagnostic shell closed.
- Initial preview exposed that saved TF_VAR values were not reaching Terraform. Explicit
  mappings in `infra/main.tfvars.json` correct this, covered by a regression test.
- Corrected `azd provision --preview --no-prompt`: **0 add, 1 in-place change, 0 destroy**.
  The only resource diff is the API's three SharePoint destination environment values;
  the previously prepared Foundry endpoint alias is an output-only addition.
- `uv run python scripts/tasks.py verify`: **164 API/domain tests + 19 agent tests**,
  coverage 94.17% / 98.10%; format, lint, types, schemas, Terraform format and secret scan pass.
- Both bootstrap PowerShell files parse. API Docker packaging succeeds. Existing deployed
  image/runtime remains unchanged by this configuration-only update.
- AzureDev/tenant/Sweden Central, azd authentication, the existing successful Container Apps
  environment and unique API deployment tag were rechecked. The four policy assignments
  match the earlier resolved initiatives; no service/SKU/network/identity changes are proposed.
  Static role scopes remain unchanged; live resource-scoped API roles including AcrPull match.
- ExchangeOnlineManagement 3.10.1 is available. Interactive Exchange sign-in and read-only
  bootstrap succeeded; the approved sender resolved and the exact recipient filter matched
  one mailbox. The executor is not yet configured in Exchange. No grant was made by this check.

### Applied binding and Exchange proof

- `azd provision --no-prompt` succeeded: **0 added, 1 changed, 0 destroyed**. ARM confirms
  all three destination values on ready revision `ca-innexq-dev-api--0000001`. The deployed
  image remains `acrinnexq40f415af.azurecr.io/innexq/innexq-api-innexq-dev:azd-deploy-1788851961`.
- `azd show --output json` confirms the existing API endpoint. Public checks after update:
  liveness 200, readiness 503 (remaining agent configuration), unauthenticated Runs 401.
- Exchange sign-in was verified as `superuser@alfacloud.gr` in the approved tenant. The
  approved bootstrap created the missing Exchange service-principal pointer, management
  scope `InnexQ-Phase1-Sender`, and role assignment `InnexQ-Phase1-MailSend`.
- Scope filter: `ExternalDirectoryObjectId -eq '11b101d5-96dd-4d25-ad68-38b54de937bf'`.
  It resolves exactly the approved sender. `Test-ServicePrincipalAuthorization` returns
  `Application Mail.Send`, `CustomRecipientScope`, and `InScope=True` for that sender.
- A separate read-only rerun of the bootstrap passes, and an assignment audit finds exactly
  one direct Exchange role assignment for the executor: the scoped mail-send assignment.
  Its Graph app-role audit still contains only Sites.Selected, not Mail.Send. Exchange
  sessions were disconnected after the verification; no password, token or secret was saved.
- No SharePoint file, mailbox message or workflow Run was created. Actual mail delivery and
  runtime permission propagation are not established by the administrative scope test.
  Negative access checks against an owner-approved out-of-scope site/mailbox remain pending.
- Owner's temporary Graph Explorer Sites.FullControl.All consent has not been revoked by
  this work; coordinate precise cleanup without removing pre-existing shared-client consent.

## 12. Hosted Agent continuation (2026-09-08)

### Validation proof

- Foundry skill dependency/environment checks pass; AzureDev, tenant and Sweden Central
  remain unchanged. `azd show` resolves exactly the existing API target; the existing
  Container Apps environment is Succeeded. Four policy assignments match the previously
  reviewed initiatives; no service, SKU, network or permission expansion is proposed.
- `azd provision --preview --no-prompt` succeeds with **no changes**. Static API/executor
  roles remain unchanged; live API AcrPull is confirmed on the existing ACR.
- `uv run python scripts/tasks.py verify`: **164 API/domain + 23 agent tests** pass,
  coverage 94.17% / 98.10%; formatting, lint, typing, schemas, Terraform format and
  secret scan pass. Agent tests include default runtime options and fixture isolation.
- Both non-root Python 3.12 Docker builds pass. API manifest:
  `sha256:2255d219cff418118961e2a89594a9a5d1bc7adb5a5283b18d0f5872a8f708fe`;
  agent manifest: `sha256:c5f811e9a1a90e867dcc205d20d4495aa5974ff3dc78d2bb8c179cc506c2f682`.
  `azd package --no-prompt` succeeds. Deploy the newly built API image explicitly to
  avoid reusing an older locally cached azd build.
- Representative local `Agent.run` now succeeds with the real model and six live
  Foundry IQ retrievals, all six evidence categories, exact citation/summary guards,
  and exactly one deterministic pricing call. Pricing uses an explicit local fixture
  transport: this does **not** prove live API authorization or the hosted identity.
- Local testing found and fixed absent AgentContext options and shared-document queries
  dominated by a contract-ID prefix. Focused source-title instructions fix retrieval;
  citation guards remain unchanged and rejected the earlier unsupported proposal.
- API transport now uses the dedicated Hosted Agent endpoint and a fresh session pinned
  to the configured immutable version, with automatic OpenAI retries disabled. This
  corrects the old shared-endpoint request without changing workflow ownership or scope.
  [Microsoft migration guidance](https://learn.microsoft.com/azure/foundry/agents/how-to/migrate-hosted-agent-preview)
  and [version-pinned sessions](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-sessions).
- Local HTTP Responses hosting smoke is in progress. No actual agent principal, live
  Run, Teams approval card, SharePoint file or email has been created by these checks.
  Agent-specific Search/Pricing roles will be previewed separately once Foundry returns
  its actual identity. Existing approval requirements remain mandatory.

### API update applied

Final API status-guard update validation: `uv run python scripts/tasks.py verify`
passes **167 API/domain + 23 agent tests**, coverage 94.19% / 98.10%, with all
other checks passing. Failed/incomplete/cancelled Hosted Agent responses are
explicitly rejected even if their output resembles a valid proposal. The final
API image `innexq-api:phase1-hosted-binding` builds successfully (manifest
`sha256:0f977daf97583fba7d0c6b4f6ef5179a80cec16ee55d1d1cfbc5778f986818fe`).
Infrastructure/configuration is unchanged from the successful no-change preview.

- `azd deploy innexq-api --from-package innexq-api:phase1-validated --no-prompt`
  succeeded. Ready revision: `ca-innexq-dev-api--azd-1788875399`; image:
  `acrinnexq40f415af.azurecr.io/innexq-api:phase1-validated`.
- `azd show --output json` confirms the existing endpoint. Post-deploy liveness
  returns 200 and unauthenticated `/api/runs` returns 401. Agent identity remains
  unset, so this is not full workflow readiness or permission propagation proof.
- An actual valid Entra token for the deployment user is rejected with 403 by
  `/api/runs`, confirming that Azure administrative access does not grant workflow
  user authority. The check used the CLI credential's API `/.default` resource
  scope and made no state changes. The configured approver's separate CLI login
  was requested for live Runs; no login was performed on the owner's behalf.
- Final status-guard image deployed successfully through azd; ready revision
  `ca-innexq-dev-api--azd-1788875866` runs
  `acrinnexq40f415af.azurecr.io/innexq-api:phase1-hosted-binding`. `azd show`
  confirms the unchanged endpoint; liveness is 200.
- During local HTTP testing the default Azure CLI identity changed to the configured
  approver (`11b101d5-96dd-4d25-ad68-38b54de937bf`), while azd remains the original
  developer. The approver's real delegated API GET returns 200. No login/grant was
  performed by this continuation. Preserve these sessions; do not run Terraform
  under the changed CLI identity because deployer-owned roles would drift.
- Local HTTP diagnostic failures included stale owned fixture processes and then
  use of the approver credential for Foundry. These do not establish a production
  streaming defect. The local probe is being rerun with azd developer credentials;
  production managed-identity authentication remains unchanged.
- Clean `azd ai agent invoke --local` HTTP smoke now passes: HTTP 200 **and**
  response status completed, response ID
  `caresp_a401d88c130a951a00KN61wuuWeAFcqSP9K66OSCOMjndz529q`, all six exact evidence
  categories, six actual Search calls and one explicit local pricing fixture call.
  Developer oid/tenant/audience were checked without printing tokens. No production
  streaming fix was needed. Production container still excludes the fixture harness.
- Local cleanup is verified: zero owned fixture Python servers and zero listeners on
  port 8088. Final full `uv run python scripts/tasks.py verify` passes **167 API/domain
  + 24 agent tests**, coverage 94.19% / 98.10%, and all format/lint/type/schema/Terraform
  format/secret checks. Hosted Agent deployment through azd is now in progress.

## 13. Hosted identity binding

- `innexq-agent:1` is active. `azd show` and `azd ai agent show` confirm the dedicated
  Responses endpoint. Foundry doctor passes 11 checks, with 0 failures / 2 not-applicable.
- Image: `acrinnexq40f415af.azurecr.io/innexq/innexq-agent-innexq-dev:azd-deploy-1788876171`.
- Actual agent principal/client ID: `ea6b8f06-d106-4a7e-973b-c0687e6a269e`, Graph type
  ServiceIdentity; it is distinct from the API/executor. Before binding it has no
  direct Azure role or Graph application assignments.
- Foundry created blueprint principal `bbd2da1f-5284-40a0-a690-2658b3b710df`, client
  `50bc308f-2ace-41dd-a15e-50ec61b97512`. Its only Graph assignment is the platform
  lifecycle permission `AgentIdentity.CreateAsManager`, not SharePoint or mail access.
- One remote negative probe supplied `{}` and was rejected by RunRequest validation
  before tools, with response.failed and empty output/usage. This proves deployed
  input validation, not a successful live workflow. Session
  `15e2fe947f6484c0585e74e1be995a9a2f4a152d665809d82c374a409774c5a` contains only this probe.
- User completed isolated profiles: `.azure/deployment-auth` is developer oid
  `7e35709d-f693-4896-9599-146e27046ef4` on AzureDev; `.azure/approver-auth` is approver
  oid `11b101d5-96dd-4d25-ad68-38b54de937bf`. Both tenant IDs match. Use the developer
  profile explicitly for Terraform and the approver profile explicitly for live Runs.
- Prepared binding maps `TF_VAR_agent_principal_id` explicitly into Terraform.
  Intended changes: Search Index Data Reader on the existing Search service;
  API Pricing.Read assignment; API's configured allowed agent principal. No Graph
  permission, model-management role, new service, destination or executor change.
- No extra model role is added: the deployed hosted identity has project-endpoint
  inference and session access by platform default. Runtime success remains to prove.
  [Microsoft hosted identity defaults](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent).
- Later-phase generated evaluation suites remain excluded by the approved Phase 1 scope.

### Binding validation proof

- `azd provision --preview --no-prompt` succeeds under `.azure/deployment-auth`:
  **2 add, 1 change, 0 destroy**, exactly the two intended assignments and API agent-ID
  environment value. No deployer-role drift, image change, destination update or
  resource replacement is present. Existing provider versions and SKUs are unchanged.
- `uv run python scripts/tasks.py verify`: **168 API/domain + 24 agent tests** pass,
  coverage 94.19% / 98.10%, and every format/lint/type/schema/Terraform/secret check passes.
  Existing validated and deployed container images are unchanged by this binding update.
- Static role review confirms the actual instance principal receives only the intended
  Search read surface and API Pricing.Read; no executor, broad Graph or model-management
  role is added. AzureDev/tenant/developer identity are verified in the isolated profile.
  The earlier same-turn package, policy, infrastructure and live AcrPull checks still apply.

### Applied binding and live assembly evidence

- Binding applied successfully: **2 added, 1 changed, 0 destroyed**. The actual
  hosted principal has Search Index Data Reader and API Pricing.Read only; no
  executor or business Graph permission. API readiness now returns 200.
- First live Run `d1421af1-5baf-57cf-8884-54c7fb340126` stopped safely in
  `EVIDENCE_HOLD` at revision 4. Its events are run.detected, agent.started,
  tool.pricing_completed and evidence.hold (error_type Denied). No approval,
  execution action or receipt exists. Preserve this failed Run; acceptance is 0/3.
- Hosted session `04ef8cca821e0d9300hQgg9u8WW18R8XOHmtO5Y5ObzdAIc3tH` metrics
  show six retrieval calls and one pricing call, with seven HTTP 200 responses.
  Exact final assembly failure is under investigation; missing permissions are
  not established and no extra role has been added.
- Application Insights query for `message == "run_event"` confirms ingestion of
  agent.started, tool.pricing_completed and evidence.hold with matching Run ID,
  correlation ID and sequences 2-4. Only audit metadata is exported, not content.
- Fresh reset-based Run `b71a5212-720b-5a56-b465-36c14f8f091f` assembled successfully
  without any production code, corpus, permission or configuration change. It is
  `AWAITING_APPROVAL`, revision 8, with all six evidence categories validated,
  deterministic policy verification and a versioned brief. The first failure's
  precise cause remains unconfirmed; this success does not erase that evidence.
- Hosted session `0486999d47befdb80027TWBSzStKAhlNlioYQ6wrBv9URgBZyb`, response
  `caresp_070e1976407b097000nU7Zgqdknd1x09dqnI5gZby9p1jX5ThX`: completed at
  17:22:35 Athens. Teams card receipt `1788877357678`; brief hash
  `633959e3d9c8bafc1e4360732f1500d82e1c64c070f05d7640383848c2cc9503`.
  No approval is synthesized; owner review in Teams is required before execution.
- Full verification rerun after documentation updates: **168 API/domain + 24 agent
  tests pass**, coverage 94.19% / 98.10%; format, lint, type, schemas, Terraform
  formatting and secret scan all pass. Existing Teams SDK deprecation/preview
  warnings remain; no dependency change was made during acceptance.

## 14. Approval record

### 2026-09-08 live execution and confirmation follow-up

- Run `b71a5212-720b-5a56-b465-36c14f8f091f` reached `EXECUTED`, revision 15.
  A read-only `verify_run` check passed: 15 ordered/correlated events, exact approval
  version/hash binding and two completed receipts. Approval was recorded at
  14:51:35 UTC and execution completed at 14:51:38 UTC. The owner confirmed the
  file in SharePoint and receipt of the email. No replay or resend was performed.
- The missing-team-group fix successfully verified the team through the bot API.
  No callback rejection was recorded for the successful approval. Teams nevertheless
  displayed “Something went wrong”; its exact cause is not established. Both the
  previous message response and a replacement card are supported by Microsoft's
  [Universal Action response contract](https://learn.microsoft.com/en-us/adaptive-cards/authoring-cards/universal-action-model).
- Prepared scoped remediation: return a persisted-status Adaptive Card without
  approval buttons; log safe callback and complete HTTP-response timings. Avoid
  claiming no authorization exists when a later execution step fails. No identity,
  permission, controller, retry, background worker or infrastructure change.
  Live client rendering remains to prove; this is not a confirmed timeout fix.
- The owner approved fixing the confirmation, proving three fresh human-approved
  Runs without intervening changes, then bringing forward the read-only React /
  TypeScript / Fluent UI Control Room. The first completed Run needed a mid-Run
  code update and therefore is not one of the three clean acceptance Runs.

Owner explicitly approved the Phase 1 plan on 2026-09-07. Implementation, validation and deployment are authorized within this scope. Actual commercial execution still requires a separate human approval in Teams for each Run.

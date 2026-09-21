# Phase 1 infrastructure

This directory is the sole infrastructure source for the approved plan in
`.azure/deployment-plan.md`. It uses AzureRM for supported resources, AzAPI for
the Foundry project, ARM-managed Blob containers and the narrow Free semantic setting,
and AzureAD for the API token
audience and narrowly scoped application permissions. No app password or shared
key is configured.

Run local validation with `terraform -chdir=infra init -backend=false` and
`terraform -chdir=infra validate`. Provision/deploy only through the validated azd
workflow. Terraform state is local development state managed by azd and must
remain ignored; it is not a shareable artifact.

The initial Container App uses the Microsoft public bootstrap image. `azd deploy`
builds and pushes `src/api/Dockerfile` and replaces that image. The registry link
already uses the API user-assigned identity; registry admin authentication is
disabled. The deployed image is intentionally owned by azd and ignored by
subsequent Terraform reconciliation.

The API's Graph IDs and actual Hosted Agent principal ID are empty initially.
After deployment, the bootstrap procedure verifies the existing site/library/
folder, sets `TF_VAR_graph_site_id`, `TF_VAR_graph_drive_id`,
`TF_VAR_graph_folder_id`, and `TF_VAR_agent_principal_id`, then reconciles this
same configuration. The three SharePoint values are explicitly mapped through
`main.tfvars.json`: saving TF_VAR values only in azd's environment was insufficient
in the observed CLI workflow. Confirm every intended value appears in the preview;
the agent input still needs equivalent resolution when its identity is available.
Missing targets/identities must fail application readiness.
The agent receives only Search read and `Pricing.Read` access. It must never use
the API identity, which holds the separately guarded write capabilities.

`Sites.Selected` provides no access until the bootstrap applies the approved
InnexQ site grant. Email is authorized separately through Exchange application
RBAC scoped to `superuser@alfacloud.gr`; this code deliberately grants no global
Microsoft Graph `Mail.Send` role.

The model version and Free Search SKU are pinned to the approved selections.
Capacity failures must be reported; do not silently upgrade the Search tier or
switch the model. Public TLS endpoints with Entra authorization are the approved
synthetic MVP network boundary; no additional network resources are included.

Schema references:

- [Foundry project ARM schema](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2025-06-01/accounts/projects)
- [AzureRM provider](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
- [AzureAD API application](https://registry.terraform.io/providers/hashicorp/azuread/latest/docs/resources/application)
- [azd with Terraform](https://learn.microsoft.com/azure/developer/azure-developer-cli/use-terraform-for-azd)

## Bootstrap gates (do not skip)

No synthetic source documents need to be uploaded to SharePoint for this slice:
`corpus/blob/phase1.json` is ingested into the new Blob/Search resources. SharePoint
is only the approved output destination. Ensure the existing InnexQDocs library has
an existing Output folder. No automatic folder creation or alternate library is
allowed when lookup fails.

The API's user-assigned identity client ID and its service-principal object ID are
different identifiers; use `INNEXQ_MANAGED_IDENTITY_CLIENT_ID` and
`INNEXQ_MANAGED_IDENTITY_PRINCIPAL_ID` from Terraform outputs. Never substitute the
API audience registration or the Hosted Agent principal for the executor.

### SharePoint

The workload receives only Graph `Sites.Selected` in Terraform. A separate
administrator grants `write` on exactly the existing InnexQ site. The resulting
permission is site-wide; the controller/executor narrows writes to the pinned
Output folder. It is not a Graph folder-scoped grant.

Use a separately authorized, interactive Microsoft Graph administrative session
in tenant `35de4c50-7dcd-4871-8685-61789c017da2`. Site resolution needs adequate
delegated site-read permission; applying the site grant needs the administrator's
delegated `Sites.FullControl.All`. Do not grant that permission to either workload.
The script does not install modules, log in, create a bootstrap app or request
consent. Any new administrative client/consent requires owner review first.

```powershell
# Existing Graph administrative session; lookup only, no file or permission writes.
./scripts/bootstrap_sharepoint.ps1 -ExecutorClientId <API-managed-identity-client-id>
# Review resolved IDs first, then apply the already-approved one-site write grant.
./scripts/bootstrap_sharepoint.ps1 -ExecutorClientId <API-managed-identity-client-id> -GrantSite
```

Record the returned IDs as `TF_VAR_graph_site_id`, `TF_VAR_graph_drive_id` and
`TF_VAR_graph_folder_id`. Reconcile the same validated IaC. Then verify the deployed
executor identity can read the approved folder and cannot read an explicitly
selected out-of-scope site. An admin-token success is not a workload-identity test.
Do not keep access tokens in terminal output, files or commit history.

### Exchange mailbox-scoped send

Connect an authorized Exchange Online administrator to the same tenant. Run:

```powershell
./scripts/bootstrap_exchange.ps1 -ExecutorClientId <client-id> -ExecutorPrincipalId <principal-id>
./scripts/bootstrap_exchange.ps1 -ExecutorClientId <client-id> -ExecutorPrincipalId <principal-id> -Apply
```

The script creates only missing named Exchange service-principal, scope and
`Application Mail.Send` assignment objects. Its scope must match exactly the
immutable directory ID of `superuser@alfacloud.gr`. Existing conflicting objects
are a hard stop; they are never overwritten. Inspect all other role assignments
for this new principal and confirm there is no Graph `Mail.Send`, mail-read role,
unscoped Exchange assignment or membership that adds authority. Exchange and
Entra grants are additive; the Exchange authorization test ignores Entra grants.
Test one other approved tenant mailbox with `Test-ServicePrincipalAuthorization`
and require `InScope=False` without sending a message to it.

Exchange permission caches can lag between 30 minutes and two hours. Do not
broaden permissions or repeatedly send test mail to diagnose propagation. A Graph
202 response means accepted, not delivered: record recipient confirmation for
each of the three approved live Runs. Reset uses fresh Run namespaces and retains
audit evidence; no mailbox delete/read privilege is required.

### Hosted Agent and readiness

Resolve the actual deployed agent identity from Foundry, set
`TF_VAR_agent_principal_id`, and verify it differs from the executor identity.
Reconcile Search read and `Pricing.Read` assignments with this value. Verify the
agent cannot access the controller's human-only routes or Graph mutation targets.
Install the generated Teams custom app in the approved Team/channel as the owner.
The application must store the authenticated channel conversation reference before
issuing an approval. Never fabricate a conversation reference from a URL.

## Historical pre-provisioning checks, 2026-09-08 (Athens)

The following records precede deployment; see the current checkpoint below.

- Azure CLI context matches AzureDev and the approved tenant/subscription.
- `az group exists -n rg-innexq-dev-swc` returned `false`; no new project resources
  were found in that group because it does not yet exist.
- Search inventory returned one existing Basic service, `rag-wandb`, in Sweden
  Central and no Free service. This does not guarantee regional provisioning
  capacity.
- Cognitive Services usage reported `OpenAI.GlobalStandard.gpt-5.4-mini` current
  0, limit 10000, unit Count in Sweden Central. Availability of the pinned model
  version and successful allocation remain deployment checks.
- SharePoint site GET returned HTTP 403. Site/library/folder IDs remain unresolved;
  that response alone does not establish its cause, site existence or user rights.
- `terraform -chdir=infra fmt -check -recursive` and `terraform -chdir=infra
  validate` passed. Both administrative scripts passed PowerShell syntax parsing;
  no bootstrap mutation or live administrative script execution was performed.
- **Corrected with owner approval:** Free Search has no outbound managed identity
  or model role. Extractive retrieval does not need either; incoming agent access
  remains Entra RBAC. No SKU upgrade or replacement credentials were introduced.
- Full azd provision preview, package/build and live identity checks remain pending;
  this is not a declaration that deployment is validated.

References: [site grant API](https://learn.microsoft.com/en-us/graph/api/site-post-permissions?view=graph-rest-1.0),
[Exchange application RBAC](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac),
[Graph mail acceptance](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0).

## Current deployment checkpoint, 2026-09-08

Infrastructure, API and synthetic corpus are deployed in `rg-innexq-dev-swc`.
API liveness/readiness have returned 200; the agent and M365 bindings are complete.
The three-consecutive-Run gate passed: three fresh human-approved Runs reached
EXECUTED with 15 correlated events and two completed receipts each. The owner
confirmed all three Teams interactions completed without client errors.
Live retrieval returned all six evidence categories. The detailed
proof and outstanding checks are in `../.azure/deployment-plan.md`.

The approved early read-only Control Room is also deployed in the existing
Container Apps environment. `infra/web.tf` owns its separate image-pull identity,
single-tenant SPA registration and Runs.Read preauthorization. API CORS is exact
and GET-only. Live endpoints and PKCE popup pass; owner sign-in acceptance remains.

The owner installed `.azure/innexq-teams-phase1.zip` in the approved Team and
confirmed the bot reply and corrected approval confirmation in Teams web. A bot
mention registers the authenticated channel reference; it does not approve a Run.

Hosted Agent version 2 serializes retrieval within each proposal. `infra/api.tf`
explicitly pins the API's target version; update that release pin only after the
corresponding immutable agent version is deployed and verified. On a fresh Foundry
project, reconcile the actual deployed version rather than assuming version 2
already exists. Runtime must never silently select the latest agent version.

For the bootstrap scripts above, the deployed executor client ID is
`4e0966f1-2cdc-4574-abd5-db7b7a67918f` and principal ID is
`a78225b8-00e9-4dd7-8848-4d1ef4b62325`. These are public identifiers, not secrets.
Do not share tokens, passwords or Terraform state.

SharePoint binding and Exchange bootstrap completed on 2026-09-08. Executor
managed-identity Graph v1.0 GETs returned 200 for the exact site/library/folder.
The API's three target settings were applied without an image change. The owner
confirmed the bot reply after installation. Exchange now has one executor
assignment, `InnexQ-Phase1-MailSend`, scoped to the immutable directory ID of
`superuser@alfacloud.gr`; its positive authorization test passes. The read-only
bootstrap rerun also passes. No file or mail was sent by these checks.

Outstanding: owner-approved negative isolation tests and real browser sign-in for
the early Control Room increment. The owner confirmed one delivered email and SharePoint
file; a Graph acceptance receipt alone is not proof of recipient delivery. Temporary
administrative Graph Explorer consent cleanup remains an owner-coordinated step;
disconnecting a session is not consent revocation.

## E1 certificate rollout configuration

`infra/certificates.tf` adds the separate customer SPA/host, private PDF container,
Document Intelligence and scoped reader identity under ADR-013. Set all three
azd values explicitly: `TF_VAR_certificate_infrastructure_enabled`,
`TF_VAR_certificate_runtime_enabled`, and `TF_VAR_certificate_agent_version`.
`main.tfvars.json` maps these values; merely putting TF_VAR names in azd's local
environment does not export them to Terraform automatically in this project.

For a new E1 rollout, infrastructure is true and runtime false with an empty
version. Preview/apply the resource delta, verify roles, publish the archived PDFs,
deploy only `innexq-certificate-team`, and validate real extraction/investigation.
Only then pin the actual immutable agent version and enable runtime. Keep these
values persisted for later provisions; clearing the infrastructure flag would
plan removal of E1 resources and requires a separate destructive-change review.
Never deploy all services or change the accepted renewal agent version2 implicitly.

Current E1 deployment evidence and live acceptance status are recorded in the
local deployment plan. Customer release and Teams receipt must be tested
with real customer sign-in; infrastructure success is not acceptance.

## ADR-017 evidence candidate configuration

The existing API can host `/api/evidence/mcp`; broker staging is independent of
customer routing. Authority boundaries and live acceptance requirements are
recorded in the internal design decisions.

- `TF_VAR_evidence_identity_enabled`: enables the Application-only `Evidence.Read`
  role and its single approved certificate-agent assignment, without an API revision.
- `TF_VAR_evidence_agent_principal_id`: only the verified owner-approved principal.
- `TF_VAR_evidence_broker_enabled`: mounts the authenticated read-only MCP surface;
  may be true while customer routing remains false and certificate v3 stays pinned.
- `TF_VAR_evidence_runtime_enabled`: defaults false; enabling requires certificate
  runtime, the broker gate and a validated agent version other than accepted v3.
- `INNEXQ_CERTIFICATE_EVIDENCE_TOOLS_ENABLED`: candidate agent-service opt-in;
  this does not enable the API's customer evidence path.
- `INNEXQ_CERTIFICATE_TOOLBOX_ENDPOINT`: immutable version-pinned endpoint in the
  existing project, mapped to the agent's `TOOLBOX_ENDPOINT`.

The four evidence Terraform values are explicitly mapped through
`main.tfvars.json`; do not rely on azd forwarding stored `TF_VAR_*` values into
the Terraform process. Keep the approved grant enabled during subsequent previews.

`evidence-toolbox.json` is the approved **innexq-dev-specific** four-tool manifest,
not a cross-environment template. Connection `innexq-evidence` uses the existing
API audience and AgenticIdentityToken; toolbox `innexq-evidence-tools` is pinned
to version 1. Never substitute the shared project identity or add direct data roles.
The connection/toolbox and narrow role were created on 2026-09-19. The API broker
and immutable candidate agent are deployed. Following three fresh evidence-only
passes, the owner approved a supervised v6 customer pilot: customer evidence
routing is enabled and v6 is pinned. V3 remains the rollback version. Cloud
metadata, dummy-scope rejection and evidence probes do not establish customer
release/hold/Operations acceptance. On 2026-09-20 the owner separately confirmed
those customer checks succeeded; live records corroborate PT-001 release and
download preparation, PT-002 service-status hold and PT-003 missing-evidence hold.
Both held requests have Operations cases. Closure updates were not separately
retested in this pilot. See the deployment plan for request IDs and evidence limits.
The operator-only `innexq_api.evidence_probe` requires broker-only staging and
explicit execution. It can record evidence receipts but cannot create a workflow,
authorize/download a certificate, create an Operations case or send notifications.

# Phase 1 infrastructure

This directory is the sole infrastructure source for the approved plan in
`.azure/deployment-plan.md`. It uses AzureRM for supported resources, AzAPI for
the Foundry project and ARM-managed Blob containers, and AzureAD for the API token
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
same configuration. Missing targets/identities must fail application readiness.
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
is only the approved output destination. Ensure the existing InnexQ library has
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

## Read-only readiness evidence, 2026-09-08 (Athens)

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

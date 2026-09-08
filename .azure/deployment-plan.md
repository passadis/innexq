# InnexQ Azure Deployment Plan

> **Status:** Validated — azure-validate infrastructure gate passed 2026-09-08. Live agent/M365 acceptance remains pending; this is not a completed Phase 1 deployment.

Generated: 2026-09-05

## 1. Project overview

**Goal:** Implement and deploy Phase 1 only: one complete, governed Contract Renewal Run from synthetic evidence through deterministic pricing, human Teams approval, approved SharePoint/mail execution, and append-only audit events. Prove three consecutive successes after reset without code changes or manual data repair.

**Path:** MODIFY. Phase 0 already supplies the Python 3.12 repository, framework-independent contracts, transition guards, canonical hashing, tests, and an azd/Terraform foundation.

### Frozen boundaries

- The Hosted Agent retrieves and proposes; it cannot approve, mutate Run state, write SharePoint, or send mail.
- The FastAPI workflow controller alone validates evidence, owns transitions, records approvals, checks authority/hash/idempotency, and invokes the allowlisted executor.
- Pricing and authority results use deterministic `Decimal` code and authoritative fixture/policy inputs; model output is never accepted as arithmetic or authority.
- Graph mutation executes only from `APPROVED`, for the stored brief/manifest hash, using an allowlist and one idempotency key per external action.
- Work IQ, the web Control Room, the 12% exception path, and later-phase UI/evaluation work remain excluded.
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
| Document library | `InnexQ` |
| Output folder | `Output` |
| Team | `VISUALSTUDIO-MCT` (`ee42f3fa-d2aa-4033-99ef-bddea5363b46`) |
| Teams channel | `InneQ` (`19:f87553c02fda46978cf84bf2e965dcf3@thread.tacv2`) |
| Sender mailbox | `superuser@alfacloud.gr` |
| Test recipient | `passadis@outlook.com` |
| Phase 1 approver mapping | `superuser@alfacloud.gr`, object ID `11b101d5-96dd-4d25-ad68-38b54de937bf`, mapped to scenario role `account_manager` |

Read-only Graph checks verified the Team and channel in the same tenant. SharePoint site lookup returned HTTP 403; its cause is not established. An authorized administrator must resolve the exact site/library/folder and grant the new identity access to that site only.

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

1. Reset returns a fresh, idempotent synthetic attempt namespace. Existing Runs, events, files and mail are preserved. It grants no approval and requires no delete permission. This replaces the earlier deletion-based reset text to preserve audit evidence.
2. Detect creates a Fabrikam Run and `DETECTED` event.
3. Assemble invokes the single Hosted Agent, which retrieves cited synthetic Foundry IQ evidence and calls the deterministic 8% pricing/authority tool.
4. Deterministic result for the EUR 180,000 fixture is EUR 14,400 discount and EUR 165,600 net annual value; required role is `account_manager`.
5. The controller validates the structured Decision Brief and allowlisted Action Manifest, hashes them, persists every event and moves to `AWAITING_APPROVAL`.
6. The bot posts a basic Adaptive Card to the confirmed channel. The first deployment requires the owner to upload/install the generated Teams app package so the bot receives a channel conversation reference.
7. Only an approval from the configured user/tenant for the stored hash transitions to `APPROVED` and invokes execution.
8. Execution creates one Run-ID-tagged file under `InnexQ/Output`, sends one Run-ID-tagged test email from the scoped mailbox, records per-action idempotency, and reaches `EXECUTED`.
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
- [ ] Apply the SharePoint site grant and mailbox-scoped Exchange application RBAC.
- [ ] Owner uploads/installs the generated Teams package in the confirmed Team/channel.
- [ ] Seed Foundry IQ and validate citations.
- [ ] Complete three post-reset approved Runs and verify Cosmos events, three SharePoint files and three test emails.
- [ ] Set status to `Deployed` only after the exit criterion succeeds.

## 9. Validation proof

Infrastructure validation passed, 2026-09-08. Provisioning is authorized within the approved plan. Hosted Agent deployment remains gated on a representative live local invocation once the new Foundry project exists. M365 activation and three-run acceptance are separate post-provisioning gates, not claimed by this validation.

- Both API and agent Linux Docker images built successfully, using Python 3.12 and non-root runtime users.
- Local API container: `/health/live` 200, `/health/ready` 503 when unconfigured, `/api/runs` 401 without an Entra token.
- `uv run python scripts/tasks.py verify`: 161 API/domain tests pass, 94.17% coverage; 19 agent tests pass, 98.10% coverage. Formatter, lint, typing, Terraform formatting, eight synchronized schemas and secret scan pass. These are offline tests, not the three live acceptance Runs.
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

## 11. Approval record

Owner explicitly approved the Phase 1 plan on 2026-09-07. Implementation, validation and deployment are authorized within this scope. Actual commercial execution still requires a separate human approval in Teams for each Run.

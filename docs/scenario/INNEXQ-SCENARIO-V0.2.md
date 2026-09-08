# InnexQ - Refined Hackathon Scenario

**Version:** 0.2  
**Date:** 2026-08-15  
**Status:** Recommended build direction  
**Executive Challenge:** Hack for agents in the enterprise  

## 1. Decision

Keep InnexQ and the contract-renewal scenario. Do not restart from a blank sheet.

The original scenario already has the ingredients of a strong submission: a real enterprise transaction, fragmented knowledge, multiple systems, a human approval boundary, a visible state change, and measurable outcomes. The refinement is to stop presenting InnexQ as a faster renewal assistant and position it as a **proof-carrying digital coworker**.

> **InnexQ turns company knowledge into governed work. Every recommendation carries its evidence, every proposed action carries its policy checks, and nothing consequential happens without the right human authority.**

The first shipped workflow is **Renewal Run** at the fictional Contoso Engineering Services.

## 2. Why this is stronger than a conventional agent demo

Most enterprise agent demonstrations stop at an answer, a summary, or a draft. InnexQ completes a business outcome while keeping the human in control.

Its differentiator is the **Proof-Carrying Decision Brief**. Before an approver is asked to act, the agent must assemble one reviewable package containing:

1. The proposed renewal and commercial options.
2. Citations for every material factual claim.
3. Deterministic pricing and margin calculations.
4. The policies and approval limits that apply.
5. Any missing, conflicting, stale, or unauthorized evidence.
6. The exact actions that will occur after approval.

The approver does not approve opaque AI output. The approver approves a traceable evidence-and-action package.

## 3. Customer and business problem

### Contoso Engineering Services

Contoso Engineering Services is a fictional, EU-based company headquartered in Athens. Approximately 400 employees maintain industrial equipment for about 120 customers under recurring service contracts.

Renewals protect service continuity and recurring revenue, but the process currently takes four to nine days and crosses six manual handoffs:

1. An account manager notices that a contract is approaching expiry.
2. The current contract is found in SharePoint.
3. Operations is asked for equipment and service history.
4. Commercial terms are calculated from pricing and discount policies.
5. Approval is chased through email or Teams.
6. The approved quote is stored and sent to the customer.

The difficult part is not document generation. It is reconstructing the complete decision context from company policy, current operational facts, recent human communication, and approval authority.

## 4. Personas

| Persona | Role | Experience |
|---|---|---|
| Elena Petrou | Account Manager | Reviews the Proof-Carrying Decision Brief and approves, edits, escalates, or rejects it in Teams. |
| Marco Ricci | Operations Manager and exception approver | Receives cases that exceed Elena's authority or contain operational/policy conflicts; monitors the Control Room. |
| Ingrid Larsen | Customer contact at Fabrikam Industrial AB | Receives the approved renewal pack in her preferred language and accessible format. |

## 5. The hero scenario

Fabrikam Industrial AB has a Gold service contract covering 18 industrial compressors. The contract expires in 45 days.

The latest customer correspondence requests a three-year renewal and a 12% loyalty discount. The current pricing policy permits Elena to approve up to 8%; a larger discount requires Marco. Service records also show an increase in emergency callouts, which affects the recommended SLA and price.

InnexQ performs the following Renewal Run:

1. Detects the approaching expiry from the contract register.
2. Uses **Foundry IQ** to retrieve the current contract, SLA policy, pricing policy, approval matrix, and renewal playbook with citations and permission enforcement.
3. Uses **Work IQ** in delegated, read-only mode to identify the latest relevant email and meeting commitments, preserving Microsoft 365 permissions.
4. Calls deterministic business tools for the current asset list, service history, pricing, discount, and margin calculations.
5. Produces two grounded options:
   - an 8% discount within Elena's authority;
   - a 12% exception that must be escalated to Marco.
6. Presents the Proof-Carrying Decision Brief in Teams, including citations, policy checks, anomalies, confidence, and the exact post-approval actions.
7. After the authorized option is approved, writes the approved renewal pack to SharePoint, sends the customer email through Microsoft Graph, and records the completed Run.

If required evidence is missing, contradictory, stale, or inaccessible, InnexQ enters **EVIDENCE_HOLD** and explains what a human must resolve. It never invents a value or silently substitutes a source.

## 6. Workflow and state model

```text
DETECTED
   |
   v
CONTEXT_ASSEMBLED -----> EVIDENCE_HOLD
   |                           |
   v                           +----> CONTEXT_ASSEMBLED (after resolution)
POLICY_VERIFIED
   |
   v
AWAITING_APPROVAL -----> CLOSED_REJECTED
   |
   +----> ESCALATED ----> AWAITING_APPROVAL
   |
   v
EXECUTED
```

| State | Required result |
|---|---|
| DETECTED | A real contract is eligible for renewal; non-expiring contracts do not start a Run. |
| CONTEXT_ASSEMBLED | Durable company knowledge, live work context, and operational facts are gathered with provenance. |
| POLICY_VERIFIED | Commercial values are calculated deterministically and checked against policy and authority. |
| EVIDENCE_HOLD | The workflow stops safely because required evidence is missing, conflicting, stale, or unauthorized. |
| AWAITING_APPROVAL | The authorized human can approve, edit, escalate, or reject the complete Decision Brief. |
| ESCALATED | The decision is routed to the role with sufficient authority without losing evidence or history. |
| EXECUTED | Only the approved version is written to SharePoint and sent to the customer. |

## 7. Five non-negotiable safety rules

1. **No uncited material claims.** Every factual statement that influences the decision must link to an authorized source or deterministic tool result.
2. **No generative arithmetic.** Prices, discounts, margins, expiry dates, and approval thresholds come from code and authoritative data, not model calculation.
3. **No action before authority.** Customer email, SharePoint writes, and commercial commitments are disabled until an authorized approval is recorded.
4. **No silent gap filling.** Missing or contradictory evidence creates an Evidence Hold.
5. **No relationship-based pricing.** Work IQ context can explain customer intent and commitments but cannot set price, discount, margin, or approval authority.

## 8. Microsoft IQ is structural, not decorative

### Foundry IQ - durable Company IQ

Foundry IQ is the authoritative knowledge layer for contracts, policy, templates, and process guidance. It provides multi-source, agentic retrieval, permission-aware results, and citations. The same Company IQ can later support additional workflows without rebuilding retrieval for every agent.

Core knowledge sources:

- SharePoint: contracts, approval matrix, renewal playbook, templates.
- Azure Blob Storage: service manuals and stable reference documents.
- Optional structured knowledge source only where technically justified.

### Work IQ - live work context

Work IQ supplies recent, user-scoped Microsoft 365 context such as relevant mail, meeting commitments, files, and Teams decisions. For the MVP it is read-only and delegated under the signed-in user's identity.

Work IQ informs **what people recently agreed or requested**. It does not replace durable policy, transaction data, or authorization logic.

### Deterministic tools - current business truth

The contract register, asset/service records, pricing calculator, and approval checks remain deterministic tools exposed through a small audited API or MCP server. They are not treated as unstructured knowledge.

### Actions - controlled Microsoft 365 writes

Microsoft Graph performs SharePoint and mail actions only after approval. Mutation capabilities are isolated from the agent's retrieval capabilities and receive a signed Run ID, approved artifact hash, actor identity, and permitted action list.

### Why Fabric IQ is not in the MVP

The renewal workflow does not require a business ontology or cross-domain relationship graph to be credible. Adding Fabric IQ would increase implementation and preview risk without changing the customer outcome. Fabric IQ becomes justified only when InnexQ expands into supply-chain impact analysis, portfolio-wide risk, or entity relationship reasoning.

This is intentional Microsoft architecture, not a product omission.

## 9. Proposed build architecture

| Layer | Microsoft technology | Responsibility |
|---|---|---|
| Experience | Teams Adaptive Card plus accessible web Control Room | Human approval, evidence inspection, Run status, metrics. |
| Application PaaS | Azure Container Apps | Trigger/API, workflow controller, approval callback, Control Room backend. |
| Agent runtime | Foundry Hosted Agent using Microsoft Agent Framework | Plans retrieval, assembles evidence, explains options, and proposes actions. |
| Durable knowledge | Foundry IQ backed by Azure AI Search | Permission-aware, multi-source retrieval with citations. |
| Live work context | Work IQ API | Delegated retrieval of recent Microsoft 365 work context. |
| Business tools | Audited MCP/REST Gateway | Contract register, service records, deterministic pricing and authority checks. |
| M365 actions | Microsoft Graph | Teams interaction, SharePoint write, approved customer email. |
| State and audit | Azure Cosmos DB or Azure SQL plus Application Insights | Run state, immutable event history, traces, outcome metrics. |
| Security | Managed identities, Microsoft Entra ID, Key Vault and RBAC | Keyless authentication, least privilege, separation of read and write authority. |

The workflow controller, not the language model, owns the state machine and action authorization. The hosted agent proposes; deterministic services validate; humans authorize; the application executes.

## 10. Inclusion by design

Inclusion must affect the product, not appear as a slide-only claim.

- The Decision Brief offers a concise plain-language view and a detailed evidence view.
- The Control Room is keyboard navigable, screen-reader friendly, and designed to WCAG 2.2 AA contrast and focus standards.
- Customer communications can be generated in the customer's recorded preferred language, while the approved source version and meaning remain visible to the approver.
- Permission-aware retrieval prevents employees from seeing evidence they are not authorized to access.
- Commercial decisions cannot use protected personal attributes or inferred relationship sentiment.
- High-impact exceptions are routed to a human with sufficient authority instead of being silently rejected or automatically executed.

For the hero demo, Ingrid receives the approved renewal in Swedish and English. Elena approves from the English Decision Brief, with the translation visible before execution.

## 11. Demo design for the two-minute submission

| Time | Beat | What judges see |
|---:|---|---|
| 0-15s | The problem | Six handoffs, scattered knowledge, four-to-nine-day baseline. |
| 15-35s | Detection and context | Fabrikam renewal starts; Foundry IQ citations and Work IQ context appear in the Run timeline. |
| 35-65s | The intelligence | The 12% request conflicts with Elena's 8% authority; deterministic calculations and two compliant options appear. |
| 65-90s | Human authority | Elena selects the compliant option and approves the complete action package in Teams. |
| 90-108s | Execution | Approved quote is written to SharePoint and the bilingual customer email is sent. |
| 108-120s | Proof | Run Log, actor attribution, citations, cycle time, prevented policy exception, and final line: “Contoso got an IQ. The human kept the last word.” |

The video should show one exceptional-but-completable Run, not three separate cases. Negative tests belong in the Control Room and repository evidence.

## 12. Outcome metrics

| Metric | Baseline | MVP target |
|---|---:|---:|
| Manual handoffs | 6 | 1 normal approval; 2 only for an exception |
| Renewal cycle time | 4-9 days | Under 15 minutes after complete evidence is available |
| Material claim citation coverage | Not measured | 100% |
| Commercial calculations performed by the model | Unknown/manual | 0 |
| Unauthorized external writes | Not centrally controlled | 0 |
| Missing-evidence tests that stop safely | Not measured | 100% of defined test set |
| Replayable Runs | Email archaeology | 100% |

The baseline is fictional scenario data documented in the Renewal Playbook; it must never be presented as customer research.

## 13. Scope

### Must build

- One Renewal Run with one visible exception and successful completion.
- Foundry IQ knowledge base with real citations.
- Work IQ integration spike; use it in the core demo if tenant access is confirmed.
- One hosted agent and deterministic workflow controller.
- Deterministic pricing and approval tools.
- Teams approval with approve, edit, escalate, and reject paths.
- SharePoint and mail execution after approval.
- Control Room with Run timeline, evidence, actions, audit and metrics.
- Automated tests for happy path, policy exception, evidence gap, unauthorized action and non-expiring contract.

### Explicitly out of scope

- Multiple cooperating agents solely for visual complexity.
- A second enterprise workflow.
- Multi-tenancy or customer onboarding automation.
- Fabric IQ unless the scenario changes to cross-domain entity reasoning.
- Autonomous contract negotiation.
- Unapproved customer communication.
- Production claims based on fictional data.
- M365 Copilot/Agent 365 publication as a dependency for the main demo; it is an optional distribution path after the core flow works.

## 14. Technical risks to resolve first

1. Confirm Hosted Agent availability in the selected Azure region and subscription.
2. Confirm Foundry IQ GA API functionality needed for the knowledge sources; use preview functionality only when it creates visible value that cannot be achieved through the GA path.
3. Confirm Work IQ API tenant access, delegated authentication, and retrieval of the required sample mail/meeting context.
4. Confirm Teams approval-card callback and Microsoft Graph permissions in the E5 sandbox.
5. Validate that the approved artifact hash and action allowlist survive edit/escalation paths.
6. Confirm that the complete hero flow can be reset and replayed reliably for filming.

## 15. Why not pivot to ImpactIQ or another blank-sheet scenario

A supplier-disruption workflow using Fabric IQ could be more visually ambitious and would demonstrate ontology-based impact reasoning. It would also require synthetic operational data, ontology modeling, event processing, policy retrieval, mitigation orchestration, and action execution before the core story works.

For a one-to-two-person human team, that increases the risk of delivering an impressive architecture with an incomplete workflow. InnexQ has the stronger feasibility-to-impact ratio and can still become a platform story: Renewal Run is the first workflow powered by a reusable Company IQ.

The scenario should be reconsidered only if the week-one spikes show that Foundry IQ or delegated Microsoft 365 integration cannot support the required demo reliably.

## 16. Judging alignment

| Criterion | InnexQ evidence |
|---|---|
| Inspiration | A digital coworker that carries proof and knows when it is not allowed to act. |
| Business Value | Fewer handoffs, faster renewals, controlled discounts, reduced revenue leakage, complete auditability. |
| Customer Focus | One recognizable account-manager workflow with a clear customer outcome. |
| Feasibility | One agent, one workflow, mainstream Microsoft 365 actions, deterministic safety boundaries. |
| Make Something | A deployed flow that detects, retrieves, reasons, requests authority, writes, sends, and logs. |

## 17. Working pitch

> Enterprise knowledge is everywhere, but business action still depends on people stitching it together. InnexQ turns that scattered knowledge into governed work. In one Renewal Run, it uses Microsoft IQ to assemble the right policy, contract, operational and work context; calculates commercial terms through deterministic tools; and produces a proof-carrying Decision Brief. A human approves the evidence and the exact actions in Teams. Only then does InnexQ write the quote, contact the customer and create a replayable audit trail. This is not another assistant that tells you what to do. It is a digital coworker that completes the workflow while keeping the human accountable and in control.

## 18. Official platform references

- [What is Foundry IQ?](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-foundry-iq)
- [Connect Foundry Agent Service to Foundry IQ](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect)
- [Microsoft Foundry Hosted Agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)
- [Microsoft Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/overview)
- [Work IQ overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/)
- [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Publish a Hosted Agent through Microsoft Agent 365](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/agent-365)

---

**Recommended decision:** Freeze this scenario after the four platform-access spikes succeed. Until then, freeze the customer problem, hero Run, safety rules and two-minute story; keep implementation details replaceable.


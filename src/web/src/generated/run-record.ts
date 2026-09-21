/* Generated from the v1 Pydantic JSON schema. Do not edit. */

export type ActorUserId = string;
export type ActorScenarioRole = string;
export type RequiredScenarioRole = string;
export type RuleId = string;
export type RuleVersion = string;
export type AuthorityVerdict = "authorized" | "unauthorized" | "escalation_required";
export type BriefHash = string;
export type BriefVersion = number;
export type Comment = string | null;
export type Decision = "approve" | "reject" | "edit" | "escalate";
export type DecisionId = string;
export type RunId = string;
export type SchemaVersion = string;
export type SubmittedAt = string;
export type ApprovalRequestedAt = string | null;
/**
 * @minItems 1
 */
export type Actions = [Action, ...Action[]];
export type ActionId = string;
export type ActionType = "sharepoint.create_file" | "graph.send_mail" | "teams.send_status";
export type ArtifactHash = string;
export type IdempotencyKey = string;
export type JsonValue = unknown;
export type BriefVersion1 = number;
export type ManifestId = string;
export type RunId1 = string;
export type SchemaVersion1 = string;
export type ActionManifestId = string;
export type Description = string;
export type OptionId = string;
export type RequiredScenarioRole1 = string;
export type Alternatives = Alternative[];
export type BriefVersion2 = number;
/**
 * @minItems 1
 */
export type Calculations = [CalculationRecord, ...CalculationRecord[]];
export type CalculationId = string;
export type ToolName = string;
export type ToolVersion = string;
export type Description1 = string;
export type GapId = string;
export type EvidenceGapKind = "missing" | "stale" | "conflicting" | "inaccessible";
export type RequiredResolution = string;
export type EvidenceGaps = EvidenceGap[];
/**
 * @minItems 1
 */
export type MaterialClaims = [MaterialClaim, ...MaterialClaim[]];
export type ClaimId = string;
/**
 * @minItems 1
 */
export type EvidenceIds = [string, ...string[]];
export type Text = string;
/**
 * @minItems 1
 */
export type PolicyChecks = [PolicyCheck, ...PolicyCheck[]];
export type CheckId = string;
/**
 * @minItems 1
 */
export type EvidenceIds1 = [string, ...string[]];
export type Explanation = string;
export type RequiredScenarioRole2 = string | null;
export type RuleId1 = string;
export type RuleVersion1 = string;
export type PolicyVerdict = "pass" | "fail" | "requires_approval";
export type DetailedSummary = string;
export type PlainLanguageSummary = string;
export type OptionId1 = string;
export type ServiceLevel = string;
export type Summary = string;
export type TermMonths = number;
export type RunId2 = string;
export type SchemaVersion2 = string;
export type BriefHash1 = string;
export type ActorUserId1 = string;
export type AuthorizationMode = "delegated" | "workload_identity";
export type TenantId = string;
export type Classification = "public" | "internal" | "confidential" | "restricted";
export type EvidenceId = string;
export type Excerpt = string;
export type RetrievedAt = string;
export type SchemaVersion3 = string;
export type SourceKind = "foundry_iq" | "work_iq" | "tool";
export type SourceLocator = string;
export type SourceName = string;
/**
 * @minItems 1
 */
export type SupportsClaimIds = [string, ...string[]];
export type Evidence = EvidenceItem[];
/**
 * @minItems 1
 * @maxItems 30
 */
export type Citations = [Citation, ...Citation[]];
export type Excerpt1 = string;
export type SourceId = string;
export type Title = string;
export type Url = string;
export type Summary1 = string;
export type Revision = number;
export type ContractId = string;
export type CorrelationId = string;
export type CreatedAt = string;
export type CurrentBriefHash = string | null;
export type CurrentBriefVersion = number;
export type OwnerUserId = string | null;
export type RunId3 = string;
export type SchemaVersion4 = string;
export type RunState =
  | "DETECTED"
  | "CONTEXT_ASSEMBLING"
  | "CONTEXT_ASSEMBLED"
  | "POLICY_VERIFIED"
  | "EVIDENCE_HOLD"
  | "AWAITING_APPROVAL"
  | "ESCALATED"
  | "APPROVED"
  | "EXECUTING"
  | "EXECUTION_FAILED"
  | "EXECUTED"
  | "CLOSED_REJECTED";
export type UpdatedAt = string;
export type WorkflowPack = "contract-renewal";

export interface RunRecord {
  action_status?: ActionStatus;
  approval?: ApprovalDecision | null;
  approval_requested_at?: ApprovalRequestedAt;
  envelope?: VersionedBrief | null;
  evidence?: Evidence;
  facts?: Facts;
  proposal?: AgentProposal | null;
  receipts?: Receipts;
  revision: Revision;
  run: Run;
  workflow_pack?: WorkflowPack;
}
export interface ActionStatus {
  [k: string]: "started" | "completed" | "unknown";
}
export interface ApprovalDecision {
  actor_user_id: ActorUserId;
  authority_result: AuthorityResult;
  brief_hash: BriefHash;
  brief_version: BriefVersion;
  comment?: Comment;
  decision: Decision;
  decision_id: DecisionId;
  run_id: RunId;
  schema_version?: SchemaVersion;
  submitted_at: SubmittedAt;
}
export interface AuthorityResult {
  actor_scenario_role: ActorScenarioRole;
  required_scenario_role: RequiredScenarioRole;
  rule_id: RuleId;
  rule_version: RuleVersion;
  verdict: AuthorityVerdict;
}
export interface VersionedBrief {
  action_manifest: ActionManifest;
  brief: DecisionBrief;
  brief_hash: BriefHash1;
}
export interface ActionManifest {
  actions: Actions;
  brief_version: BriefVersion1;
  manifest_id: ManifestId;
  run_id: RunId1;
  schema_version?: SchemaVersion1;
}
export interface Action {
  action_id: ActionId;
  action_type: ActionType;
  artifact_hash: ArtifactHash;
  idempotency_key: IdempotencyKey;
  parameters: Parameters;
}
export interface Parameters {
  [k: string]: JsonValue;
}
export interface DecisionBrief {
  action_manifest_id: ActionManifestId;
  alternatives: Alternatives;
  brief_version: BriefVersion2;
  calculations: Calculations;
  evidence_gaps: EvidenceGaps;
  material_claims: MaterialClaims;
  policy_checks: PolicyChecks;
  presentation: Presentation;
  recommendation: Recommendation;
  run_id: RunId2;
  schema_version?: SchemaVersion2;
}
export interface Alternative {
  description: Description;
  option_id: OptionId;
  required_scenario_role: RequiredScenarioRole1;
}
export interface CalculationRecord {
  calculation_id: CalculationId;
  inputs: Inputs;
  outputs: Outputs;
  tool_name: ToolName;
  tool_version: ToolVersion;
}
export interface Inputs {
  [k: string]: JsonValue;
}
export interface Outputs {
  [k: string]: JsonValue;
}
export interface EvidenceGap {
  description: Description1;
  gap_id: GapId;
  kind: EvidenceGapKind;
  required_resolution: RequiredResolution;
}
export interface MaterialClaim {
  claim_id: ClaimId;
  evidence_ids: EvidenceIds;
  text: Text;
}
export interface PolicyCheck {
  check_id: CheckId;
  evidence_ids: EvidenceIds1;
  explanation: Explanation;
  required_scenario_role?: RequiredScenarioRole2;
  rule_id: RuleId1;
  rule_version: RuleVersion1;
  verdict: PolicyVerdict;
}
export interface Presentation {
  customer_language_drafts: CustomerLanguageDrafts;
  detailed_summary: DetailedSummary;
  plain_language_summary: PlainLanguageSummary;
}
export interface CustomerLanguageDrafts {
  [k: string]: string;
}
export interface Recommendation {
  option_id: OptionId1;
  service_level: ServiceLevel;
  summary: Summary;
  term_months: TermMonths;
}
export interface EvidenceItem {
  actor_context: ActorContext;
  classification: Classification;
  evidence_id: EvidenceId;
  excerpt: Excerpt;
  retrieved_at: RetrievedAt;
  schema_version?: SchemaVersion3;
  source_kind: SourceKind;
  source_locator: SourceLocator;
  source_name: SourceName;
  supports_claim_ids: SupportsClaimIds;
}
export interface ActorContext {
  actor_user_id: ActorUserId1;
  authorization_mode: AuthorizationMode;
  tenant_id: TenantId;
}
export interface Facts {
  [k: string]: string;
}
export interface AgentProposal {
  citations: Citations;
  summary: Summary1;
}
export interface Citation {
  excerpt: Excerpt1;
  source_id: SourceId;
  title: Title;
  url: Url;
}
export interface Receipts {
  [k: string]: string;
}
export interface Run {
  contract_id: ContractId;
  correlation_id: CorrelationId;
  created_at: CreatedAt;
  current_brief_hash?: CurrentBriefHash;
  current_brief_version?: CurrentBriefVersion;
  owner_user_id?: OwnerUserId;
  run_id: RunId3;
  schema_version?: SchemaVersion4;
  state: RunState;
  updated_at: UpdatedAt;
}

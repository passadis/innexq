/* Generated from the v1 Pydantic JSON schema. Do not edit. */

export type AssignedUserId = string;
export type CaseId = string;
export type DecisionHash = string;
export type ActorUserId = string;
export type Action = "acknowledge" | "add_note" | "close_without_release";
export type CaseId1 = string;
export type CommandId = string;
export type DecisionHash1 = string;
export type ExpectedRevision = number;
export type Note = string;
export type OccurredAt = string;
export type Sequence = number;
/**
 * @maxItems 1000
 */
export type Events = CaseReviewEvent[];
export type RequestId = string;
export type Revision = number;
export type SchemaVersion = "1.0";
export type State = "open" | "acknowledged" | "closed_without_release";
export type TenantId = string;

export interface CaseReview {
  assigned_user_id: AssignedUserId;
  case_id: CaseId;
  decision_hash: DecisionHash;
  events?: Events;
  request_id: RequestId;
  revision?: Revision;
  schema_version?: SchemaVersion;
  state?: State;
  tenant_id: TenantId;
}
export interface CaseReviewEvent {
  actor_user_id: ActorUserId;
  command: CaseCommand;
  occurred_at: OccurredAt;
  sequence: Sequence;
}
export interface CaseCommand {
  action: Action;
  case_id: CaseId1;
  command_id: CommandId;
  decision_hash: DecisionHash1;
  expected_revision: ExpectedRevision;
  note?: Note;
}

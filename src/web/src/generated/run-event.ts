/* Generated from the v1 Pydantic JSON schema. Do not edit. */

export type ActorUserId = string;
export type CorrelationId = string;
export type EventId = string;
export type EventType = string;
export type OccurredAt = string;
export type RunId = string;
export type SchemaVersion = "1.0";
export type Sequence = number;
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

export interface RunEvent {
  actor_user_id: ActorUserId;
  correlation_id: CorrelationId;
  details?: Details;
  event_id: EventId;
  event_type: EventType;
  occurred_at: OccurredAt;
  run_id: RunId;
  schema_version?: SchemaVersion;
  sequence: Sequence;
  state: RunState;
}
export interface Details {
  [k: string]: string;
}

/* Generated from the v1 Pydantic JSON schema. Do not edit. */

export type Action = "acknowledge" | "add_note" | "close_without_release";
export type CaseId = string;
export type CommandId = string;
export type DecisionHash = string;
export type ExpectedRevision = number;
export type Note = string;

export interface CaseCommand {
  action: Action;
  case_id: CaseId;
  command_id: CommandId;
  decision_hash: DecisionHash;
  expected_revision: ExpectedRevision;
  note?: Note;
}

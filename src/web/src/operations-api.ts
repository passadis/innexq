import { validateConfig, type WebConfig } from './api';

export interface VerifiedToolActivity {
  attemptId: string;
  receiptId: string;
  specialist: 'document_analyst' | 'equipment_service';
  toolName: 'get_equipment_record' | 'list_equipment_documents' | 'analyze_document' | 'retrieve_policy';
  sourceVersion: string;
  documentId: string | null;
  completedAt: string;
}

export interface OperationsCaseView {
  requestId: string;
  caseId: string;
  customerId: string;
  equipmentId: string;
  assignedUserId: string;
  decisionHash: string;
  evaluatedAt: string;
  requestContext?: { customerMessages: string[]; interpretedIntent: 'certificate_request'; equipmentId: string; interpreterResponseId: string | null } | null;
  reasons: string[];
  checks: { name: string; verdict: 'pass' | 'fail' | 'unknown'; reason: string }[];
  fields: { documentId: string; documentVersion: string; sha256: string; label: string; value: string; page: number }[];
  specialists: { specialist: string; responseId: string; summary: string }[];
  toolActivity?: VerifiedToolActivity[];
  notification: { state: 'pending' | 'claimed' | 'delivered' | 'ambiguous'; receiptId: string | null };
}
export interface OperationsApi { list(signal?: AbortSignal): Promise<OperationsCaseView[]> }
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const digest = /^[0-9a-f]{64}$/i;
const failure = () => new Error('Operations cases are unavailable to this account.');
const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw failure();
  return value as Record<string, unknown>;
};
const text = (value: unknown, max = 2000): string => {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw failure();
  return value;
};
const identifier = (value: unknown): string => { const result = text(value); if (!uuid.test(result)) throw failure(); return result; };
const hash = (value: unknown): string => { const result = text(value); if (!digest.test(result)) throw failure(); return result; };
const array = (value: unknown, max = 500): unknown[] => { if (!Array.isArray(value) || value.length > max) throw failure(); return value; };
const roleTools = {
  document_analyst: ['list_equipment_documents', 'analyze_document'],
  equipment_service: ['get_equipment_record', 'retrieve_policy'],
};

function projectActivity(value: unknown): VerifiedToolActivity[] {
  if (value === undefined) return [];
  const entries = array(value, 12).map<VerifiedToolActivity>(value => {
    const item = object(value);
    if (Object.keys(item).some(key => !['attempt_id', 'receipt_id', 'specialist', 'tool_name', 'source_version', 'document_id', 'completed_at'].includes(key)) ||
        (item.specialist !== 'document_analyst' && item.specialist !== 'equipment_service') ||
        typeof item.tool_name !== 'string' || !roleTools[item.specialist].includes(item.tool_name)) throw failure();
    const documentId = item.document_id === null ? null : text(item.document_id, 105);
    if (documentId !== null && !/^DEMO-[A-Z0-9-]{1,100}$/.test(documentId)) throw failure();
    if ((item.tool_name === 'analyze_document') !== (documentId !== null)) throw failure();
    const completedAt = text(item.completed_at, 40);
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(completedAt) || Number.isNaN(Date.parse(completedAt))) throw failure();
    return { attemptId: identifier(item.attempt_id), receiptId: identifier(item.receipt_id), specialist: item.specialist,
      toolName: item.tool_name as VerifiedToolActivity['toolName'], sourceVersion: text(item.source_version, 200), documentId, completedAt };
  });
  if (new Set(entries.map(item => item.receiptId.toLowerCase())).size !== entries.length || new Set(entries.map(item => item.attemptId.toLowerCase())).size > 1) throw failure();
  return entries;
}

export function parseOperationsLink(search: string): { requestId: string } | { invalid: true } {
  const params = new URLSearchParams(search);
  const id = params.get('operations');
  if (params.getAll('operations').length !== 1 || !id || !uuid.test(id) || [...params.keys()].some(key => key !== 'operations')) return { invalid: true };
  return { requestId: id };
}

function projectCase(value: unknown): OperationsCaseView {
  const item = object(value), record = object(item.record), decision = object(record.decision);
  const ops = object(record.operations_case), sources = object(decision.sources), notification = object(item.notification);
  const requestId = identifier(record.request_id);
  if (record.workflow_pack !== 'certificate_fulfilment' || decision.outcome !== 'operations_required' ||
      decision.policy_id !== 'CERT-RELEASE-001' || decision.policy_version !== 1 || ops.state !== 'open') throw failure();
  const checks = array(decision.checks, 3).map<OperationsCaseView['checks'][number]>(value => {
    const check = object(value);
    if (check.verdict !== 'pass' && check.verdict !== 'fail' && check.verdict !== 'unknown') throw failure();
    return { name: text(check.name), verdict: check.verdict, reason: text(check.reason) };
  });
  if (checks.map(check => check.name).join(',') !== 'ownership,certificate_validity,service_status' || checks.every(check => check.verdict === 'pass')) throw failure();
  const reasons = array(ops.reason_codes, 30).map(value => text(value));
  if (!reasons.length) throw failure();
  let fields: OperationsCaseView['fields'] = [], specialists: OperationsCaseView['specialists'] = [], toolActivity: VerifiedToolActivity[] = [];
  if (sources.investigation != null) {
    const investigation = object(sources.investigation);
    if (investigation.request_id !== requestId || investigation.extraction_api !== '2024-11-30' || investigation.extraction_model !== 'prebuilt-layout') throw failure();
    fields = array(investigation.fields).map(value => {
      const field = object(value);
      if (typeof field.page !== 'number' || !Number.isSafeInteger(field.page) || field.page < 1) throw failure();
      return { documentId: text(field.document_id), documentVersion: text(field.document_version), sha256: hash(field.sha256), label: text(field.label), value: text(field.value), page: field.page };
    });
    specialists = array(investigation.specialists, 3).map(value => {
      const specialist = object(value);
      if (!['request_coordinator', 'document_analyst', 'equipment_service'].includes(text(specialist.specialist))) throw failure();
      return { specialist: text(specialist.specialist), responseId: text(specialist.response_id), summary: text(specialist.summary) };
    });
    if (new Set(specialists.map(item => item.specialist)).size !== specialists.length) throw failure();
    toolActivity = projectActivity(investigation.tool_activity);
  }
  if (notification.state !== 'pending' && notification.state !== 'claimed' && notification.state !== 'delivered' && notification.state !== 'ambiguous') throw failure();
  const receiptId = notification.receipt_id == null ? null : text(notification.receipt_id);
  if ((notification.state === 'delivered') !== !!receiptId) throw failure();
  const evaluatedAt = text(decision.evaluated_at);
  if (Number.isNaN(Date.parse(evaluatedAt))) throw failure();
  let requestContext: OperationsCaseView['requestContext'] = null;
  if (record.request_context != null) {
    const context = object(record.request_context);
    const customerMessages = array(context.customer_messages, 6).map(value => text(value, 1000));
    if (!customerMessages.length || context.interpreted_intent !== 'certificate_request' || context.equipment_id !== record.equipment_id ||
        Object.keys(context).some(key => !['customer_messages', 'interpreted_intent', 'equipment_id', 'interpreter_response_id'].includes(key))) throw failure();
    requestContext = { customerMessages, interpretedIntent: 'certificate_request', equipmentId: text(context.equipment_id), interpreterResponseId: context.interpreter_response_id == null ? null : text(context.interpreter_response_id) };
  }
  return { requestId, caseId: identifier(ops.case_id), customerId: text(record.customer_id), equipmentId: text(record.equipment_id), assignedUserId: identifier(ops.assigned_user_id), decisionHash: hash(record.decision_hash), evaluatedAt, requestContext, reasons, checks, fields, specialists, toolActivity, notification: { state: notification.state, receiptId } };
}

export function createOperationsApi(config: WebConfig, getToken: () => Promise<string>): OperationsApi {
  validateConfig(config);
  return {
    async list(signal) {
      const token = await getToken();
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const response = await fetch(config.apiOrigin + '/api/operations/certificates', { method: 'GET', headers: { Authorization: `Bearer ${token}` }, signal, cache: 'no-store', credentials: 'omit', redirect: 'error' });
      if (!response.ok) throw failure();
      const items = array(await response.json(), 100).map(projectCase);
      if (new Set(items.map(item => item.requestId)).size !== items.length) throw failure();
      return items;
    },
  };
}

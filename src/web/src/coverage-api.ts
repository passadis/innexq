import { validateConfig, type WebConfig } from './api';

export type CoverageStage = 'operations' | 'manager';
export type CoverageState =
  | 'CUSTOMER_REQUESTED' | 'EVIDENCE_ASSEMBLING' | 'ELIGIBILITY_VERIFIED' | 'PACKAGE_DRAFTED'
  | 'AWAITING_OPERATIONS_APPROVAL' | 'OPERATIONS_APPROVED' | 'AWAITING_MANAGER_APPROVAL'
  | 'MANAGER_APPROVED' | 'EXECUTING' | 'COMPLETED' | 'EVIDENCE_HOLD' | 'OPERATIONS_REJECTED'
  | 'MANAGER_REJECTED' | 'EXECUTION_FAILED' | 'CANCELLED';

export const COVERAGE_PROGRESS: Record<CoverageState, string> = {
  CUSTOMER_REQUESTED: 'Evidence review', EVIDENCE_ASSEMBLING: 'Evidence review',
  ELIGIBILITY_VERIFIED: 'Evidence review', PACKAGE_DRAFTED: 'Awaiting Operations',
  AWAITING_OPERATIONS_APPROVAL: 'Awaiting Operations', OPERATIONS_APPROVED: 'Awaiting Manager',
  AWAITING_MANAGER_APPROVAL: 'Awaiting Manager', MANAGER_APPROVED: 'Issuing documents',
  EXECUTING: 'Issuing documents', COMPLETED: 'Completed', EVIDENCE_HOLD: 'Held or rejected',
  OPERATIONS_REJECTED: 'Held or rejected', MANAGER_REJECTED: 'Held or rejected',
  EXECUTION_FAILED: 'Held or rejected', CANCELLED: 'Held or rejected',
};

export interface CoveragePackageView {
  version: number; hash: string; coverageMonths: number; serialNumber: string;
  quote: { currency: string; baseAmount: string; vatRatePercent: string; vatAmount: string; totalAmount: string };
  invoiceNotice: string;
  previousDocument: { documentId: string; documentVersion: string; sha256: string };
}
export interface CoverageDecisionView {
  decision: 'approve' | 'reject'; actorObjectId: string; submittedAt: string; rejectReason: string | null;
  decisionId: string;
}
export interface CoverageRenewalView {
  requestId: string; state: CoverageState; publicProgress: string; customerId: string;
  equipmentId: string; updatedAt: string; holdReasons: string[];
  package: CoveragePackageView | null;
  operationsDecision: CoverageDecisionView | null; managerDecision: CoverageDecisionView | null;
}
export interface CoverageCommand {
  decision: 'approve' | 'reject'; packageVersion: number; packageHash: string;
  noteSha256?: string; rejectReason?: string;
}
export interface CoverageApi {
  list(signal?: AbortSignal): Promise<CoverageRenewalView[]>;
  decide(requestId: string, stage: CoverageStage, command: CoverageCommand): Promise<CoverageRenewalView>;
}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const digest = /^[0-9a-f]{64}$/;
const money = /^\d{1,12}\.\d{2}$/;
const fail = () => new Error('Coverage renewals are unavailable. Refresh before taking another action.');
const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw fail();
  return value as Record<string, unknown>;
};
const text = (value: unknown, max = 2000): string => {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw fail();
  return value;
};
const amount = (value: unknown): string => { const result = text(value, 20); if (!money.test(result)) throw fail(); return result; };
const hash = (value: unknown): string => { const result = text(value, 64); if (!digest.test(result)) throw fail(); return result; };

function parseDecision(value: unknown, requestId: string, packageHash: string): CoverageDecisionView | null {
  if (value == null) return null;
  const item = object(value);
  if (item.request_id !== requestId || item.package_hash !== packageHash ||
      (item.decision !== 'approve' && item.decision !== 'reject') ||
      typeof item.actor_object_id !== 'string' || !uuid.test(item.actor_object_id) ||
      typeof item.decision_id !== 'string' || !uuid.test(item.decision_id)) throw fail();
  const submittedAt = text(item.submitted_at, 40);
  if (Number.isNaN(Date.parse(submittedAt))) throw fail();
  const rejectReason = item.reject_reason == null ? null : text(item.reject_reason, 500);
  if ((item.decision === 'reject') !== (rejectReason !== null)) throw fail();
  return { decision: item.decision, actorObjectId: item.actor_object_id, submittedAt, rejectReason, decisionId: item.decision_id };
}

export function parseCoverageRecord(value: unknown): CoverageRenewalView {
  const record = object(value);
  const requestId = text(record.request_id, 40);
  if (!uuid.test(requestId) || record.workflow_pack !== 'service-coverage-renewal' ||
      typeof record.state !== 'string' || !(record.state in COVERAGE_PROGRESS)) throw fail();
  const state = record.state as CoverageState;
  const updatedAt = text(record.updated_at, 40);
  if (Number.isNaN(Date.parse(updatedAt))) throw fail();
  const holdReasons = record.hold_reasons == null ? [] : (record.hold_reasons as unknown[]).map(reason => text(reason, 60));
  let packageView: CoveragePackageView | null = null;
  if (record.package != null) {
    const item = object(record.package), quote = object(item.quote), preview = object(item.invoice_preview);
    const previous = object(item.previous_document);
    if (item.request_id !== requestId || typeof item.package_version !== 'number' || item.package_version < 1 ||
        item.coverage_months !== 12 || quote.currency !== 'EUR') throw fail();
    const notice = text(preview.notice, 200);
    if (!notice.startsWith('SYNTHETIC DEMO')) throw fail();
    packageView = {
      version: item.package_version, hash: hash(record.package_hash), coverageMonths: 12,
      serialNumber: text(item.serial_number, 100),
      quote: { currency: 'EUR', baseAmount: amount(quote.base_amount), vatRatePercent: amount(quote.vat_rate_percent),
        vatAmount: amount(quote.vat_amount), totalAmount: amount(quote.total_amount) },
      invoiceNotice: notice,
      previousDocument: { documentId: text(previous.document_id, 105), documentVersion: text(previous.document_version, 200), sha256: hash(previous.sha256) },
    };
  }
  const packageHash = packageView?.hash ?? '';
  return {
    requestId, state, publicProgress: COVERAGE_PROGRESS[state],
    customerId: text(record.customer_id, 100), equipmentId: text(record.equipment_id, 100), updatedAt,
    holdReasons, package: packageView,
    operationsDecision: packageView ? parseDecision(record.operations_decision, requestId, packageHash) : null,
    managerDecision: packageView ? parseDecision(record.manager_decision, requestId, packageHash) : null,
  };
}

export function createCoverageApi(config: WebConfig, readToken: () => Promise<string>, writeToken: () => Promise<string>): CoverageApi {
  validateConfig(config);
  const base = `${config.apiOrigin}/api/operations/coverage`;
  return {
    async list(signal) {
      const token = await readToken();
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const response = await fetch(base, { method: 'GET', headers: { Authorization: `Bearer ${token}` }, signal, cache: 'no-store', credentials: 'omit', redirect: 'error' });
      if (!response.ok) throw fail();
      const payload = await response.json();
      if (!Array.isArray(payload) || payload.length > 200) throw fail();
      return payload.map(item => parseCoverageRecord(object(item).record));
    },
    async decide(requestId, stage, command) {
      if (!uuid.test(requestId)) throw fail();
      const token = await writeToken();
      const body = {
        decision: command.decision, package_version: command.packageVersion, package_hash: command.packageHash,
        ...(command.noteSha256 ? { note_sha256: command.noteSha256 } : {}),
        ...(command.rejectReason ? { reject_reason: command.rejectReason } : {}),
      };
      const response = await fetch(`${base}/${requestId}/${stage}-decision`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body), cache: 'no-store', credentials: 'omit', redirect: 'error',
      });
      if (!response.ok) throw fail();
      const result = parseCoverageRecord(await response.json());
      const recorded = stage === 'operations' ? result.operationsDecision : result.managerDecision;
      // The stored decision must reflect exactly what this client displayed and sent.
      if (result.requestId !== requestId || !recorded || recorded.decision !== command.decision ||
          result.package?.hash !== command.packageHash || result.package?.version !== command.packageVersion) throw fail();
      return result;
    },
  };
}

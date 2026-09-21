import { validateConfig, type WebConfig } from './api';
import type { CaseCommand } from './generated/case-command';
import type { CaseReview as ReviewContract } from './generated/case-review';

export type CaseReview = Required<ReviewContract>;
export type { CaseCommand };
export interface CaseReviewApi {
  read(requestId: string, signal?: AbortSignal): Promise<{ review: CaseReview; canManage: boolean }>;
  act(requestId: string, command: CaseCommand): Promise<CaseReview>;
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const digest = /^[0-9a-f]{64}$/;
const fail = () => new Error('Case review is unavailable. Refresh before taking another action.');
const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw fail();
  return value as Record<string, unknown>;
};
function parse(value: unknown, requestId: string, tenantId: string): CaseReview {
  const item = object(value);
  if (item.schema_version !== '1.0' || item.request_id !== requestId || item.tenant_id !== tenantId ||
      typeof item.case_id !== 'string' || !uuid.test(item.case_id) ||
      typeof item.assigned_user_id !== 'string' || !uuid.test(item.assigned_user_id) ||
      typeof item.decision_hash !== 'string' || !digest.test(item.decision_hash) ||
      !Array.isArray(item.events) || item.events.length > 1000 || item.revision !== item.events.length) throw fail();
  let state = 'open', previousTime = -Infinity;
  const seen = new Set<string>();
  const events = item.events.map((value: unknown, index: number) => {
    const event = object(value), command = object(event.command);
    if (event.sequence !== index + 1 || event.actor_user_id !== item.assigned_user_id ||
        typeof event.occurred_at !== 'string' || !Number.isFinite(Date.parse(event.occurred_at)) || Date.parse(event.occurred_at) < previousTime ||
        command.case_id !== item.case_id || command.decision_hash !== item.decision_hash || command.expected_revision !== index ||
        typeof command.command_id !== 'string' || !uuid.test(command.command_id) || seen.has(command.command_id) ||
        typeof command.note !== 'string' || command.note.length > 2000 ||
        !['acknowledge', 'add_note', 'close_without_release'].includes(String(command.action)) ||
        (command.action !== 'acknowledge' && !command.note.trim()) || state === 'closed_without_release') throw fail();
    if (command.action === 'acknowledge') { if (state !== 'open') throw fail(); state = 'acknowledged'; }
    if (command.action === 'close_without_release') state = 'closed_without_release';
    previousTime = Date.parse(event.occurred_at); seen.add(command.command_id);
    return { sequence: event.sequence, actor_user_id: event.actor_user_id, occurred_at: event.occurred_at,
      command: { command_id: command.command_id, case_id: command.case_id, decision_hash: command.decision_hash,
        expected_revision: command.expected_revision, action: command.action, note: command.note } };
  });
  if (item.state !== state) throw fail();
  // Return only the whitelisted staff contract, never arbitrary server properties.
  return { schema_version: '1.0', request_id: requestId, tenant_id: tenantId, case_id: item.case_id,
    assigned_user_id: item.assigned_user_id, decision_hash: item.decision_hash,
    revision: item.revision, state: item.state, events } as CaseReview;
}

export function createCaseReviewApi(config: WebConfig, readToken: () => Promise<string>, writeToken: () => Promise<string>): CaseReviewApi {
  validateConfig(config);
  const path = (id: string) => {
    if (!uuid.test(id)) throw fail();
    return `${config.apiOrigin}/api/operations/certificates/${id}`;
  };
  return {
    async read(id, signal) {
      const url = path(id), token = await readToken();
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const response = await fetch(url + '/review', { method: 'GET', headers: { Authorization: `Bearer ${token}` }, signal, cache: 'no-store', credentials: 'omit', redirect: 'error' });
      if (!response.ok) throw fail();
      const payload = object(await response.json());
      if (typeof payload.can_manage !== 'boolean') throw fail();
      return { review: parse(payload.review, id, config.tenantId), canManage: payload.can_manage };
    },
    async act(id, command) {
      const url = path(id), token = await writeToken();
      const response = await fetch(url + '/actions', { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify(command), cache: 'no-store', credentials: 'omit', redirect: 'error' });
      if (!response.ok) throw fail();
      const result = parse(await response.json(), id, config.tenantId);
      const event = result.events.find(event => event.command.command_id === command.command_id);
      if (!event || Object.entries(command).some(([key, value]) => event.command[key as keyof CaseCommand] !== value)) throw fail();
      return result;
    },
  };
}

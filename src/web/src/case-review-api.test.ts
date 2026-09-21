import { afterEach, expect, it, vi } from 'vitest';
import { createCaseReviewApi, type CaseCommand, type CaseReview } from './case-review-api';

const id = '22222222-2222-4222-8222-222222222222';
const config = { tenantId: '35de4c50-7dcd-4871-8685-61789c017da2', clientId: id, apiOrigin: 'https://api.example.azurecontainerapps.io', apiScope: `api://${id}/Runs.Read` };
const review: CaseReview = { schema_version: '1.0', request_id: id, tenant_id: config.tenantId, case_id: id, assigned_user_id: id, decision_hash: 'a'.repeat(64), revision: 0, state: 'open', events: [] };
const command: CaseCommand = { command_id: id, case_id: id, decision_hash: review.decision_hash, expected_revision: 0, action: 'acknowledge', note: '' };
const updated = { ...review, revision: 1, state: 'acknowledged', events: [{ sequence: 1, actor_user_id: id, occurred_at: '2026-09-15T00:00:00Z', command }] };
afterEach(() => vi.unstubAllGlobals());
it('uses separate write token, exact command binding, and no automatic retries', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ review, can_manage: true }) }).mockResolvedValueOnce({ ok: true, json: async () => updated });
  vi.stubGlobal('fetch', fetcher);
  const read = vi.fn(async () => 'read-only-test'), write = vi.fn(async () => 'write-test');
  const api = createCaseReviewApi(config, read, write);
  expect((await api.read(id)).canManage).toBe(true); expect(write).not.toHaveBeenCalled();
  expect((await api.act(id, command)).state).toBe('acknowledged');
  expect(write).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[1][1]).toMatchObject({ method: 'POST', credentials: 'omit', redirect: 'error', cache: 'no-store', body: JSON.stringify(command), headers: { Authorization: 'Bearer write-test' } });
  fetcher.mockRejectedValue(new Error('private details'));
  await expect(api.act(id, command)).rejects.toThrow();
  expect(fetcher).toHaveBeenCalledTimes(3);
});
it('rejects mismatched tenants, requests, roles, audit states and server error content', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  const api = createCaseReviewApi(config, async () => 'test', async () => 'test');
  for (const payload of [
    { review: { ...review, request_id: config.tenantId }, can_manage: true },
    { review: { ...review, tenant_id: id }, can_manage: true },
    { review, can_manage: 'true' },
    { review: { ...updated, state: 'closed_without_release' }, can_manage: true },
    { review: { ...updated, events: [...updated.events, ...updated.events], revision: 2 }, can_manage: true },
  ]) {
    fetcher.mockResolvedValue({ ok: true, json: async () => payload });
    await expect(api.read(id)).rejects.toThrow('unavailable');
  }
  const json = vi.fn(); fetcher.mockResolvedValue({ ok: false, status: 403, json });
  await expect(api.read(id)).rejects.toThrow('unavailable'); expect(json).not.toHaveBeenCalled();
  fetcher.mockResolvedValue({ ok: true, json: async () => review });
  await expect(api.act(id, command)).rejects.toThrow('unavailable');
});
it('rejects invalid links and aborts before fetching after token acquisition', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  const api = createCaseReviewApi(config, async () => 'test', async () => 'test');
  await expect(api.read('../runs')).rejects.toThrow('unavailable');
  const controller = new AbortController(); controller.abort();
  await expect(api.read(id, controller.signal)).rejects.toThrow('Aborted');
  expect(fetcher).not.toHaveBeenCalled();
});

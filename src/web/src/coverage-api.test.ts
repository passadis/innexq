import { afterEach, expect, it, vi } from 'vitest';
import { createCoverageApi, type CoverageCommand } from './coverage-api';

const id = '22222222-2222-4222-8222-222222222222';
const actor = '33333333-3333-4333-8333-333333333333';
const hash = 'a'.repeat(64);
const config = { tenantId: '35de4c50-7dcd-4871-8685-61789c017da2', clientId: id, apiOrigin: 'https://api.example.azurecontainerapps.io', apiScope: `api://${id}/Runs.Read` };

function record(state = 'AWAITING_OPERATIONS_APPROVAL', extra: Record<string, unknown> = {}) {
  return {
    request_id: id, workflow_pack: 'service-coverage-renewal', state,
    customer_id: 'DEMO-FAB', equipment_id: 'DEMO-COV-001', updated_at: '2026-09-22T12:00:00Z',
    hold_reasons: [], package_hash: hash,
    package: {
      request_id: id, package_version: 1, coverage_months: 12, serial_number: 'SER-1',
      quote: { currency: 'EUR', base_amount: '8500.00', vat_rate_percent: '24.00', vat_amount: '2040.00', total_amount: '10540.00' },
      invoice_preview: { notice: 'SYNTHETIC DEMO — NOT A FISCAL OR TAX DOCUMENT' },
      previous_document: { document_id: 'DEMO-COV-001-COVERAGE-PDF', document_version: 'v1', sha256: hash },
    },
    operations_decision: null, manager_decision: null, ...extra,
  };
}
const command: CoverageCommand = { decision: 'approve', packageVersion: 1, packageHash: hash };
afterEach(() => vi.unstubAllGlobals());

it('lists renewals with derived public progress and separate write token on decisions', async () => {
  const approved = record('AWAITING_MANAGER_APPROVAL', {
    operations_decision: { request_id: id, package_hash: hash, package_version: 1, decision: 'approve', actor_object_id: actor, decision_id: actor, submitted_at: '2026-09-22T12:05:00Z', reject_reason: null },
  });
  const fetcher = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => [{ record: record(), public_progress: 'Awaiting Operations' }] })
    .mockResolvedValueOnce({ ok: true, json: async () => approved });
  vi.stubGlobal('fetch', fetcher);
  const read = vi.fn(async () => 'read-test'), write = vi.fn(async () => 'write-test');
  const api = createCoverageApi(config, read, write);
  const listing = await api.list();
  expect(listing[0].publicProgress).toBe('Awaiting Operations');
  expect(listing[0].package?.quote.totalAmount).toBe('10540.00');
  expect(write).not.toHaveBeenCalled();
  const result = await api.decide(id, 'operations', command);
  expect(result.operationsDecision?.decision).toBe('approve');
  expect(fetcher.mock.calls[1][0]).toBe(`${config.apiOrigin}/api/operations/coverage/${id}/operations-decision`);
  expect(fetcher.mock.calls[1][1]).toMatchObject({ method: 'POST', credentials: 'omit', redirect: 'error', cache: 'no-store', headers: { Authorization: 'Bearer write-test' } });
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ decision: 'approve', package_version: 1, package_hash: hash });
});

it('rejects tampered packs, drifted hashes and unconfirmed decisions', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  const api = createCoverageApi(config, async () => 'test', async () => 'test');
  for (const payload of [
    [{ record: record('COMPLETED', { workflow_pack: 'certificate_fulfilment' }), public_progress: 'Completed' }],
    [{ record: record('NOT_A_STATE'), public_progress: 'Completed' }],
    [{ record: record('AWAITING_OPERATIONS_APPROVAL', { package_hash: 'zz' }), public_progress: 'Awaiting Operations' }],
  ]) {
    fetcher.mockResolvedValue({ ok: true, json: async () => payload });
    await expect(api.list()).rejects.toThrow('unavailable');
  }
  // A decision response that does not record the sent decision is refused.
  fetcher.mockResolvedValue({ ok: true, json: async () => record() });
  await expect(api.decide(id, 'operations', command)).rejects.toThrow('unavailable');
  fetcher.mockResolvedValue({ ok: false, status: 403, json: vi.fn() });
  await expect(api.decide(id, 'manager', command)).rejects.toThrow('unavailable');
  await expect(api.decide('../runs', 'operations', command)).rejects.toThrow('unavailable');
});

it('requires the synthetic invoice notice and euro quote strings', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  const api = createCoverageApi(config, async () => 'test', async () => 'test');
  const bad = record();
  (bad.package.invoice_preview as { notice: string }).notice = 'Official tax invoice';
  fetcher.mockResolvedValue({ ok: true, json: async () => [{ record: bad, public_progress: 'Awaiting Operations' }] });
  await expect(api.list()).rejects.toThrow('unavailable');
  const wrongCurrency = record();
  (wrongCurrency.package.quote as { currency: string }).currency = 'USD';
  fetcher.mockResolvedValue({ ok: true, json: async () => [{ record: wrongCurrency, public_progress: 'Awaiting Operations' }] });
  await expect(api.list()).rejects.toThrow('unavailable');
});

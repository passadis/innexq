import { afterEach, describe, expect, it, vi } from 'vitest';
import { createOperationsApi, parseOperationsLink } from './operations-api';

const config = { tenantId: '35de4c50-7dcd-4871-8685-61789c017da2', clientId: '11111111-1111-4111-8111-111111111111', apiOrigin: 'https://api.example.azurecontainerapps.io', apiScope: 'api://11111111-1111-4111-8111-111111111111/Runs.Read' };
const id = '22222222-2222-4222-8222-222222222222';
const proof = { document_id: 'DEMO-SERVICE-002', document_version: 'v1', sha256: 'a'.repeat(64), label: 'Valid until', value: '2026-09-10', page: 2, polygon: [0, 0, 1, 0, 1, 1, 0, 1] };
const activity = { attempt_id: id, receipt_id: config.clientId, specialist: 'document_analyst', tool_name: 'analyze_document', source_version: 'registry-v1', document_id: 'DEMO-SERVICE-002', completed_at: '2026-09-11T00:00:00Z' };
function item() {
  return {
    record: { workflow_pack: 'certificate_fulfilment', request_id: id, customer_id: 'DEMO-FAB', equipment_id: 'DEMO-PT-002', decision_hash: 'b'.repeat(64),
      operations_case: { case_id: config.clientId, assigned_user_id: config.clientId, reason_codes: ['service_not_current'], state: 'open' },
      decision: { outcome: 'operations_required', policy_id: 'CERT-RELEASE-001', policy_version: 1, evaluated_at: '2026-09-11T00:00:00Z',
        checks: [{ name: 'ownership', verdict: 'pass', reason: 'passed' }, { name: 'certificate_validity', verdict: 'pass', reason: 'passed' }, { name: 'service_status', verdict: 'fail', reason: 'service_not_current' }],
        sources: { investigation: { request_id: id, extraction_api: '2024-11-30', extraction_model: 'prebuilt-layout', fields: [proof], specialists: [{ specialist: 'equipment_service', response_id: 'response-equipment', summary: 'Service evidence requires Operations review.' }] } },
      },
    },
    notification: { state: 'pending', receipt_id: null as string | null },
  };
}
afterEach(() => vi.unstubAllGlobals());

describe('Operations API and links', () => {
  it('projects only recorded bounded tool activity and leaves legacy activity empty', async () => {
    const value = item();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [value] }));
    const api = createOperationsApi(config, async () => 'test-only');
    expect((await api.list())[0].toolActivity).toEqual([]);
    Object.assign(value.record.decision.sources.investigation, { tool_activity: [activity] });
    expect((await api.list())[0].toolActivity).toEqual([{ attemptId: id, receiptId: config.clientId, specialist: 'document_analyst', toolName: 'analyze_document', sourceVersion: 'registry-v1', documentId: 'DEMO-SERVICE-002', completedAt: activity.completed_at }]);
    Object.assign(value.record.decision.sources.investigation, { tool_activity: [] });
    expect((await api.list())[0].toolActivity).toEqual([]);
  });
  it('rejects malformed, forged-role, duplicate and excessive activity without exposing payloads', async () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    const api = createOperationsApi(config, async () => 'test-only');
    const badEntries = [null, 'not a list', [null], [activity, activity], Array(13).fill(activity),
      [{ ...activity, attempt_id: 'invalid' }], [{ ...activity, receipt_id: 'javascript:alert(1)' }],
      [{ ...activity, specialist: 'executor' }], [{ ...activity, specialist: 'equipment_service' }],
      [{ ...activity, tool_name: 'send_email' }], [{ ...activity, tool_name: '<img src=x>' }],
      [{ ...activity, document_id: 'https://foreign.example/private.pdf' }], [{ ...activity, document_id: null }],
      [{ ...activity, tool_name: 'list_equipment_documents' }], [{ ...activity, completed_at: 'today' }],
      [{ ...activity, completed_at: '2026-09-11T00:00:00' }], [{ ...activity, completed_at: '2026-99-11T00:00:00Z' }],
      [{ ...activity, source_version: '' }], [{ ...activity, source_version: 'x'.repeat(201) }],
      [{ ...activity, payload: { unexpected_field: 'not for this view' } }],
      [activity, { ...activity, receipt_id: id, attempt_id: config.clientId }]];
    for (const entries of badEntries) {
      const value = item(); Object.assign(value.record.decision.sources.investigation, { tool_activity: entries });
      fetcher.mockResolvedValue({ ok: true, json: async () => [value] });
      await expect(api.list()).rejects.toThrow('unavailable');
    }
  });
  it('accepts each tool only for its expected specialist and treats version text as data', async () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    const api = createOperationsApi(config, async () => 'test-only');
    for (const [specialist, tool_name] of [['document_analyst', 'list_equipment_documents'], ['equipment_service', 'get_equipment_record'], ['equipment_service', 'retrieve_policy']]) {
      const value = item(); Object.assign(value.record.decision.sources.investigation, { tool_activity: [{ ...activity, specialist, tool_name, document_id: null, source_version: '<script>not executable</script>' }] });
      fetcher.mockResolvedValue({ ok: true, json: async () => [value] });
      expect((await api.list())[0].toolActivity?.[0].sourceVersion).toBe('<script>not executable</script>');
    }
  });
  it('projects bounded customer context and preserves legacy absent/null context', async () => {
    const value = item();
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => [value] }); vi.stubGlobal('fetch', fetcher);
    const api = createOperationsApi(config, async () => 'test-only');
    expect((await api.list())[0].requestContext).toBeNull();
    Object.assign(value.record, { request_context: null });
    expect((await api.list())[0].requestContext).toBeNull();
    Object.assign(value.record, { request_context: { customer_messages: ['Please provide PT-002 certificate.'], interpreted_intent: 'certificate_request', equipment_id: value.record.equipment_id, interpreter_response_id: 'response-intent' } });
    expect((await api.list())[0].requestContext).toEqual({ customerMessages: ['Please provide PT-002 certificate.'], interpretedIntent: 'certificate_request', equipmentId: 'DEMO-PT-002', interpreterResponseId: 'response-intent' });
  });
  it('rejects invalid, unbounded or equipment-mismatched customer context', async () => {
    const base = { customer_messages: ['Please provide the certificate.'], interpreted_intent: 'certificate_request', equipment_id: 'DEMO-PT-002', interpreter_response_id: null };
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    const api = createOperationsApi(config, async () => 'test-only');
    for (const context of [{ ...base, customer_messages: [] }, { ...base, customer_messages: Array(7).fill('message') }, { ...base, customer_messages: ['x'.repeat(1001)] }, { ...base, customer_messages: [false] }, { ...base, interpreted_intent: 'service_request' }, { ...base, equipment_id: 'DEMO-PT-001' }, { ...base, interpreter_response_id: {} }, { ...base, unauthorized: true }]) {
      const value = item(); Object.assign(value.record, { request_context: context });
      fetcher.mockResolvedValue({ ok: true, json: async () => [value] });
      await expect(api.list()).rejects.toThrow('unavailable');
    }
  });
  it('allows only an unambiguous request UUID deep link', () => {
    expect(parseOperationsLink(`?operations=${id}`)).toEqual({ requestId: id });
    for (const query of ['', '?operations=', '?operations=../runs', `?operations=${id}&operations=${id}`, `?operations=${id}&run=${id}`]) expect(parseOperationsLink(query)).toEqual({ invalid: true });
  });
  it('reads cases without cookies, redirects, mutations or customer authority', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => [item()] });
    vi.stubGlobal('fetch', fetcher);
    const cases = await createOperationsApi(config, async () => 'test-only').list();
    expect(fetcher).toHaveBeenCalledWith(config.apiOrigin + '/api/operations/certificates', expect.objectContaining({ method: 'GET', credentials: 'omit', redirect: 'error', cache: 'no-store' }));
    expect(cases[0]).toMatchObject({ requestId: id, equipmentId: 'DEMO-PT-002', notification: { state: 'pending', receiptId: null }, fields: [{ documentId: proof.document_id, page: 2, sha256: proof.sha256 }] });
    expect(cases[0]).not.toHaveProperty('record');
  });
  it('rejects mismatched investigation, invalid page evidence and duplicate requests', async () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    const api = createOperationsApi(config, async () => 'test-only');
    const mismatched = item(); mismatched.record.decision.sources.investigation.request_id = config.clientId;
    const badPage = item(); badPage.record.decision.sources.investigation.fields = [{ ...proof, page: 0 }];
    for (const records of [[mismatched], [badPage], [item(), item()]]) {
      fetcher.mockResolvedValue({ ok: true, json: async () => records });
      await expect(api.list()).rejects.toThrow('unavailable');
    }
  });
  it('does not label a notification delivered without its recorded receipt', async () => {
    const value = item(); value.notification.state = 'delivered';
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => [value] }); vi.stubGlobal('fetch', fetcher);
    const api = createOperationsApi(config, async () => 'test-only');
    await expect(api.list()).rejects.toThrow('unavailable');
    value.notification.receipt_id = 'teams-activity-id';
    expect((await api.list())[0].notification).toEqual({ state: 'delivered', receiptId: 'teams-activity-id' });
  });
  it('does not parse unauthorized error content or send after aborted token acquisition', async () => {
    const json = vi.fn(); const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 403, json }); vi.stubGlobal('fetch', fetcher);
    const api = createOperationsApi(config, async () => 'test-only');
    await expect(api.list()).rejects.toThrow('unavailable');
    expect(json).not.toHaveBeenCalled();
    fetcher.mockClear(); const controller = new AbortController(); controller.abort();
    await expect(api.list(controller.signal)).rejects.toThrow('Aborted');
    expect(fetcher).not.toHaveBeenCalled();
  });
});

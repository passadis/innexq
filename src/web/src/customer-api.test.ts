import { afterEach, describe, expect, it, vi } from 'vitest';
import { createCustomerApi, validateCustomerConfig } from './customer-api';

const config = { tenantId: '35de4c50-7dcd-4871-8685-61789c017da2', clientId: '11111111-1111-4111-8111-111111111111', apiOrigin: 'https://api.example.azurecontainerapps.io', apiScope: 'api://11111111-1111-4111-8111-111111111111/Certificates.Request' };
const id = '22222222-2222-4222-8222-222222222222';
const input = { request_id: id, equipment_id: 'DEMO-PT-001', prompt: 'Please send my existing certificate.' };
const catalog = { customer_name: 'Fictional customer', equipment: [{ equipment_id: input.equipment_id, name: 'Pallet carrier', serial_number: 'DEMO-001' }], presets: [{ equipment_id: input.equipment_id, prompt: input.prompt }] };
const status = { request_id: id, status: 'release_ready', message: 'Your certificate is ready.' };
const messageInput = { message_id: id, prompt: 'Is service for PT-001 up to date?', equipment_id: null, parent_message_id: null };
const answer = { message_id: id, intent: 'service_status', equipment_id: 'DEMO-PT-001', kind: 'answer', message: 'Service evidence is current.', as_of: '2026-09-17T10:00:00Z', citations: [{ document_id: 'service-001', document_version: 'v1', page: 1, label: 'Due date', value: '2026-12-10' }], can_confirm: false };
afterEach(() => vi.unstubAllGlobals());

describe('customer API', () => {
  it('projects only public case stage and timestamp; rejects inconsistent progress', async () => {
    const closed = { ...status, status: 'operations_required', case_status: 'closed_without_release', updated_at: '2026-09-18T09:00:00Z' };
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...closed, notes: 'PRIVATE', events: [{ note: 'PRIVATE' }], assigned_user_id: 'PRIVATE' }) });
    vi.stubGlobal('fetch', fetcher);
    const api = createCustomerApi(config, async () => 'test-only');
    expect(await api.status(id)).toEqual(closed);
    for (const bad of [
      { ...closed, case_status: 'approved' }, { ...closed, status: 'release_ready' },
      { ...closed, case_status: 'not_required' }, { ...closed, updated_at: 'yesterday' },
      { ...closed, updated_at: '2026-09-18T09:00:00' },
      { ...closed, updated_at: undefined }, { ...closed, case_status: undefined },
    ]) {
      fetcher.mockResolvedValue({ ok: true, json: async () => bad });
      await expect(api.status(id)).rejects.toThrow('unavailable');
    }
  });
  it('sends only whitelisted message fields and keeps only public response evidence', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...answer, actor_id: 'private', evidence: 'private', citations: [{ ...answer.citations[0], private_url: 'https://internal.test' }] }) });
    vi.stubGlobal('fetch', fetcher);
    const api = createCustomerApi(config, async () => 'test-only');
    expect(await api.message({ ...messageInput, ...{ approved: true, customer_id: 'private' } })).toEqual(answer);
    expect(fetcher).toHaveBeenCalledWith(config.apiOrigin + '/api/customer/messages', expect.objectContaining({ method: 'POST', body: JSON.stringify(messageInput), credentials: 'omit', cache: 'no-store', redirect: 'error' }));
  });

  it('confirms only the exact message id using an empty authenticated POST', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => status });
    vi.stubGlobal('fetch', fetcher);
    const api = createCustomerApi(config, async () => 'test-only');
    expect(await api.confirm(id)).toEqual(status);
    expect(fetcher).toHaveBeenCalledWith(config.apiOrigin + `/api/customer/messages/${id}/confirm`, expect.objectContaining({ method: 'POST', body: '{}', credentials: 'omit', redirect: 'error' }));
    await expect(api.confirm('../runs')).rejects.toThrow('Invalid request');
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it('rejects missing fields, mismatched ids, invalid intent, dates, citations and fabricated confirmation', async () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    const api = createCustomerApi(config, async () => 'test-only');
    const invalid = [
      ...Object.keys(answer).map(key => Object.fromEntries(Object.entries(answer).filter(([field]) => field !== key))),
      { ...answer, message_id: config.clientId }, { ...answer, intent: 'execute' }, { ...answer, kind: 'approved' },
      { ...answer, message: '' }, { ...answer, message: 'x'.repeat(2001) }, { ...answer, equipment_id: '../private' },
      { ...answer, as_of: 'yesterday' }, { ...answer, as_of: '2026-99-99T10:00:00Z' },
      { ...answer, citations: Array(31).fill(answer.citations[0]) },
      { ...answer, citations: [{ ...answer.citations[0], page: 0 }] },
      { ...answer, citations: [{ ...answer.citations[0], page: 1.5 }] },
      { ...answer, citations: [{ ...answer.citations[0], document_version: null }] },
      { ...answer, can_confirm: true }, { ...answer, kind: 'confirmation_required', can_confirm: true },
      { ...answer, intent: 'certificate_request', kind: 'confirmation_required', can_confirm: true, equipment_id: null },
      { ...answer, intent: 'certificate_request', kind: 'confirmation_required', can_confirm: false },
    ];
    for (const value of invalid) {
      fetcher.mockResolvedValue({ ok: true, json: async () => value });
      await expect(api.message(messageInput)).rejects.toThrow('unavailable');
    }
  });

  it('rejects invalid message inputs before sending a token', async () => {
    const fetcher = vi.fn(); const token = vi.fn().mockResolvedValue('test-only'); vi.stubGlobal('fetch', fetcher);
    const api = createCustomerApi(config, token);
    for (const value of [{ ...messageInput, prompt: ' ' }, { ...messageInput, prompt: 'x'.repeat(1001) }, { ...messageInput, message_id: '../runs' }, { ...messageInput, parent_message_id: 'invalid' }, { ...messageInput, equipment_id: 'customer-elsewhere' }]) {
      await expect(api.message(value)).rejects.toThrow('Enter a message');
    }
    expect(fetcher).not.toHaveBeenCalled(); expect(token).not.toHaveBeenCalled();
  });

  it('uses only the customer scope and an exact trusted HTTPS API origin', () => {
    expect(validateCustomerConfig(config)).toEqual(config);
    for (const apiScope of ['api://11111111-1111-4111-8111-111111111111/Runs.Read', 'https://graph.microsoft.com/Mail.Send']) expect(() => validateCustomerConfig({ ...config, apiScope })).toThrow();
    for (const apiOrigin of ['http://api.example.azurecontainerapps.io', 'https://evil.test', 'https://api.example.azurecontainerapps.io/path', 'https://api.example.azurecontainerapps.io?target=x']) expect(() => validateCustomerConfig({ ...config, apiOrigin })).toThrow();
  });

  it('sends authenticated customer requests without cookies or redirects and strips extra authority fields', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => status });
    vi.stubGlobal('fetch', fetcher);
    const api = createCustomerApi(config, async () => 'test-only');
    await api.request({ ...input, ...{ customer_id: 'other-customer', actor_id: 'other-actor', approved: true } });
    expect(fetcher).toHaveBeenCalledWith(config.apiOrigin + '/api/customer/requests', expect.objectContaining({ method: 'POST', cache: 'no-store', credentials: 'omit', redirect: 'error', body: JSON.stringify(input), headers: { Authorization: 'Bearer test-only', 'Content-Type': 'application/json' } }));
  });

  it('retains only catalog fields and validates preset equipment membership', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...catalog, internal_evidence: 'private' }) });
    vi.stubGlobal('fetch', fetcher);
    expect(await createCustomerApi(config, async () => 'test-only').catalog()).toEqual(catalog);
    fetcher.mockResolvedValue({ ok: true, json: async () => ({ ...catalog, presets: [{ equipment_id: 'other-customer-machine', prompt: 'Certificate' }] }) });
    await expect(createCustomerApi(config, async () => 'test-only').catalog()).rejects.toThrow('unavailable');
  });

  it('rejects over ten presets, duplicate equipment, and unknown request states', async () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    const api = createCustomerApi(config, async () => 'test-only');
    for (const value of [{ ...catalog, presets: Array(11).fill(catalog.presets[0]) }, { ...catalog, equipment: [catalog.equipment[0], catalog.equipment[0]] }]) {
      fetcher.mockResolvedValue({ ok: true, json: async () => value });
      await expect(api.catalog()).rejects.toThrow('unavailable');
    }
    fetcher.mockResolvedValue({ ok: true, json: async () => ({ ...status, status: 'approved_by_agent' }) });
    await expect(api.status(id)).rejects.toThrow('unavailable');
  });

  it('rejects mismatched request IDs and never retains internal source records', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...status, sources: { private: 'evidence' } }) });
    vi.stubGlobal('fetch', fetcher);
    const api = createCustomerApi(config, async () => 'test-only');
    expect(await api.status(id)).toEqual(status);
    fetcher.mockResolvedValue({ ok: true, json: async () => ({ ...status, request_id: config.clientId }) });
    await expect(api.status(id)).rejects.toThrow('unavailable');
  });

  it('does not send tokens for unsafe identifiers, blank prompts, or aborted actions', async () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    const api = createCustomerApi(config, async () => 'test-only');
    await expect(api.status('../runs')).rejects.toThrow('Invalid request');
    await expect(api.pdf('//evil.test')).rejects.toThrow('Invalid request');
    await expect(api.request({ ...input, prompt: ' ' })).rejects.toThrow('Choose equipment');
    const controller = new AbortController(); controller.abort();
    await expect(api.catalog(controller.signal)).rejects.toThrow('Aborted');
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('does not expose server error payloads', async () => {
    const json = vi.fn().mockResolvedValue({ detail: 'private source document and token' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, json }));
    await expect(createCustomerApi(config, async () => 'test-only').catalog()).rejects.toThrow('certificate service is unavailable');
    expect(json).not.toHaveBeenCalled();
  });

  it('returns bounded PDF blobs only and never navigates to an external download URL', async () => {
    const pdf = new Blob(['%PDF-1.7\nsynthetic-test-only'], { type: 'application/pdf' });
    const fetcher = vi.fn().mockResolvedValue({ ok: true, headers: new Headers({ 'content-type': 'application/pdf' }), blob: async () => pdf });
    vi.stubGlobal('fetch', fetcher);
    const api = createCustomerApi(config, async () => 'test-only');
    expect(await api.pdf(id)).toBe(pdf);
    expect(fetcher).toHaveBeenCalledWith(config.apiOrigin + `/api/customer/requests/${id}/pdf`, expect.objectContaining({ method: 'GET', redirect: 'error' }));
    for (const value of [{ headers: new Headers({ 'content-type': 'text/html' }), blob: async () => pdf }, { headers: new Headers({ 'content-type': 'application/pdf' }), blob: async () => new Blob([]) }, { headers: new Headers({ 'content-type': 'application/pdf' }), blob: async () => ({ size: 21 * 1024 * 1024 }) }]) {
      fetcher.mockResolvedValue({ ok: true, ...value });
      await expect(api.pdf(id)).rejects.toThrow('unavailable');
    }
  });
});

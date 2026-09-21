import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CustomerPortal } from './CustomerPortal';
import type { CustomerApi, CustomerCatalog, CustomerMessage, CustomerRequestStatus } from './customer-api';

const catalog: CustomerCatalog = {
  customer_name: 'Fictional Fabrikam',
  equipment: [{ equipment_id: 'DEMO-PT-001', name: 'Pallet carrier', serial_number: 'DEMO-SERIAL-001' }, { equipment_id: 'DEMO-PT-002', name: 'Pallet carrier', serial_number: 'DEMO-SERIAL-002' }],
  presets: [{ equipment_id: 'DEMO-PT-001', prompt: 'Please provide the existing certificate for DEMO-PT-001.' }],
};
const id = '22222222-2222-4222-8222-222222222222';
const ready: CustomerRequestStatus = { request_id: id, status: 'release_ready', message: 'Certificate ready.' };
const proposal: CustomerMessage = { message_id: id, intent: 'certificate_request', equipment_id: 'DEMO-PT-001', kind: 'confirmation_required', message: 'Would you like to request this certificate?', as_of: null, citations: [], can_confirm: true };

function client(): CustomerApi {
  return {
    catalog: vi.fn().mockResolvedValue(catalog),
    request: vi.fn().mockImplementation(async input => ({ ...ready, request_id: input.request_id })),
    message: vi.fn().mockImplementation(async input => ({ ...proposal, message_id: input.message_id })),
    confirm: vi.fn().mockImplementation(async requestId => ({ ...ready, request_id: requestId })),
    status: vi.fn().mockResolvedValue(ready),
    pdf: vi.fn().mockResolvedValue(new Blob(['%PDF-1.7\nsynthetic-only'], { type: 'application/pdf' })),
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(res => { resolve = res; });
  return { promise, resolve };
}
async function begin(api = client()) {
  vi.spyOn(crypto, 'randomUUID').mockReturnValue(id);
  const view = render(<CustomerPortal api={api} accountName="Customer one" onSignOut={() => {}} />);
  await screen.findByRole('heading', { name: catalog.customer_name });
  return { api, ...view };
}
async function send(prompt = 'Please send my existing certificate.') {
  fireEvent.change(screen.getByRole('textbox', { name: 'Your message' }), { target: { value: prompt } });
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
}
async function submit() {
  await send();
  fireEvent.click(await screen.findByRole('button', { name: 'Request this certificate' }));
}
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('CustomerPortal', () => {
  it('automatically follows open, acknowledged and closed cases without releasing or exposing notes', async () => {
    const held = { ...ready, status: 'operations_required' as const, case_status: 'open' as const, updated_at: '2026-09-18T09:00:00Z' };
    const api = client(); vi.mocked(api.confirm).mockResolvedValue(held);
    await begin(api); await submit(); await screen.findByText('Awaiting Operations');
    vi.useFakeTimers();
    vi.mocked(api.status).mockResolvedValueOnce(held)
      .mockResolvedValueOnce({ ...held, case_status: 'acknowledged', updated_at: '2026-09-18T09:01:00Z' })
      .mockResolvedValueOnce({ ...held, case_status: 'closed_without_release', updated_at: '2026-09-18T09:02:00Z', ...{ notes: 'PRIVATE' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh status' })); });
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    expect(screen.getByText('Under review')).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    expect(screen.getByRole('heading', { name: 'Request closed' })).toBeInTheDocument();
    expect(screen.getByText('Closed without release')).toBeInTheDocument();
    expect(screen.getByText('Last updated')).toBeInTheDocument();
    expect(screen.queryByText('PRIVATE')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Download existing PDF' })).not.toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(60000));
    expect(api.status).toHaveBeenCalledTimes(3);
    expect(api.confirm).toHaveBeenCalledOnce(); expect(api.pdf).not.toHaveBeenCalled();
  });

  it('marks polling failure as stale and waits for a manual refresh', async () => {
    const held = { ...ready, status: 'operations_required' as const, case_status: 'open' as const, updated_at: '2026-09-18T09:00:00Z' };
    const api = client(); vi.mocked(api.confirm).mockResolvedValue(held);
    await begin(api); await submit(); await screen.findByText('Awaiting Operations');
    vi.useFakeTimers(); vi.mocked(api.status).mockResolvedValueOnce(held).mockRejectedValue(new Error('PRIVATE'));
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh status' })); });
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    expect(screen.getByRole('alert')).toHaveTextContent('Showing the last known status');
    expect(screen.queryByText('PRIVATE')).not.toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(60000));
    expect(api.status).toHaveBeenCalledTimes(2);
    vi.mocked(api.status).mockResolvedValue({ ...held, case_status: 'closed_without_release' });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh status' })); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Request closed' })).toBeInTheDocument();
  });

  it('aborts an in-flight poll on sign-out and ignores its late result', async () => {
    const held = { ...ready, status: 'operations_required' as const, case_status: 'open' as const, updated_at: '2026-09-18T09:00:00Z' };
    const api = client(); vi.mocked(api.confirm).mockResolvedValue(held);
    await begin(api); await submit(); await screen.findByText('Awaiting Operations');
    const pending = deferred<CustomerRequestStatus>();
    vi.useFakeTimers(); vi.mocked(api.status).mockResolvedValueOnce(held).mockReturnValueOnce(pending.promise);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh status' })); });
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    const signal = vi.mocked(api.status).mock.calls[1][1];
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(signal?.aborted).toBe(true);
    await act(async () => pending.resolve({ ...held, case_status: 'closed_without_release' }));
    expect(screen.queryByRole('heading', { name: 'Request closed' })).not.toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(60000));
    expect(api.status).toHaveBeenCalledTimes(2);
  });
  it('skips hidden tabs and never overlaps automatic status requests', async () => {
    const held = { ...ready, status: 'operations_required' as const, case_status: 'open' as const, updated_at: '2026-09-18T09:00:00Z' };
    const api = client(); vi.mocked(api.confirm).mockResolvedValue(held);
    await begin(api); await submit(); await screen.findByText('Awaiting Operations');
    const pending = deferred<CustomerRequestStatus>();
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    vi.useFakeTimers(); vi.mocked(api.status).mockResolvedValueOnce(held).mockReturnValueOnce(pending.promise).mockResolvedValue(held);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh status' })); });
    await act(async () => vi.advanceTimersByTimeAsync(60000));
    expect(api.status).toHaveBeenCalledOnce();
    hidden.mockReturnValue(false);
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    expect(api.status).toHaveBeenCalledTimes(2);
    await act(async () => vi.advanceTimersByTimeAsync(60000));
    expect(api.status).toHaveBeenCalledTimes(2);
    await act(async () => pending.resolve(held));
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    expect(api.status).toHaveBeenCalledTimes(3);
    expect(api.confirm).toHaveBeenCalledOnce();
  });

  it('aborts a poll and clears its result when the account changes', async () => {
    const held = { ...ready, status: 'operations_required' as const, case_status: 'open' as const, updated_at: '2026-09-18T09:00:00Z' };
    const api = client(); vi.mocked(api.confirm).mockResolvedValue(held);
    const { rerender } = await begin(api); await submit(); await screen.findByText('Awaiting Operations');
    const pending = deferred<CustomerRequestStatus>();
    vi.useFakeTimers(); vi.mocked(api.status).mockResolvedValueOnce(held).mockReturnValueOnce(pending.promise);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh status' })); });
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    const signal = vi.mocked(api.status).mock.calls[1][1];
    vi.mocked(api.catalog).mockResolvedValue({ customer_name: 'Fictional Northwind', equipment: [], presets: [] });
    await act(async () => { rerender(<CustomerPortal api={api} accountName="Customer two" onSignOut={() => {}} />); });
    expect(signal?.aborted).toBe(true);
    await act(async () => pending.resolve({ ...held, case_status: 'closed_without_release' }));
    expect(screen.getByRole('heading', { name: 'Fictional Northwind' })).toBeInTheDocument();
    expect(screen.queryByText('Awaiting Operations')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Request closed' })).not.toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(60000));
    expect(api.status).toHaveBeenCalledTimes(2);
  });

  it('answers service questions with target, timestamp and evidence without creating a certificate request', async () => {
    const api = client();
    vi.mocked(api.message).mockResolvedValue({ ...proposal, intent: 'service_status', kind: 'answer', can_confirm: false, message: 'The service record is current.', as_of: '2026-09-17T09:00:00Z', citations: [{ document_id: 'service-001', document_version: 'v1', page: 1, label: 'Service due', value: '2026-12-10' }] });
    await begin(api); await send('Is service for PT-001 up to date?');
    await screen.findByText('The service record is current.');
    expect(screen.getByText('Understood: service status · DEMO-PT-001')).toBeInTheDocument();
    expect(screen.getByText('2026-09-17T09:00:00Z')).toBeInTheDocument();
    expect(screen.getByText(/service-001 · version v1 · page 1/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Request this certificate' })).not.toBeInTheDocument();
    expect(api.confirm).not.toHaveBeenCalled(); expect(api.request).not.toHaveBeenCalled();
    expect(vi.mocked(api.message).mock.calls[0][0].equipment_id).toBeNull();
  });

  it('links a clarification follow-up to the previous server message and resets on start new', async () => {
    const api = client();
    vi.mocked(api.message).mockResolvedValueOnce({ ...proposal, intent: 'clarify', equipment_id: null, kind: 'clarification', can_confirm: false, message: 'Which equipment do you mean?' });
    await begin(api); await send('Please provide a certificate');
    await screen.findByText('Which equipment do you mean?');
    const secondId = '33333333-3333-4333-8333-333333333333';
    vi.mocked(crypto.randomUUID).mockReturnValueOnce(secondId);
    await send('PT-001'); await screen.findByRole('button', { name: 'Request this certificate' });
    expect(vi.mocked(api.message).mock.calls[1][0]).toEqual({ message_id: secondId, parent_message_id: id, prompt: 'PT-001', equipment_id: null });
    fireEvent.click(screen.getByRole('button', { name: 'Start new conversation' }));
    expect(screen.queryByText('Which equipment do you mean?')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Request this certificate' })).not.toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveValue('');
    await send('Certificate for PT-001'); await screen.findByRole('button', { name: 'Request this certificate' });
    expect(vi.mocked(api.message).mock.calls[2][0].parent_message_id).toBeNull();
  });

  it('retries an uncertain message with the same id and never automatically confirms', async () => {
    const api = client(); vi.mocked(api.message).mockRejectedValueOnce(new Error('private failure'));
    await begin(api); await send(); await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByRole('button', { name: 'Request this certificate' });
    expect(vi.mocked(api.message).mock.calls[0][0]).toEqual(vi.mocked(api.message).mock.calls[1][0]);
    expect(crypto.randomUUID).toHaveBeenCalledOnce(); expect(api.confirm).not.toHaveBeenCalled();
  });

  it('removes an old proposal when composing a new message and reports unsupported service booking', async () => {
    const { api } = await begin(); await send(); await screen.findByRole('button', { name: 'Request this certificate' });
    vi.mocked(crypto.randomUUID).mockReturnValueOnce('33333333-3333-4333-8333-333333333333');
    vi.mocked(api.message).mockImplementationOnce(async input => ({ ...proposal, message_id: input.message_id, intent: 'service_request', kind: 'unsupported', can_confirm: false, message: 'Service booking is not available.' }));
    await send('Book a service'); await screen.findByText('Service booking is not available.');
    expect(screen.getByText('No service booking or approval workflow was created.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Request this certificate' })).not.toBeInTheDocument();
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it('renders response markup as text and rejects unassigned equipment proposals', async () => {
    const api = client(); vi.mocked(api.message).mockResolvedValueOnce({ ...proposal, message: '<img src=x onerror=alert(1)>' });
    await begin(api); await send(); await screen.findByText('<img src=x onerror=alert(1)>');
    expect(document.querySelector('img')).toBeNull();
    vi.mocked(api.message).mockResolvedValueOnce({ ...proposal, equipment_id: 'DEMO-OTHER-999' });
    await send(); await screen.findByRole('alert');
    expect(screen.queryByRole('button', { name: 'Request this certificate' })).not.toBeInTheDocument();
  });

  it('aborts and discards a late answer on sign out even if the parent does not unmount', async () => {
    const waiting = deferred<CustomerMessage>(); const api = client(); vi.mocked(api.message).mockReturnValueOnce(waiting.promise);
    await begin(api); await send();
    const signal = vi.mocked(api.message).mock.calls[0][1]!;
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' })); expect(signal.aborted).toBe(true);
    await act(async () => waiting.resolve(proposal));
    expect(screen.queryByText(catalog.customer_name)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Request this certificate' })).not.toBeInTheDocument();
  });

  it('discards late answers after start new and after replacing the API', async () => {
    const waiting = deferred<CustomerMessage>(); const api = client(); vi.mocked(api.message).mockReturnValueOnce(waiting.promise);
    const { rerender } = await begin(api); await send();
    fireEvent.click(screen.getByRole('button', { name: 'Start new conversation' }));
    await act(async () => waiting.resolve(proposal));
    expect(screen.queryByRole('button', { name: 'Request this certificate' })).not.toBeInTheDocument();
    const second = deferred<CustomerMessage>(); vi.mocked(api.message).mockReturnValueOnce(second.promise);
    await send();
    rerender(<CustomerPortal api={client()} accountName="Customer one" onSignOut={() => {}} />);
    await act(async () => second.resolve(proposal));
    expect(screen.queryByRole('button', { name: 'Request this certificate' })).not.toBeInTheDocument();
  });

  it('shows only assigned equipment without a customer selector, authorization controls or fabricated agent progress', async () => {
    const { api } = await begin();
    expect(screen.getAllByRole('combobox')).toHaveLength(1);
    expect(screen.getByRole('combobox', { name: 'Your equipment (optional)' })).toHaveTextContent('DEMO-SERIAL-001');
    expect(screen.getByRole('combobox')).toHaveValue('');
    expect(screen.getByText(/Synthetic hackathon environment/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /approve|execute|override/i })).not.toBeInTheDocument();
    expect(api.request).not.toHaveBeenCalled();
  });

  it('sends presets as messages and requires explicit confirmation before any certificate request', async () => {
    const { api } = await begin();
    fireEvent.click(screen.getByRole('button', { name: catalog.presets[0].prompt }));
    expect(screen.getByRole('textbox')).toHaveValue(catalog.presets[0].prompt);
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    const confirmation = await screen.findByRole('button', { name: 'Request this certificate' });
    expect(api.confirm).not.toHaveBeenCalled();
    expect(api.request).not.toHaveBeenCalled();
    expect(api.message).toHaveBeenCalledWith({ message_id: id, equipment_id: 'DEMO-PT-001', prompt: catalog.presets[0].prompt, parent_message_id: null }, expect.any(AbortSignal));
    fireEvent.click(confirmation);
    await screen.findByRole('heading', { name: 'Certificate ready' });
    expect(api.confirm).toHaveBeenCalledWith(id, expect.any(AbortSignal));
    expect(screen.getByRole('button', { name: 'Download existing PDF' })).toBeInTheDocument();
    expect(api.pdf).not.toHaveBeenCalled();
  });

  it('retains the same request ID on retry after an uncertain network outcome', async () => {
    const api = client(); vi.mocked(api.confirm).mockRejectedValueOnce(new Error('private backend data'));
    await begin(api); await submit();
    await screen.findByRole('alert');
    expect(screen.queryByText(/private backend data/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Request this certificate' }));
    await screen.findByRole('heading', { name: 'Certificate ready' });
    expect(vi.mocked(api.confirm).mock.calls[0][0]).toEqual(vi.mocked(api.confirm).mock.calls[1][0]);
    expect(crypto.randomUUID).toHaveBeenCalledOnce();
  });

  it('locks submission and inputs while waiting without assuming a successful result', async () => {
    const pending = deferred<CustomerRequestStatus>(); const api = client(); vi.mocked(api.confirm).mockReturnValue(pending.promise);
    await begin(api); await submit();
    expect(screen.getByRole('button', { name: 'Working…' })).toBeDisabled();
    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Download existing PDF' })).not.toBeInTheDocument();
    fireEvent.submit(screen.getByRole('textbox').closest('form')!);
    expect(api.confirm).toHaveBeenCalledOnce();
    await act(async () => pending.resolve(ready));
  });

  it('shows a held Operations case without implying approval, live notification, or a customer PDF release', async () => {
    const api = client(); vi.mocked(api.confirm).mockResolvedValue({ ...ready, status: 'operations_required', message: 'private reason text must not be rendered' });
    await begin(api); await submit();
    await screen.findByRole('heading', { name: 'Operations review needed' });
    expect(screen.getByText(/saved for Operations review/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Download existing PDF' })).not.toBeInTheDocument();
    expect(screen.queryByText(/private reason text/)).not.toBeInTheDocument();
    expect(api.pdf).not.toHaveBeenCalled();
  });

  it('rejects a response for another request', async () => {
    const api = client(); vi.mocked(api.confirm).mockResolvedValue({ ...ready, request_id: '33333333-3333-4333-8333-333333333333' });
    await begin(api); await submit();
    await screen.findByRole('alert');
    expect(screen.queryByRole('heading', { name: 'Certificate ready' })).not.toBeInTheDocument();
  });

  it('clears data and ignores late responses when the signed-in account changes', async () => {
    const pending = deferred<CustomerRequestStatus>(); const api = client(); vi.mocked(api.confirm).mockReturnValue(pending.promise);
    const { rerender } = await begin(api); await submit();
    const nextCatalog = deferred<CustomerCatalog>(); vi.mocked(api.catalog).mockReturnValueOnce(nextCatalog.promise);
    rerender(<CustomerPortal api={api} accountName="Customer two" onSignOut={() => {}} />);
    expect(screen.queryByRole('heading', { name: catalog.customer_name })).not.toBeInTheDocument();
    await act(async () => pending.resolve(ready));
    expect(screen.queryByRole('heading', { name: 'Certificate ready' })).not.toBeInTheDocument();
    await act(async () => nextCatalog.resolve({ customer_name: 'Fictional Northwind', equipment: [], presets: [] }));
    expect(screen.getByRole('heading', { name: 'Fictional Northwind' })).toBeInTheDocument();
  });

  it('refreshes actual persisted status without repeating submission', async () => {
    const { api } = await begin(); await submit();
    await screen.findByRole('heading', { name: 'Certificate ready' });
    vi.mocked(api.status).mockResolvedValue({ ...ready, status: 'operations_required' });
    fireEvent.click(screen.getByRole('button', { name: 'Refresh status' }));
    await screen.findByRole('heading', { name: 'Operations review needed' });
    expect(api.status).toHaveBeenCalledWith(id, expect.any(AbortSignal));
    expect(api.confirm).toHaveBeenCalledOnce();
  });

  it('refreshes a newly held request after download is refused and never creates a download URL', async () => {
    const { api } = await begin(); await submit();
    await screen.findByRole('heading', { name: 'Certificate ready' });
    vi.mocked(api.pdf).mockRejectedValue(new Error('private ownership detail'));
    vi.mocked(api.status).mockResolvedValue({ ...ready, status: 'operations_required' });
    const createObjectURL = vi.fn(); Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    fireEvent.click(screen.getByRole('button', { name: 'Download existing PDF' }));
    await screen.findByRole('heading', { name: 'Operations review needed' });
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByText(/private ownership/)).not.toBeInTheDocument();
  });

  it('clears stale download availability when a status refresh fails', async () => {
    const { api } = await begin(); await submit();
    await screen.findByRole('heading', { name: 'Certificate ready' });
    vi.mocked(api.status).mockRejectedValue(new Error('Access denied'));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh status' }));
    await screen.findByRole('alert');
    expect(screen.queryByRole('button', { name: 'Download existing PDF' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Certificate ready' })).not.toBeInTheDocument();
  });

  it('downloads only an authenticated Blob, removes its link and revokes the object URL', async () => {
    const { api } = await begin(); await submit();
    await screen.findByRole('heading', { name: 'Certificate ready' });
    const createObjectURL = vi.fn().mockReturnValue('blob:synthetic-only');
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole('button', { name: 'Download existing PDF' }));
    await act(async () => { await Promise.resolve(); });
    expect(api.pdf).toHaveBeenCalledWith(id, expect.any(AbortSignal));
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledOnce();
    expect(document.querySelector('a[download]')).toBeNull();
    expect(screen.getByText(/handed to your browser/)).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTime(1000));
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:synthetic-only');
  });

  it('renders customer-provided strings as plain text and clears workspace errors on retry', async () => {
    const api = client(); vi.mocked(api.catalog).mockRejectedValueOnce(new Error('private directory record'));
    const signOut = vi.fn();
    render(<CustomerPortal api={api} accountName="Customer" onSignOut={signOut} />);
    await screen.findByRole('alert');
    expect(screen.queryByText(/private directory/)).not.toBeInTheDocument();
    vi.mocked(api.catalog).mockResolvedValue({ ...catalog, customer_name: '<script>never execute</script>' });
    fireEvent.click(screen.getByRole('button', { name: 'Retry workspace' }));
    await screen.findByRole('heading', { name: '<script>never execute</script>' });
    expect(document.querySelector('script')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    await waitFor(() => expect(signOut).toHaveBeenCalledOnce());
  });
});

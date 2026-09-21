import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CertificateCases } from './CertificateCases';
import type { OperationsApi, OperationsCaseView } from './operations-api';

const id = '22222222-2222-4222-8222-222222222222';
const otherId = '33333333-3333-4333-8333-333333333333';
function record(requestId = id): OperationsCaseView {
  return { requestId, caseId: requestId, customerId: 'DEMO-FAB', equipmentId: requestId === id ? 'DEMO-PT-003' : 'DEMO-PT-002', assignedUserId: id, decisionHash: 'a'.repeat(64), evaluatedAt: requestId === id ? '2026-09-14T00:00:00Z' : '2026-09-11T00:00:00Z', reasons: ['certificate_missing'], checks: [], fields: [], specialists: [], notification: { state: 'pending', receiptId: null } };
}
const client = (records = [record()]): OperationsApi => ({ list: vi.fn().mockResolvedValue(records) });

describe('CertificateCases', () => {
  it('shows actual held cases newest first with exact links and no release controls', async () => {
    const api = client([record(otherId), record()]);
    render(<CertificateCases api={api} accountName="Operations" />);
    await screen.findByRole('link', { name: 'Inspect DEMO-PT-003' });
    const items = screen.getAllByRole('listitem');
    expect(within(items[0]).getByRole('link')).toHaveAttribute('href', `/?operations=${id}`);
    expect(screen.getByText(/not successful certificate downloads/)).toBeInTheDocument();
    expect(screen.getByText(/2 held cases returned/)).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', { name: /approve|release|resolve|send/i })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Find a certificate case' }), { target: { value: '002' } });
    expect(screen.queryByRole('link', { name: 'Inspect DEMO-PT-003' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Inspect DEMO-PT-002' })).toBeInTheDocument();
  });
  it('distinguishes an empty list from a denied or unavailable list', async () => {
    const api = client([]);
    render(<CertificateCases api={api} accountName="Operations" />);
    await screen.findByText('No held certificate cases were returned for this account.');
    vi.mocked(api.list).mockRejectedValue(new Error('private token'));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh certificate cases' }));
    await screen.findByRole('alert');
    expect(screen.queryByText('No held certificate cases were returned for this account.')).not.toBeInTheDocument();
    expect(screen.queryByText(/private token/)).not.toBeInTheDocument();
  });
  it('clears old cases immediately on refresh failure', async () => {
    const api = client(); render(<CertificateCases api={api} accountName="Operations" />);
    await screen.findByRole('link', { name: 'Inspect DEMO-PT-003' });
    vi.mocked(api.list).mockRejectedValue(new Error('denied'));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh certificate cases' }));
    expect(screen.queryByRole('link', { name: 'Inspect DEMO-PT-003' })).not.toBeInTheDocument();
    await screen.findByRole('alert');
  });
  it('discards late responses when account or API changes', async () => {
    let resolve!: (items: OperationsCaseView[]) => void;
    const api: OperationsApi = { list: vi.fn().mockReturnValue(new Promise(done => { resolve = done; })) };
    const view = render(<CertificateCases api={api} accountName="first" />);
    view.rerender(<CertificateCases api={client([])} accountName="second" />);
    await act(async () => resolve([record()]));
    await screen.findByText('No held certificate cases were returned for this account.');
    expect(screen.queryByText('DEMO-PT-003')).not.toBeInTheDocument();
  });
  it('refreshes with the dashboard epoch and renders evidence as text', async () => {
    const item = record(); item.reasons = ['<script>untrusted</script>'];
    const api = client([item]); const view = render(<CertificateCases api={api} accountName="Operations" refreshEpoch={0} />);
    await screen.findByText('<script>untrusted</script>');
    expect(document.querySelector('script')).toBeNull();
    vi.mocked(api.list).mockResolvedValue([]);
    view.rerender(<CertificateCases api={api} accountName="Operations" refreshEpoch={1} />);
    expect(screen.queryByText('<script>untrusted</script>')).not.toBeInTheDocument();
    await screen.findByText('No held certificate cases were returned for this account.');
    expect(api.list).toHaveBeenCalledTimes(2);
  });
});

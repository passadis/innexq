import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { OperationsInbox } from './OperationsInbox';
import type { OperationsApi, OperationsCaseView } from './operations-api';

const id = '22222222-2222-4222-8222-222222222222';
const otherId = '33333333-3333-4333-8333-333333333333';
function record(requestId = id): OperationsCaseView {
  return { requestId, caseId: id, customerId: 'DEMO-FAB', equipmentId: requestId === id ? 'DEMO-PT-002' : 'OTHER-EQUIPMENT', assignedUserId: id, decisionHash: 'a'.repeat(64), evaluatedAt: '2026-09-11T00:00:00Z', reasons: ['service_not_current'], checks: [{ name: 'ownership', verdict: 'pass', reason: 'passed' }, { name: 'certificate_validity', verdict: 'pass', reason: 'passed' }, { name: 'service_status', verdict: 'fail', reason: 'service_not_current' }], fields: [{ documentId: 'DEMO-SERVICE', documentVersion: 'v1', sha256: 'b'.repeat(64), label: 'Valid until', value: '2026-09-10', page: 2 }], specialists: [{ specialist: 'equipment_service', responseId: 'response-equipment', summary: 'The machine service period has ended.' }], notification: { state: 'pending', receiptId: null } };
}
function client(records = [record()]): OperationsApi { return { list: vi.fn().mockResolvedValue(records) }; }
function show(api = client()) { window.history.replaceState({}, '', `/?operations=${id}`); return render(<OperationsInbox api={api} accountName="Operations" onSignOut={() => {}} />); }
afterEach(() => window.history.replaceState({}, '', '/'));

describe('OperationsInbox', () => {
  it('shows actual read-only tool receipts grouped by specialist with no new actions or links', async () => {
    const value = record();
    value.toolActivity = [
      { attemptId: id, receiptId: id, specialist: 'document_analyst', toolName: 'analyze_document', documentId: 'DEMO-CERTIFICATE-002', sourceVersion: '<img src=x onerror=alert(1)>', completedAt: '2026-09-11T00:00:00Z' },
      { attemptId: id, receiptId: otherId, specialist: 'equipment_service', toolName: 'retrieve_policy', documentId: null, sourceVersion: 'https://private.example/not-a-link', completedAt: '2026-09-11T00:00:01Z' },
    ];
    show(client([value]));
    const section = await screen.findByRole('region', { name: 'Verified tool activity' });
    expect(screen.getByRole('heading', { name: 'Document Analyst' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Equipment & Service' })).toBeInTheDocument();
    expect(screen.getByText('Analyze PDF with Document Intelligence')).toBeInTheDocument();
    expect(screen.getByText('Retrieve applicable policy')).toBeInTheDocument();
    expect(screen.getByText(/read-only evidence, not authorization/)).toBeInTheDocument();
    expect(section.querySelectorAll('time')).toHaveLength(2);
    expect(section.querySelectorAll('details')).toHaveLength(2);
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(screen.getByText('https://private.example/not-a-link')).toBeInTheDocument();
    expect(section.querySelector('img, script, a, button')).toBeNull();
  });
  it('does not invent a tool timeline for legacy or empty activity', async () => {
    const value = record(), api = client([value]);
    show(api); await screen.findByRole('heading', { name: 'DEMO-PT-002' });
    expect(screen.queryByRole('heading', { name: 'Verified tool activity' })).not.toBeInTheDocument();
    vi.mocked(api.list).mockResolvedValue([{ ...value, toolActivity: [] }]);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh cases' }));
    await screen.findByRole('heading', { name: 'DEMO-PT-002' });
    expect(screen.queryByRole('heading', { name: 'Verified tool activity' })).not.toBeInTheDocument();
  });
  it('shows the original customer messages as plain text with the interpreted intent and limited next actions', async () => {
    const value = record();
    value.requestContext = { customerMessages: ['Could I get the certificate?', '<img src=x onerror=alert(1)> PT-002'], interpretedIntent: 'certificate_request', equipmentId: value.equipmentId, interpreterResponseId: 'response-intent' };
    show(client([value]));
    await screen.findByText('Could I get the certificate?');
    expect(screen.getByText('<img src=x onerror=alert(1)> PT-002')).toBeInTheDocument();
    expect(document.querySelector('img, script')).toBeNull();
    expect(screen.getByText('Certificate request for DEMO-PT-002.')).toBeInTheDocument();
    expect(screen.getByText('The recorded service status was not current.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Next owner: Operations' })).toBeInTheDocument();
    expect(screen.getByText(/Acknowledgement does not unlock manager approval/)).toBeInTheDocument();
  });
  it('explicitly identifies legacy missing customer context without inventing a message', async () => {
    show();
    await screen.findByText('Original customer message was not recorded.');
    expect(screen.getByText(/not a reconstruction of what the customer asked/)).toBeInTheDocument();
  });
  it('opens only the linked case with honest notification status, citations and specialist findings', async () => {
    const api = client([record(otherId), record()]); show(api);
    await screen.findByRole('heading', { name: 'DEMO-PT-002' });
    expect(screen.queryByText('OTHER-EQUIPMENT')).not.toBeInTheDocument();
    expect(screen.getByText('Pending dispatch')).toBeInTheDocument();
    expect(screen.getByText('Page 2')).toBeInTheDocument();
    expect(screen.getByText('The machine service period has ended.')).toBeInTheDocument();
    expect(screen.getByText('Response: response-equipment')).toBeInTheDocument();
    expect(screen.getAllByText(/service not current/).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /approve|release|retry delivery|execute/i })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Return to Control Room' })).toHaveAttribute('href', '/');
  });
  it('does not substitute another case when the linked request is missing', async () => {
    show(client([record(otherId)]));
    await screen.findByRole('alert');
    expect(screen.queryByText('OTHER-EQUIPMENT')).not.toBeInTheDocument();
  });
  it('does not query cases for an invalid deep link', async () => {
    window.history.replaceState({}, '', '/?operations=../runs');
    const api = client(); render(<OperationsInbox api={api} accountName="Operations" onSignOut={() => {}} />);
    await screen.findByRole('alert');
    expect(api.list).not.toHaveBeenCalled();
  });
  it.each(['claimed', 'delivered', 'ambiguous'] as const)('reports %s notification state without asserting human reading', async state => {
    const value = record(); value.notification = { state, receiptId: state === 'delivered' ? 'teams-receipt' : null };
    show(client([value])); await screen.findByRole('heading', { name: 'DEMO-PT-002' });
    expect(screen.getByText(state === 'claimed' ? 'Sending · unconfirmed' : state === 'delivered' ? 'Accepted by Teams' : 'Delivery uncertain')).toBeInTheDocument();
    if (state === 'delivered') expect(screen.getByText(/not proof that an operator read/)).toBeInTheDocument();
    if (state === 'ambiguous') expect(screen.getByText(/Inspect Teams and the audit record before any retry/)).toBeInTheDocument();
  });
  it('shows missing investigation explicitly and renders untrusted strings as text only', async () => {
    const value = record(); value.specialists[0].summary = '<img src=x onerror=alert(1)>'; value.fields[0].value = '<script>source text</script>';
    const api = client([value]); show(api); await screen.findByRole('heading', { name: 'DEMO-PT-002' });
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(screen.getByText('<script>source text</script>')).toBeInTheDocument();
    expect(document.querySelector('img, script')).toBeNull();
    vi.mocked(api.list).mockResolvedValue([{ ...value, fields: [], specialists: [] }]);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh cases' }));
    await screen.findByText(/No specialist findings were recorded/);
    expect(screen.getByText(/No verified PDF field citations/)).toBeInTheDocument();
  });
  it('clears prior records on refresh denial without showing the server exception', async () => {
    const api = client(); show(api); await screen.findByRole('heading', { name: 'DEMO-PT-002' });
    vi.mocked(api.list).mockRejectedValue(new Error('private token and source details'));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh cases' }));
    await screen.findByRole('alert');
    expect(screen.queryByText('DEMO-PT-002')).not.toBeInTheDocument();
    expect(screen.queryByText(/private token/)).not.toBeInTheDocument();
  });
  it('clears the snapshot immediately on account changes and ignores old responses', async () => {
    let resolve!: (value: OperationsCaseView[]) => void;
    const api = client(); vi.mocked(api.list).mockReturnValue(new Promise(done => { resolve = done; }));
    const { rerender } = show(api);
    const next: OperationsApi = { list: vi.fn().mockResolvedValue([]) };
    rerender(<OperationsInbox api={next} accountName="Other account" onSignOut={() => {}} />);
    await act(async () => resolve([record()]));
    await screen.findByRole('alert');
    expect(screen.queryByText('DEMO-PT-002')).not.toBeInTheDocument();
  });
});

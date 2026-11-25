import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CoverageRenewals } from './CoverageRenewals';
import type { CoverageApi, CoverageRenewalView } from './coverage-api';

const id = '22222222-2222-4222-8222-222222222222';
const hash = 'a'.repeat(64);
function renewal(state: CoverageRenewalView['state'] = 'AWAITING_OPERATIONS_APPROVAL'): CoverageRenewalView {
  return {
    requestId: id, state, publicProgress: state === 'AWAITING_OPERATIONS_APPROVAL' ? 'Awaiting Operations' : 'Awaiting Manager',
    customerId: 'DEMO-FAB', equipmentId: 'DEMO-COV-001', updatedAt: '2026-09-22T12:00:00Z', holdReasons: [],
    package: { version: 1, hash, coverageMonths: 12, serialNumber: 'SER-1',
      quote: { currency: 'EUR', baseAmount: '8500.00', vatRatePercent: '24.00', vatAmount: '2040.00', totalAmount: '10540.00' },
      invoiceNotice: 'SYNTHETIC DEMO — NOT A FISCAL OR TAX DOCUMENT',
      previousDocument: { documentId: 'DEMO-COV-001-COVERAGE-PDF', documentVersion: 'v1', sha256: hash } },
    operationsDecision: null, managerDecision: null,
  };
}
const client = (records = [renewal()]): CoverageApi => ({
  list: vi.fn().mockResolvedValue(records),
  decide: vi.fn().mockImplementation(async () => ({ ...renewal('AWAITING_MANAGER_APPROVAL'), operationsDecision: { decision: 'approve', actorObjectId: id, submittedAt: '2026-09-22T12:05:00Z', rejectReason: null, decisionId: id } })),
});

describe('CoverageRenewals', () => {
  it('shows the exact quote, hash and synthetic notice with stage-scoped actions', async () => {
    const api = client();
    render(<CoverageRenewals api={api} accountName="Operations" />);
    await screen.findByText('DEMO-COV-001');
    expect(screen.getByText(/Total EUR 10540\.00/)).toBeInTheDocument();
    expect(screen.getByText(/SYNTHETIC DEMO/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(hash))).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge and Approve' }));
    expect(api.decide).toHaveBeenCalledWith(id, 'operations', { decision: 'approve', packageVersion: 1, packageHash: hash });
    // The updated record replaces the entry and offers the manager stage next.
    await screen.findByText(/Operations: approved/);
    expect(screen.getByRole('button', { name: 'Approve package v1' })).toBeInTheDocument();
  });
  it('requires a rejection reason and binds it to the displayed package', async () => {
    const api = client([renewal('AWAITING_MANAGER_APPROVAL')]);
    render(<CoverageRenewals api={api} accountName="Manager" />);
    await screen.findByRole('button', { name: 'Approve package v1' });
    const reject = screen.getByRole('button', { name: 'Reject' });
    expect(reject).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Rejection reason/), { target: { value: 'pricing query' } });
    fireEvent.click(reject);
    expect(api.decide).toHaveBeenCalledWith(id, 'manager', { decision: 'reject', packageVersion: 1, packageHash: hash, rejectReason: 'pricing query' });
  });
  it('offers no decision controls outside the two awaiting states and surfaces refusals generically', async () => {
    const held: CoverageRenewalView = { ...renewal(), state: 'EVIDENCE_HOLD', publicProgress: 'Held or rejected', package: null, holdReasons: ['missing_evidence'] };
    const api = client([held]);
    render(<CoverageRenewals api={api} accountName="Operations" />);
    await screen.findByText(/missing evidence/);
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument();
    const failing = client();
    vi.mocked(failing.decide).mockRejectedValue(new Error('private token details'));
    const view = render(<CoverageRenewals api={failing} accountName="Operations" />);
    fireEvent.click(await within(view.container).findByRole('button', { name: 'Acknowledge and Approve' }));
    await within(view.container).findByRole('alert');
    expect(view.container.textContent).not.toContain('private token');
  });
  it('distinguishes an empty queue from a denied list', async () => {
    render(<CoverageRenewals api={client([])} accountName="Operations" />);
    await screen.findByText('No coverage renewals were returned for this account.');
    const denied: CoverageApi = { list: vi.fn().mockRejectedValue(new Error('denied')), decide: vi.fn() };
    const view = render(<CoverageRenewals api={denied} accountName="Operations" />);
    await within(view.container).findByRole('alert');
  });
});

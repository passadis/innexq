import { act, fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { CaseReviewPanel } from './CaseReviewPanel';
import type { CaseReview, CaseReviewApi } from './case-review-api';
import type { OperationsCaseView } from './operations-api';

const id = '22222222-2222-4222-8222-222222222222';
const current: OperationsCaseView = { requestId: id, caseId: id, assignedUserId: id, customerId: 'DEMO-FAB', equipmentId: 'DEMO-PT-002', decisionHash: 'a'.repeat(64), evaluatedAt: '2026-09-15T00:00:00Z', reasons: ['service_not_current'], checks: [], fields: [], specialists: [], notification: { state: 'pending', receiptId: null } };
const initial: CaseReview = { schema_version: '1.0', request_id: id, tenant_id: id, case_id: id, assigned_user_id: id, decision_hash: current.decisionHash, state: 'open', revision: 0, events: [] };
function client(canManage = true): CaseReviewApi {
  let review = initial;
  return {
    read: vi.fn(async () => ({ review, canManage })),
    act: vi.fn(async (_, command) => {
      review = { ...review, revision: review.revision + 1, state: command.action === 'close_without_release' ? 'closed_without_release' : command.action === 'acknowledge' ? 'acknowledged' : review.state,
        events: [...review.events, { sequence: review.revision + 1, actor_user_id: id, occurred_at: '2026-09-15T01:00:00Z', command }] };
      return review;
    }),
  };
}
it('shows Operations actions, mandatory note, immutable history and terminal closure', async () => {
  const api = client(); render(<CaseReviewPanel api={api} current={current} />);
  const acknowledge = await screen.findByRole('button', { name: 'Acknowledge' });
  expect(screen.getByRole('button', { name: 'Close without release' })).toBeDisabled();
  fireEvent.click(acknowledge);
  await screen.findByText('Acknowledged');
  expect(screen.getByRole('button', { name: 'Acknowledge' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Internal note or closure reason'), { target: { value: '<script>internal source note</script>' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add internal note' }));
  await screen.findByText('<script>internal source note</script>'); expect(document.querySelector('script')).toBeNull();
  fireEvent.change(screen.getByLabelText('Internal note or closure reason'), { target: { value: 'Service remains expired.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Close without release' }));
  await screen.findByText('Closed without release');
  expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument();
  expect(screen.getByText(/original customer request remains held/)).toBeInTheDocument();
  expect(api.act).toHaveBeenCalledTimes(3);
});
it('Manager can read the audit but never sees action controls', async () => {
  const api = client(false); render(<CaseReviewPanel api={api} current={current} />);
  await screen.findByText(/Manager · Read-only/);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /acknowledge|note|close/i })).not.toBeInTheDocument();
  expect(api.act).not.toHaveBeenCalled();
});
it('on ambiguous save hides controls, requires refresh, and retries only the identical command', async () => {
  const api = client(); vi.mocked(api.act).mockRejectedValueOnce(new Error('private data'));
  render(<CaseReviewPanel api={api} current={current} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Acknowledge' }));
  await screen.findByRole('alert'); expect(screen.queryByText('private data')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh review' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Retry the same action' }));
  await screen.findByText('Acknowledged');
  expect(vi.mocked(api.act).mock.calls[1]).toEqual(vi.mocked(api.act).mock.calls[0]);
});
it('denied refresh clears actions and late results cannot restore old account data', async () => {
  const api = client(); const { rerender } = render(<CaseReviewPanel api={api} current={current} />);
  await screen.findByRole('button', { name: 'Acknowledge' });
  let resolve!: (result: { review: CaseReview; canManage: boolean }) => void;
  vi.mocked(api.read).mockReturnValue(new Promise(done => { resolve = done; }));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh review' }));
  const denied = client(); vi.mocked(denied.read).mockRejectedValue(new Error('access denied'));
  rerender(<CaseReviewPanel api={denied} current={current} />);
  await screen.findByRole('alert');
  await act(async () => resolve({ review: initial, canManage: true }));
  expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument();
});

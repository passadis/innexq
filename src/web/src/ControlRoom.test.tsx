import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlRoom, type ControlRoomProps } from './ControlRoom';
import type { RunEvent, RunRecord } from './contracts';

const runA = '11111111-1111-4111-8111-111111111111';
const runB = '22222222-2222-4222-8222-222222222222';
const hash = 'a'.repeat(64);
const at = '2026-09-08T18:00:00Z';
afterEach(() => window.history.replaceState({}, '', '/'));

it('connects certificate case discovery to the overview without affecting renewal inspection', async () => {
  const operationsApi = { list: vi.fn().mockResolvedValue([]) };
  render(<ControlRoom api={api()} operationsApi={operationsApi} accountName="Operations" onSignOut={() => {}} />);
  await screen.findByText('No held certificate cases were returned for this account.');
  await screen.findByRole('heading', { name: 'Decision summary' });
  expect(operationsApi.list).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh Runs' }));
  await waitFor(() => expect(operationsApi.list).toHaveBeenCalledTimes(2));
});

it('does not show unrelated certificate cases on an exact renewal deep link', async () => {
  window.history.replaceState({}, '', `/?run=${runA}&version=1&hash=${hash}`);
  const operationsApi = { list: vi.fn().mockResolvedValue([]) };
  render(<ControlRoom api={api()} operationsApi={operationsApi} accountName="Operations" onSignOut={() => {}} />);
  await screen.findByRole('heading', { name: 'Decision brief · version 1' });
  expect(operationsApi.list).not.toHaveBeenCalled();
});

function record(id = runA, customer = 'Fictional Fabrikam'): RunRecord {
  return {
    run: { schema_version: '1.0', run_id: id, contract_id: `contract-${id.slice(0, 8)}`, state: 'EXECUTED', owner_user_id: 'human-actor', current_brief_version: 1, current_brief_hash: hash, created_at: at, updated_at: at, correlation_id: id },
    workflow_pack: 'contract-renewal', revision: 2, facts: { customer_name: customer, annual_value: '100000.00' }, proposal: null,
    evidence: [{ schema_version: '1.0', evidence_id: id, source_kind: 'foundry_iq', source_name: 'Synthetic contract', source_locator: 'https://example.test/contract', excerpt: '<script>never execute this</script>\nExact evidence line.', retrieved_at: at, actor_context: { actor_user_id: 'retrieval-identity', tenant_id: 'tenant', authorization_mode: 'workload_identity' }, supports_claim_ids: [id], classification: 'internal' }],
    envelope: {
      brief_hash: hash,
      brief: { schema_version: '1.0', run_id: id, brief_version: 1, recommendation: { option_id: 'renewal', term_months: 12, service_level: 'Gold', summary: 'A source-grounded proposal.' }, alternatives: [], material_claims: [{ claim_id: id, text: 'Claim with evidence', evidence_ids: [id] }], calculations: [{ calculation_id: id, tool_name: 'pricing-authority', tool_version: '1.0', inputs: { annual_value: '100000.00', discount_percent: '8' }, outputs: { discounted_annual_value: '92000.00' } }], policy_checks: [{ check_id: id, rule_id: 'discount-authority', rule_version: '1.0', verdict: 'pass', evidence_ids: [id], required_scenario_role: 'account_manager', explanation: 'Verified human still required.' }], evidence_gaps: [], action_manifest_id: id, presentation: { plain_language_summary: 'A source-grounded proposal.', detailed_summary: 'Exact detailed summary', customer_language_drafts: { 'en-GB': 'Exact customer draft' } } },
      action_manifest: { schema_version: '1.0', manifest_id: id, run_id: id, brief_version: 1, actions: [{ action_id: id, action_type: 'graph.send_mail', parameters: { sender: 'sender@example.test', recipient: 'recipient@example.test', subject: 'Synthetic test', content: 'Exact mail content\nSecond line' }, artifact_hash: hash, idempotency_key: `${id}:mail:v1` }] },
    },
    approval: { schema_version: '1.0', decision_id: id, run_id: id, brief_version: 1, brief_hash: hash, actor_user_id: 'human-actor', decision: 'approve', authority_result: { verdict: 'authorized', actor_scenario_role: 'account_manager', required_scenario_role: 'account_manager', rule_id: 'discount-authority', rule_version: '1.0' }, submitted_at: at, comment: null },
    action_status: { [`${id}:mail:v1`]: 'completed' }, receipts: { [`${id}:mail:v1`]: 'accepted:synthetic-receipt' }, approval_requested_at: at,
  };
}

function event(id: string, sequence: number): RunEvent {
  return { schema_version: '1.0', run_id: id, event_id: `${id}-${sequence}`, correlation_id: id, sequence, event_type: sequence === 1 ? 'run.detected' : 'execution.completed', state: sequence === 1 ? 'DETECTED' : 'EXECUTED', occurred_at: at, actor_user_id: 'human-actor', details: { reason: 'audit value' } };
}

function api(records = [record()]): ControlRoomProps['api'] {
  return { listRuns: vi.fn().mockResolvedValue(records), getRun: vi.fn().mockImplementation((id: string) => Promise.resolve(records.find(item => item.run.run_id === id))), getEvents: vi.fn().mockImplementation((id: string) => Promise.resolve([event(id, 2), event(id, 1)])) };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe('ControlRoom', () => {
  it('opens the exact linked Run on its decision tab rather than the first Run', async () => {
    window.history.replaceState({}, '', `/?run=${runB}&version=1&hash=${hash}`);
    const client = api([record(), record(runB, 'Linked customer')]);
    render(<ControlRoom api={client} accountName="reader" onSignOut={() => {}} />);
    await screen.findByRole('heading', { name: 'Decision brief · version 1' });
    expect(client.getRun).toHaveBeenCalledWith(runB, expect.any(AbortSignal));
    expect(screen.getByRole('tab', { name: 'Decision brief' })).toHaveAttribute('aria-selected', 'true');
  });

  it('does not substitute a different envelope for a stale decision link', async () => {
    window.history.replaceState({}, '', `/?run=${runA}&version=1&hash=${'b'.repeat(64)}`);
    render(<ControlRoom api={api()} accountName="reader" onSignOut={() => {}} />);
    await screen.findByText('This decision link is stale');
    expect(screen.queryByRole('heading', { name: 'Decision summary' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Decision brief' })).not.toBeInTheDocument();
  });

  it('does not fall back when the linked Run is unavailable', async () => {
    window.history.replaceState({}, '', `/?run=${runB}&version=1&hash=${hash}`);
    const client = api();
    render(<ControlRoom api={client} accountName="reader" onSignOut={() => {}} />);
    await screen.findByText('Runs could not be loaded');
    expect(client.getRun).not.toHaveBeenCalled();
  });

  it('renders HTML only in a sandbox without script, network or navigation grants', async () => {
    const current = record();
    current.envelope!.action_manifest.actions[0].parameters.content_type = 'HTML';
    current.envelope!.action_manifest.actions[0].parameters.content = '<h1>Mail preview</h1><script>evil()</script>';
    render(<ControlRoom api={api([current])} accountName="reader" onSignOut={() => {}} />);
    await screen.findByRole('heading', { name: 'Decision summary' });
    fireEvent.click(screen.getByRole('tab', { name: 'Decision brief' }));
    const frame = screen.getByTitle('Approved email layout preview');
    expect(frame).toHaveAttribute('sandbox', '');
    expect(frame).toHaveAttribute('tabindex', '-1');
    expect(frame).toHaveAttribute('inert');
    expect(frame.getAttribute('srcdoc')).toContain("default-src 'none'");
    expect(frame.getAttribute('srcdoc')).toContain("script-src 'none'");
    expect(document.querySelector('script')).not.toBeInTheDocument();
  });

  it('shows real stored state, exact hashes and acceptance rather than delivery with no write controls', async () => {
    const client = api(); const signOut = vi.fn();
    render(<ControlRoom api={client} accountName="reader@example.test" onSignOut={signOut} />);
    expect(await screen.findByRole('heading', { name: 'Decision summary' })).toBeInTheDocument();
    expect(screen.getAllByText(hash).length).toBeGreaterThan(0);
    expect(screen.getByText('accepted:synthetic-receipt')).toBeInTheDocument();
    expect(screen.getByText(/not inbox delivery/)).toBeInTheDocument();
    expect(screen.getByText('Synthetic demo')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^approve$|^execute$|^reset$|^send$/i })).not.toBeInTheDocument();
    expect(client.getRun).toHaveBeenCalledWith(runA, expect.any(AbortSignal));
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' })); expect(signOut).toHaveBeenCalledOnce();
  });

  it('renders source excerpts as text, uses safe source links, and shows exact action content', async () => {
    render(<ControlRoom api={api()} accountName="reader" onSignOut={() => {}} />);
    await screen.findByRole('heading', { name: 'Decision summary' });
    fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
    expect(screen.getByText(/<script>never execute this<\/script>/)).toBeInTheDocument();
    expect(document.querySelector('script')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /https:\/\/example.test\/contract/ })).toHaveAttribute('rel', 'noopener noreferrer');
    fireEvent.click(screen.getByRole('tab', { name: 'Decision brief' }));
    expect(screen.getByText('Exact mail content Second line')).toBeInTheDocument();
    expect(screen.getAllByText(/"discounted_annual_value": "92000.00"/).length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: 'Exact proposed actions' })).toBeInTheDocument();
  });

  it('does not turn an unsafe evidence locator into a clickable link', async () => {
    const unsafe = record(); unsafe.evidence![0].source_locator = 'javascript:alert(1)';
    render(<ControlRoom api={api([unsafe])} accountName="reader" onSignOut={() => {}} />);
    await screen.findByRole('heading', { name: 'Decision summary' });
    fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
    expect(screen.getByText('javascript:alert(1)')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'javascript:alert(1)' })).not.toBeInTheDocument();
  });

  it('labels synthetic .invalid provenance identifiers without dead document links', async () => {
    const synthetic = record(); synthetic.evidence![0].source_locator = 'https://schemas.innexq.invalid/corpus/contract';
    render(<ControlRoom api={api([synthetic])} accountName="reader" onSignOut={() => {}} />);
    await screen.findByRole('heading', { name: 'Decision summary' });
    fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
    expect(screen.getByText(/Synthetic provenance reference/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /schemas.innexq.invalid/ })).not.toBeInTheDocument();
  });

  it('orders the timeline by controller sequence and exposes exact event details', async () => {
    render(<ControlRoom api={api()} accountName="reader" onSignOut={() => {}} />);
    await screen.findByRole('heading', { name: 'Decision summary' });
    fireEvent.click(screen.getByRole('tab', { name: 'Timeline' }));
    const panel = screen.getByRole('tabpanel');
    const rows = within(panel).getAllByRole('listitem');
    expect(within(rows[0]).getByRole('heading', { name: 'run · detected' })).toBeInTheDocument();
    expect(within(rows[1]).getByRole('heading', { name: 'execution · completed' })).toBeInTheDocument();
  });

  it('filters Runs without creating or mutating them', async () => {
    const client = api([record(), record(runB, 'Synthetic Contoso')]);
    render(<ControlRoom api={client} accountName="reader" onSignOut={() => {}} />);
    await screen.findByRole('heading', { name: 'Decision summary' });
    fireEvent.change(screen.getByRole('textbox', { name: 'Find a Run' }), { target: { value: 'Contoso' } });
    expect(screen.getByRole('button', { name: /Synthetic Contoso/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Fictional Fabrikam/ })).not.toBeInTheDocument();
    expect(client.listRuns).toHaveBeenCalledOnce();
  });

  it('discards late responses after switching Runs', async () => {
    const late = deferred<RunRecord>(); const client = api([record(), record(runB, 'Synthetic Contoso')]);
    client.getRun = vi.fn().mockImplementation((id: string) => id === runA ? late.promise : Promise.resolve(record(runB, 'Synthetic Contoso')));
    render(<ControlRoom api={client} accountName="reader" onSignOut={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: /Synthetic Contoso/ }));
    expect(await screen.findByRole('heading', { name: 'Synthetic Contoso' })).toBeInTheDocument();
    await act(async () => late.resolve(record()));
    expect(screen.getByRole('heading', { name: 'Synthetic Contoso' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Fictional Fabrikam' })).not.toBeInTheDocument();
  });

  it('clears prior Run data on refresh failures without rendering arbitrary error details', async () => {
    const client = api();
    render(<ControlRoom api={client} accountName="reader" onSignOut={() => {}} />);
    await screen.findByRole('heading', { name: 'Decision summary' });
    vi.mocked(client.listRuns).mockRejectedValueOnce(new Error('private access token must not be rendered'));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh Runs' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Runs could not be loaded');
    expect(screen.queryByText('accepted:synthetic-receipt')).not.toBeInTheDocument();
    expect(screen.queryByText(/private access token/)).not.toBeInTheDocument();
  });

  it('does not display another Run returned by an inconsistent API response', async () => {
    const client = api(); client.getRun = vi.fn().mockResolvedValue(record(runB));
    render(<ControlRoom api={client} accountName="reader" onSignOut={() => {}} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Run details could not be loaded');
    expect(screen.queryByText('accepted:synthetic-receipt')).not.toBeInTheDocument();
  });

  it.each(['missing', 'duplicate', 'correlation'] as const)('fails closed on %s audit events', async failure => {
    const client = api();
    const events = failure === 'missing' ? [event(runA, 1)] : failure === 'duplicate' ? [event(runA, 1), event(runA, 1)] : [event(runA, 1), { ...event(runA, 2), correlation_id: runB }];
    client.getEvents = vi.fn().mockResolvedValue(events);
    render(<ControlRoom api={client} accountName="reader" onSignOut={() => {}} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Run details could not be loaded');
    expect(screen.queryByText('accepted:synthetic-receipt')).not.toBeInTheDocument();
  });

  it('takes a complete event prefix when a later audit event arrives after the Run snapshot', async () => {
    const client = api(); client.getEvents = vi.fn().mockResolvedValue([event(runA, 1), event(runA, 2), event(runA, 3)]);
    render(<ControlRoom api={client} accountName="reader" onSignOut={() => {}} />);
    await screen.findByRole('heading', { name: 'Decision summary' });
    fireEvent.click(screen.getByRole('tab', { name: 'Timeline' }));
    expect(within(screen.getByRole('tabpanel')).getAllByRole('listitem')).toHaveLength(2);
  });

  it('clears the selected snapshot when account identity changes', async () => {
    const client = api(); const onSignOut = () => {};
    const { rerender } = render(<ControlRoom api={client} accountName="first-account" onSignOut={onSignOut} />);
    await screen.findByRole('heading', { name: 'Decision summary' });
    const pending = deferred<RunRecord[]>(); vi.mocked(client.listRuns).mockReturnValueOnce(pending.promise);
    rerender(<ControlRoom api={client} accountName="second-account" onSignOut={onSignOut} />);
    expect(screen.queryByText('accepted:synthetic-receipt')).not.toBeInTheDocument();
    await act(async () => pending.resolve([]));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'No Runs available' })).toBeInTheDocument());
    expect(screen.queryByRole('heading', { name: 'Decision summary' })).not.toBeInTheDocument();
  });
});

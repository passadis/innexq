import { useEffect, useState } from 'react';
import { Button } from '@fluentui/react-components';
import type { CoverageApi, CoverageRenewalView, CoverageStage } from './coverage-api';

export interface CoverageRenewalsProps { api: CoverageApi; accountName: string; refreshEpoch?: number }

function Package({ item }: { item: CoverageRenewalView }) {
  const pack = item.package;
  if (!pack) return <p className="iq-muted">No package drafted. {item.holdReasons.length ? `Hold: ${item.holdReasons.map(reason => reason.replaceAll('_', ' ')).join(' · ')}` : 'Evidence review in progress.'}</p>;
  return <div className="iq-coverage-package">
    <p>Renewal quote · {pack.coverageMonths} months · serial {pack.serialNumber}</p>
    <p>Base {pack.quote.currency} {pack.quote.baseAmount} · VAT {pack.quote.vatRatePercent}% = {pack.quote.currency} {pack.quote.vatAmount} · <strong>Total {pack.quote.currency} {pack.quote.totalAmount}</strong></p>
    <p className="iq-muted">{pack.invoiceNotice}</p>
    <p className="iq-muted">Replaces {pack.previousDocument.documentId} v{pack.previousDocument.documentVersion}</p>
    <p className="iq-mono">Package v{pack.version} · SHA-256 {pack.hash}</p>
  </div>;
}

function Decisions({ item }: { item: CoverageRenewalView }) {
  return <>{([['Operations', item.operationsDecision], ['Manager', item.managerDecision]] as const).map(([label, decision]) => decision &&
    <p key={label} className="iq-muted">{label}: {decision.decision === 'approve' ? 'approved' : 'rejected'} <time dateTime={decision.submittedAt}>{new Date(decision.submittedAt).toLocaleString()}</time>{decision.rejectReason ? ` · ${decision.rejectReason}` : ''}</p>)}</>;
}

function Actions({ item, api, onUpdated }: { item: CoverageRenewalView; api: CoverageApi; onUpdated: (record: CoverageRenewalView) => void }) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const stage: CoverageStage | null = item.state === 'AWAITING_OPERATIONS_APPROVAL' ? 'operations' : item.state === 'AWAITING_MANAGER_APPROVAL' ? 'manager' : null;
  if (!stage || !item.package) return null;
  const pack = item.package;
  async function decide(decision: 'approve' | 'reject') {
    setBusy(true); setError(false);
    try {
      // Restate exactly the displayed package version and hash; the API refuses drift.
      onUpdated(await api.decide(item.requestId, stage as CoverageStage, {
        decision, packageVersion: pack.version, packageHash: pack.hash,
        ...(decision === 'reject' ? { rejectReason: reason.trim() } : {}),
      }));
    } catch { setError(true); } finally { setBusy(false); }
  }
  return <div className="iq-coverage-actions">
    <p>{stage === 'operations'
      ? 'Approving forwards this exact package to the Manager. Nothing is issued or charged until the Manager also approves.'
      : 'Manager approval authorizes issuing exactly this certificate and synthetic invoice. Coverage starts on the approval date.'}</p>
    <Button appearance="primary" disabled={busy} onClick={() => void decide('approve')}>
      {stage === 'operations' ? 'Acknowledge and Approve' : `Approve package v${pack.version}`}</Button>
    <label>Rejection reason (kept internal)<input value={reason} maxLength={500} onChange={event => setReason(event.target.value)} /></label>
    <Button disabled={busy || !reason.trim()} onClick={() => void decide('reject')}>Reject</Button>
    {error && <p role="alert">The decision was not accepted. Refresh the queue: the package or state may have changed, or this account is not the assigned {stage === 'operations' ? 'Operations reviewer' : 'Manager'}.</p>}
  </div>;
}

/** Two-person renewal queue. Decisions bind to the displayed package hash only. */
export function CoverageRenewals({ api, accountName, refreshEpoch = 0 }: CoverageRenewalsProps) {
  const [epoch, setEpoch] = useState(0);
  const [snapshot, setSnapshot] = useState<{ api: CoverageApi; account: string; epoch: number; refreshEpoch: number; records: CoverageRenewalView[] } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); let active = true;
    setSnapshot(null); setError(false);
    void api.list(controller.signal).then(records => {
      if (active) setSnapshot({ api, account: accountName, epoch, refreshEpoch, records });
    }).catch(() => { if (active) { setSnapshot(null); setError(true); } });
    return () => { active = false; controller.abort(); };
  }, [api, accountName, epoch, refreshEpoch]);
  const current = snapshot?.api === api && snapshot.account === accountName && snapshot.epoch === epoch && snapshot.refreshEpoch === refreshEpoch ? snapshot : null;
  const records = [...(current?.records ?? [])].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt) || a.requestId.localeCompare(b.requestId));
  function replace(record: CoverageRenewalView) {
    setSnapshot(value => value && { ...value, records: value.records.map(item => item.requestId === record.requestId ? record : item) });
  }
  return <section className="iq-panel iq-coverage-renewals" aria-labelledby="iq-coverage-renewals-title">
    <div className="iq-section-title"><div><p className="iq-eyebrow">SERVICE COVERAGE RENEWAL</p><h2 id="iq-coverage-renewals-title">Coverage renewals requiring review</h2></div><Button disabled={!current && !error} onClick={() => setEpoch(value => value + 1)}>Refresh coverage renewals</Button></div>
    <p className="iq-muted">Two approvals are required: Operations, then a distinct Manager. Every decision binds to the exact package hash shown; nothing is issued or charged before both approvals.</p>
    {error ? <div role="alert" className="iq-alert">Coverage renewals could not be loaded. No previous entries are shown. Refresh or check your access.</div> : !current ? <p role="status">Loading coverage renewals…</p> : !records.length ? <p>No coverage renewals were returned for this account.</p> : <ul className="iq-case-list">{records.map(item => <li key={item.requestId}>
      <div className="iq-section-title"><strong>{item.equipmentId}</strong><span>{item.publicProgress}</span></div>
      <p>{item.customerId} · <time dateTime={item.updatedAt}>{new Date(item.updatedAt).toLocaleString()}</time></p>
      <p className="iq-mono">Request: {item.requestId}</p>
      <Package item={item} />
      <Decisions item={item} />
      <Actions item={item} api={api} onUpdated={replace} />
    </li>)}</ul>}
  </section>;
}

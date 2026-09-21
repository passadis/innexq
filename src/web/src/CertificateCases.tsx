import { useEffect, useState } from 'react';
import { Button } from '@fluentui/react-components';
import type { OperationsApi, OperationsCaseView } from './operations-api';
import { InternalLink } from './navigation';

export interface CertificateCasesProps { api: OperationsApi; accountName: string; refreshEpoch?: number }

/** Existing employee case-read API. No new request or release authority. */
export function CertificateCases({ api, accountName, refreshEpoch = 0 }: CertificateCasesProps) {
  const [epoch, setEpoch] = useState(0);
  const [snapshot, setSnapshot] = useState<{ api: OperationsApi; account: string; epoch: number; refreshEpoch: number; records: OperationsCaseView[] } | null>(null);
  const [error, setError] = useState(false);
  const [query, setQuery] = useState('');
  useEffect(() => {
    const controller = new AbortController(); let active = true;
    setSnapshot(null); setError(false);
    void api.list(controller.signal).then(records => {
      if (active) setSnapshot({ api, account: accountName, epoch, refreshEpoch, records });
    }).catch(() => { if (active) { setSnapshot(null); setError(true); } });
    return () => { active = false; controller.abort(); };
  }, [api, accountName, epoch, refreshEpoch]);
  const current = snapshot?.api === api && snapshot.account === accountName && snapshot.epoch === epoch && snapshot.refreshEpoch === refreshEpoch ? snapshot : null;
  const records = [...(current?.records ?? [])].sort((a, b) => Date.parse(b.evaluatedAt) - Date.parse(a.evaluatedAt) || a.requestId.localeCompare(b.requestId));
  const visible = records.filter(item => `${item.customerId} ${item.equipmentId} ${item.requestId} ${item.caseId}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <section className="iq-panel iq-certificate-cases" aria-labelledby="iq-certificate-cases-title">
    <div className="iq-section-title"><div><p className="iq-eyebrow">CERTIFICATE FULFILMENT</p><h2 id="iq-certificate-cases-title">Certificate cases requiring Operations</h2></div><Button disabled={!current && !error} onClick={() => setEpoch(value => value + 1)}>Refresh certificate cases</Button></div>
    <p>Held customer requests appear here as well as in Teams. These are certificate cases, not Contract Renewal Runs.</p>
    <p className="iq-muted">This list shows up to 100 held cases, not successful certificate downloads. Operations can acknowledge, add notes or close without release. Managers can inspect only; acknowledgement does not unlock approval.</p>
    {error ? <div role="alert" className="iq-alert">Certificate cases could not be loaded. No previous cases are shown. Refresh or check your case access; renewal Runs can still be inspected below.</div> : !current ? <p role="status">Loading certificate cases…</p> : <>
      <label className="iq-case-search">Find a certificate case<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Equipment, customer or request reference" /></label>
      <p className="iq-muted">{records.length} held {records.length === 1 ? 'case' : 'cases'} returned</p>
      {!visible.length ? <p>{records.length ? 'No matching certificate cases.' : 'No held certificate cases were returned for this account.'}</p> : <ul className="iq-case-list">{visible.map(item => <li key={item.requestId}>
        <div className="iq-section-title"><InternalLink href={`/?operations=${encodeURIComponent(item.requestId)}`}>Inspect {item.equipmentId}</InternalLink><span>Held · Operations required</span></div>
        <p>{item.customerId} · <time dateTime={item.evaluatedAt}>{new Date(item.evaluatedAt).toLocaleString()}</time></p>
        <p className="iq-mono">Request: {item.requestId}</p>
        <p>{item.reasons.map(reason => reason.replaceAll('_', ' ')).join(' · ')}</p>
      </li>)}</ul>}
    </>}
  </section>;
}

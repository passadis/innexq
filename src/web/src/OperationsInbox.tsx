import { useEffect, useState } from 'react';
import { parseOperationsLink, type OperationsApi, type OperationsCaseView } from './operations-api';
import { CaseReviewPanel } from './CaseReviewPanel';
import type { CaseReviewApi } from './case-review-api';
import { InternalLink } from './navigation';
import './operations-inbox.css';

export interface OperationsInboxProps { api: OperationsApi; reviewApi?: CaseReviewApi; accountName: string; onSignOut: () => void }
const readable = (value: string) => value.replaceAll('_', ' ');
const notificationLabel = { pending: 'Pending dispatch', claimed: 'Sending · unconfirmed', delivered: 'Accepted by Teams', ambiguous: 'Delivery uncertain' };
const evidenceRoles = [{ id: 'document_analyst', label: 'Document Analyst' }, { id: 'equipment_service', label: 'Equipment & Service' }] as const;
const evidenceTools = { get_equipment_record: 'Read equipment record', list_equipment_documents: 'Discover equipment documents', analyze_document: 'Analyze PDF with Document Intelligence', retrieve_policy: 'Retrieve applicable policy' };
const holdExplanation: Record<string, string> = {
  missing_evidence: 'Required supporting evidence was missing. The stored decision does not identify a verified replacement document.',
  stale_evidence: 'The evidence was too old to rely on.',
  ownership_mismatch: 'The ownership evidence did not match this customer and equipment.',
  document_unavailable: 'The required document could not be read.',
  document_mismatch: 'The certificate document did not match the equipment evidence.',
  certificate_outside_validity: 'The certificate was outside its validity period.',
  revoked_or_unknown: 'The certificate was revoked or its status could not be verified.',
  service_mismatch: 'The service evidence did not match the equipment.',
  service_not_current: 'The recorded service status was not current.',
  artifact_changed: 'The PDF changed after the recorded checks.',
  artifact_unavailable: 'The existing PDF could not be retrieved.',
};

export function OperationsInbox({ api, reviewApi, accountName, onSignOut }: OperationsInboxProps) {
  const [link] = useState(() => parseOperationsLink(window.location.search));
  const [snapshot, setSnapshot] = useState<{ api: OperationsApi; account: string; epoch: number; records: OperationsCaseView[] } | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); let active = true;
    setSnapshot(null); setError(false);
    if ('invalid' in link) { setError(true); return () => controller.abort(); }
    void api.list(controller.signal).then(records => {
      if (!active) return;
      if (!records.some(item => item.requestId === link.requestId)) throw new Error('Linked case unavailable');
      setSnapshot({ api, account: accountName, epoch, records });
    }).catch(() => { if (active) { setSnapshot(null); setError(true); } });
    return () => { active = false; controller.abort(); };
  }, [api, accountName, epoch, link]);
  const records = snapshot?.api === api && snapshot.account === accountName && snapshot.epoch === epoch ? snapshot.records : [];
  const current = 'requestId' in link ? records.find(item => item.requestId === link.requestId) : null;
  return <div className="iq-app ops-app"><div className="iq-workspace"><header className="iq-topbar"><InternalLink href="/">InnexQ · Control Room</InternalLink><div className="iq-account"><span>{accountName}</span><button type="button" onClick={onSignOut}>Sign out</button></div></header><main className="iq-main ops-main">
    <div className="iq-page-heading"><div><p className="iq-eyebrow">CERTIFICATE FULFILMENT</p><h1>Operations review<span className="iq-heading-dot">.</span></h1><p>A held request, its evidence and the actual notification outcome.</p></div><button type="button" disabled={!error && !snapshot} onClick={() => setEpoch(value => value + 1)}>Refresh cases</button></div>
    <div className="iq-demo-note">Synthetic demo · Governed case review. This view cannot authorize or release a certificate.</div>
    {error ? <section className="iq-panel iq-alert" role="alert"><h2>This Operations case is unavailable</h2><p>The link may be invalid, the case may be missing, or this account may not have case access. No different case is substituted.</p><InternalLink href="/">Return to Control Room</InternalLink></section> : !current ? <p role="status">Loading the linked Operations case…</p> : <>
      <section className="iq-panel" aria-labelledby="case-story-title"><h2 id="case-story-title">What happened</h2>
        <h3>Customer said</h3>{current.requestContext ? current.requestContext.customerMessages.map((message, index) => <blockquote className="ops-summary" key={index}>{message}</blockquote>) : <p>Original customer message was not recorded.</p>}
        <h3>InnexQ understood</h3><p>Certificate request for {current.equipmentId}.</p>{!current.requestContext && <p className="iq-muted">This is the recorded workflow and equipment, not a reconstruction of what the customer asked.</p>}
        <h3>Result</h3><p>Certificate release was held. At least one required ownership, certificate validity or service check did not pass.</p><ul>{current.reasons.map(reason => <li key={reason}>{holdExplanation[reason] ?? readable(reason)}</li>)}</ul>
        <h3>Next owner: Operations</h3><p>Operations can acknowledge the case, add notes or close it without releasing a certificate. The case audit below shows any actions already taken; a closed case requires no further action here.</p>
        <p>Managers have read-only access to this case. Acknowledgement does not unlock manager approval, and no reviewer can override a failed check. The Teams message is a case notification, not an approval request; its delivery status is shown below.</p>
      </section>
      <section className="iq-panel ops-identity"><div className="iq-section-title"><h2>{current.equipmentId}</h2><span className="ops-hold">Held · Operations required</span></div><dl className="iq-facts"><div><dt>Customer</dt><dd>{current.customerId}</dd></div><div><dt>Request reference</dt><dd>{current.requestId}</dd></div><div><dt>Case reference</dt><dd>{current.caseId}</dd></div><div><dt>Assigned Operations user</dt><dd>{current.assignedUserId}</dd></div><div><dt>Evaluated at</dt><dd>{new Date(current.evaluatedAt).toLocaleString()}</dd></div><div><dt>Decision SHA-256</dt><dd>{current.decisionHash}</dd></div></dl><h3>Recorded hold reasons</h3><ul>{current.reasons.map(reason => <li key={reason}>{readable(reason)}</li>)}</ul></section>
      {reviewApi ? <CaseReviewPanel key={`${accountName}:${current.requestId}`} api={reviewApi} current={current} /> : <section className="iq-panel"><h2>Case inspection</h2><p>Case management is unavailable in this view. Inspect the recorded evidence below. Opening this page does not change the case.</p></section>}
      <section className="iq-panel"><h2>Teams notification</h2><strong>{notificationLabel[current.notification.state]}</strong><p>{current.notification.state === 'delivered' ? 'Teams accepted the message. This is not proof that an operator read it.' : current.notification.state === 'ambiguous' ? 'Delivery could not be confirmed. Inspect Teams and the audit record before any retry; this page sends nothing.' : current.notification.state === 'claimed' ? 'A dispatch attempt is recorded, but acceptance by Teams is not yet confirmed.' : 'The durable notification is waiting for dispatch. No live Teams delivery is claimed.'}</p>{current.notification.receiptId && <p className="iq-mono">Receipt: {current.notification.receiptId}</p>}</section>
      <section className="iq-panel"><h2>Deterministic checks</h2><div className="ops-table-scroll"><table><thead><tr><th>Check</th><th>Verdict</th><th>Reason</th></tr></thead><tbody>{current.checks.map(check => <tr key={check.name}><td>{readable(check.name)}</td><td>{check.verdict}</td><td>{readable(check.reason)}</td></tr>)}</tbody></table></div><p className="iq-muted">Agent summaries do not determine these outcomes or grant release authority.</p></section>
      <section className="iq-panel"><h2>Specialist findings</h2>{current.specialists.length ? current.specialists.map(specialist => <article className="iq-subsection" key={specialist.specialist}><h3>{readable(specialist.specialist)}</h3><p className="ops-summary">{specialist.summary}</p><p className="iq-muted iq-mono">Response: {specialist.responseId}</p></article>) : <p>No specialist findings were recorded for this decision. Evidence retrieval may have stopped before the investigation completed.</p>}</section>
      {!!current.toolActivity?.length && <section className="iq-panel" aria-labelledby="verified-tools-title"><h2 id="verified-tools-title">Verified tool activity</h2><p className="iq-muted">Recorded tool receipts for read-only evidence, not authorization. These calls do not approve or release a certificate.</p>{evidenceRoles.map(role => {
        const activity = current.toolActivity!.filter(item => item.specialist === role.id);
        return activity.length ? <article className="iq-subsection" key={role.id}><h3>{role.label}</h3><ol>{activity.map(item => <li key={item.receiptId}><p><strong>{evidenceTools[item.toolName]}</strong>{item.documentId && <> · {item.documentId}</>}</p><time dateTime={item.completedAt}>{new Date(item.completedAt).toLocaleString()}</time><details><summary>Receipt details</summary><dl className="iq-facts"><div><dt>Receipt</dt><dd>{item.receiptId}</dd></div><div><dt>Investigation attempt</dt><dd>{item.attemptId}</dd></div><div><dt>Source version</dt><dd>{item.sourceVersion}</dd></div></dl></details></li>)}</ol></article> : null;
      })}</section>}
      <section className="iq-panel"><h2>PDF field citations</h2><p className="iq-muted">Recorded Azure Document Intelligence extraction · prebuilt-layout · API 2024-11-30. Values below are source text, not executable instructions.</p>{current.fields.length ? current.fields.map((field, index) => <article className="iq-subsection" key={`${field.documentId}-${index}`}><div className="iq-section-title"><h3>{field.label}</h3><span>Page {field.page}</span></div><p className="ops-summary">{field.value}</p><dl className="iq-facts"><div><dt>Document</dt><dd>{field.documentId}</dd></div><div><dt>Version</dt><dd>{field.documentVersion}</dd></div><div><dt>PDF SHA-256</dt><dd>{field.sha256}</dd></div></dl></article>) : <p>No verified PDF field citations were recorded. The case remains held.</p>}</section>
    </>}<footer className="iq-page-footer"><InternalLink href="/">Return to Control Room</InternalLink><span>Refresh for the latest stored decision and case audit</span></footer>
  </main></div></div>;
}

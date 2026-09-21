import { useEffect, useRef, useState } from 'react';
import type { CaseCommand, CaseReview, CaseReviewApi } from './case-review-api';
import type { OperationsCaseView } from './operations-api';

const labels = { open: 'Open', acknowledged: 'Acknowledged', closed_without_release: 'Closed without release' };
export function CaseReviewPanel({ api, current }: { api: CaseReviewApi; current: OperationsCaseView }) {
  const [snapshot, setSnapshot] = useState<{ api: CaseReviewApi; review: CaseReview; canManage: boolean } | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [note, setNote] = useState('');
  const [pending, setPending] = useState<CaseCommand | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const generation = useRef(0);
  const saving = useRef(false);
  useEffect(() => {
    const controller = new AbortController(), turn = ++generation.current;
    setSnapshot(null); setError(''); setBusy(false); saving.current = false;
    void api.read(current.requestId, controller.signal).then(result => {
      if (turn !== generation.current) return;
      if (result.review.case_id !== current.caseId || result.review.decision_hash !== current.decisionHash || result.review.assigned_user_id !== current.assignedUserId) throw new Error('Case mismatch');
      setSnapshot({ api, ...result });
      setPending(command => result.review.events.some(event => event.command.command_id === command?.command_id) ? null : command);
    }).catch(() => { if (turn === generation.current) setError('Case review could not be loaded. No action is available until refresh succeeds.'); });
    return () => { generation.current++; controller.abort(); };
  }, [api, current.requestId, current.caseId, current.decisionHash, current.assignedUserId, epoch]);
  const data = snapshot?.api === api && snapshot.review.request_id === current.requestId ? snapshot : null;
  const review = data?.review;
  async function submit(command: CaseCommand) {
    if (saving.current || !data?.canManage) return;
    saving.current = true; const turn = generation.current;
    setBusy(true); setError(''); setMessage(''); setPending(command);
    try {
      const result = await api.act(current.requestId, command);
      if (turn !== generation.current) return;
      setSnapshot({ api, review: result, canManage: true }); setPending(null); setNote('');
      setMessage('Action saved to the case audit. No PDF was released.');
    } catch {
      if (turn === generation.current) {
        setSnapshot(null);
        setError('Save was not confirmed. Refresh to inspect the audit before retrying; the case may already have changed.');
      }
    } finally { if (turn === generation.current) { saving.current = false; setBusy(false); } }
  }
  function act(action: CaseCommand['action']) {
    if (!review || pending || busy) return;
    void submit({ command_id: crypto.randomUUID(), case_id: review.case_id, decision_hash: review.decision_hash,
      expected_revision: review.revision, action, note: note.trim() });
  }
  return <section className="iq-panel ops-review-panel"><div className="iq-section-title"><h2>Case actions and audit</h2><button type="button" disabled={busy} onClick={() => { setMessage(''); setEpoch(value => value + 1); }}>Refresh review</button></div>
    <p>Acknowledgement, internal notes and closure never authorize a PDF. All three certificate checks remain mandatory.</p>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {!data && !error && <p role="status">Loading case review…</p>}
    {review && <><p><strong>{labels[review.state]}</strong> · Revision {review.revision} · {data?.canManage ? 'Operations' : 'Manager · Read-only'}</p>
      {data?.canManage && review.state !== 'closed_without_release' && !pending && <div className="ops-case-controls">
        <label htmlFor="case-note">Internal note or closure reason</label><textarea id="case-note" maxLength={2000} rows={4} value={note} disabled={busy} onChange={event => setNote(event.target.value)} />
        <p className="iq-muted">Staff only. Not sent to customers, Teams or agents. Closing requires a reason and cannot be undone here.</p>
        <div className="ops-case-buttons"><button type="button" disabled={busy || review.state !== 'open'} onClick={() => act('acknowledge')}>Acknowledge</button><button type="button" disabled={busy || !note.trim()} onClick={() => act('add_note')}>Add internal note</button><button type="button" disabled={busy || !note.trim()} onClick={() => act('close_without_release')}>Close without release</button></div>
      </div>}
      {pending && data?.canManage && <p>{pending.expected_revision === review.revision && review.state !== 'closed_without_release' ? <button type="button" disabled={busy} onClick={() => void submit(pending)}>Retry the same action</button> : <button type="button" disabled={busy} onClick={() => { setPending(null); setNote(''); }}>Dismiss stale action</button>}</p>}
      {review.state === 'closed_without_release' && <p>This case is closed. The original customer request remains held; no certificate was released by closure.</p>}
      <h3>Internal history</h3>{review.events.length ? <ol className="ops-review-history">{review.events.map(event => <li key={event.command.command_id}><strong>{event.command.action.replaceAll('_', ' ')}</strong><p>{event.command.note || 'Case acknowledged.'}</p><small>{new Date(event.occurred_at).toLocaleString()} · Actor {event.actor_user_id} · Revision {event.sequence}</small></li>)}</ol> : <p>No case actions recorded yet.</p>}
    </>}
  </section>;
}

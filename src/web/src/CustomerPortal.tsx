import { useEffect, useId, useRef, useState } from 'react';
import { customerMessageResponse, statusResponse, type CustomerApi, type CustomerCatalog, type CustomerMessage, type CustomerMessageInput, type CustomerRequestStatus } from './customer-api';
import './customer-portal.css';

export interface CustomerPortalProps {
  api: CustomerApi;
  /** Use the stable signed-in account identifier as the React key when switching accounts. */
  accountName: string;
  onSignOut: () => void;
}

export function CustomerPortal({ api, accountName, onSignOut }: CustomerPortalProps) {
  const [catalog, setCatalog] = useState<{ api: CustomerApi; account: string; value: CustomerCatalog } | null>(null);
  const [catalogError, setCatalogError] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [equipmentId, setEquipmentId] = useState('');
  const [prompt, setPrompt] = useState('');
  const [result, setResult] = useState<CustomerRequestStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [downloadNotice, setDownloadNotice] = useState(false);
  const [turns, setTurns] = useState<{ prompt: string; response: CustomerMessage }[]>([]);
  const [proposal, setProposal] = useState<CustomerMessage | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const [statusUnavailable, setStatusUnavailable] = useState(false);
  const pending = useRef<CustomerMessageInput | null>(null);
  const requestController = useRef<AbortController | null>(null);
  const operation = useRef(0);
  const equipmentLabel = useId();
  const promptLabel = useId();

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    operation.current += 1;
    requestController.current?.abort();
    requestController.current = null;
    pending.current = null;
    setCatalog(null); setCatalogError(false); setResult(null); setError(''); setBusy(false); setStatusUnavailable(false);
    setEquipmentId(''); setPrompt(''); setDownloadNotice(false); setTurns([]); setProposal(null); setSignedOut(false);
    void api.catalog(controller.signal).then(value => {
      if (!active) return;
      setCatalog({ api, account: accountName, value });
    }).catch(() => { if (active) setCatalogError(true); });
    return () => { active = false; controller.abort(); requestController.current?.abort(); operation.current += 1; };
  }, [api, accountName, epoch]);

  const current = !signedOut && catalog?.api === api && catalog.account === accountName ? catalog.value : null;
  const visibleResult = current ? result : null;
  const caseLabel = visibleResult?.case_status ? {
    not_required: 'No review needed', open: 'Awaiting Operations',
    acknowledged: 'Under review', closed_without_release: 'Closed without release',
  }[visibleResult.case_status] : 'Progress unavailable';

  useEffect(() => {
    if (!current || busy || statusUnavailable || visibleResult?.status !== 'operations_required' ||
        visibleResult.case_status === 'closed_without_release') return;
    const id = visibleResult.request_id;
    const serial = operation.current;
    const controller = new AbortController();
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!active || controller.signal.aborted || serial !== operation.current) return;
      if (!document.hidden) {
        try {
          const value = statusResponse(await api.status(id, controller.signal), id);
          if (!active || controller.signal.aborted || serial !== operation.current) return;
          setResult(value);
          if (value.case_status === 'closed_without_release' || value.status !== 'operations_required') return;
        } catch {
          if (active && !controller.signal.aborted && serial === operation.current) setStatusUnavailable(true);
          return;
        }
      }
      timer = setTimeout(() => { void poll(); }, 15000);
    };
    timer = setTimeout(() => { void poll(); }, 15000);
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [api, current, busy, statusUnavailable, visibleResult?.request_id, visibleResult?.status, visibleResult?.case_status]);

  function edit(nextEquipment: string, nextPrompt: string) {
    if (requestController.current) return;
    operation.current += 1; setStatusUnavailable(false);
    setEquipmentId(nextEquipment); setPrompt(nextPrompt); setResult(null); setError('');
    pending.current = null; setDownloadNotice(false); setProposal(null);
  }

  function resetConversation() {
    requestController.current?.abort(); requestController.current = null; operation.current += 1;
    pending.current = null; setTurns([]); setProposal(null); setResult(null); setEquipmentId('');
    setPrompt(''); setError(''); setBusy(false); setDownloadNotice(false); setStatusUnavailable(false);
  }

  function signOut() {
    resetConversation(); setCatalog(null); setSignedOut(true); onSignOut();
  }

  async function perform(action: (signal: AbortSignal) => Promise<void>) {
    if (requestController.current || !current) return;
    const controller = new AbortController();
    const serial = ++operation.current;
    requestController.current = controller;
    setBusy(true); setError(''); setDownloadNotice(false); setStatusUnavailable(false);
    try { await action(controller.signal); }
    catch {
      if (operation.current === serial && !controller.signal.aborted) {
        setError('We could not complete this step. Retry, or sign out and sign in again if your session has expired.');
      }
    } finally {
      if (operation.current === serial) { requestController.current = null; setBusy(false); }
    }
  }

  function submit() {
    if (requestController.current || !current || turns.length >= 6 || !prompt.trim() || prompt.length > 1000 ||
        (equipmentId && !current.equipment.some(item => item.equipment_id === equipmentId))) return;
    if (!pending.current) pending.current = { message_id: crypto.randomUUID(), equipment_id: equipmentId || null, prompt: prompt.trim(), parent_message_id: turns.at(-1)?.response.message_id ?? null };
    const input = pending.current;
    setProposal(null); setResult(null);
    void perform(async signal => {
      const value = customerMessageResponse(await api.message(input, signal), input.message_id);
      if (value.equipment_id !== null && !current.equipment.some(item => item.equipment_id === value.equipment_id)) throw new Error('Equipment mismatch');
      if (!signal.aborted) {
        setTurns(previous => [...previous, { prompt: input.prompt, response: value }]);
        setProposal(value.can_confirm ? value : null); setPrompt(''); setEquipmentId(''); pending.current = null;
      }
    });
  }

  function confirm() {
    if (!proposal?.can_confirm || proposal.kind !== 'confirmation_required' || proposal.intent !== 'certificate_request' || visibleResult) return;
    const id = proposal.message_id;
    void perform(async signal => {
      const value = statusResponse(await api.confirm(id, signal), id);
      if (value.request_id !== id || !['release_ready', 'operations_required'].includes(value.status)) throw new Error('Request mismatch');
      if (!signal.aborted) { setResult(value); setProposal(null); }
    });
  }

  function refresh() {
    if (!visibleResult) return;
    const id = visibleResult.request_id;
    void perform(async signal => {
      try {
        const value = statusResponse(await api.status(id, signal), id);
        if (value.request_id !== id) throw new Error('Request mismatch');
        if (!signal.aborted) setResult(value);
      } catch {
        if (!signal.aborted) setResult(null);
        throw new Error('Status unavailable');
      }
    });
  }

  function download() {
    if (visibleResult?.status !== 'release_ready') return;
    const id = visibleResult.request_id;
    void perform(async signal => {
      let blob: Blob;
      try { blob = await api.pdf(id, signal); }
      catch {
        // A new source check may have held the request. Show its actual persisted state.
        try {
          const value = statusResponse(await api.status(id, signal), id);
          if (!signal.aborted && value.request_id === id) setResult(value);
        } catch { if (!signal.aborted) setResult(null); }
        throw new Error('Download unavailable');
      }
      if (signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `InnexQ-certificate-${id}.pdf`;
      document.body.append(link);
      try { link.click(); setDownloadNotice(true); }
      finally { link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }
    });
  }

  return <div className="cp-app">
    <a className="cp-skip" href="#customer-main">Skip to requests</a>
    <header className="cp-header"><a className="cp-brand" href="#customer-main" aria-label="InnexQ Customer Portal"><span aria-hidden="true">iQ</span>InnexQ</a><div><span>{accountName}</span><button type="button" onClick={signOut}>Sign out</button></div></header>
    <main id="customer-main" className="cp-main" tabIndex={-1}>
      <section className="cp-intro"><p className="cp-eyebrow">CUSTOMER PORTAL / EQUIPMENT ASSISTANT</p><h1>Your equipment.<br />Ask. Understand. Request.</h1><p>Ask about recorded service or certificate status, or request an existing certificate. Questions do not release documents. Certificate requests need your confirmation and eligibility checks.</p></section>
      <div className="cp-demo">Synthetic hackathon environment · Fictional equipment and documents, real governed requests.</div>
      {catalogError ? <section className="cp-panel" role="alert"><h2>Your workspace could not be loaded</h2><p>No previous customer data is shown. Retry or sign in again.</p><button type="button" onClick={() => setEpoch(value => value + 1)}>Retry workspace</button></section> : !current ? <p role="status">Loading your equipment…</p> : <>
        <div className="cp-section-heading"><h2>{current.customer_name}</h2><span>{current.equipment.length} assigned equipment items</span></div>
        <div className="cp-layout">
          <section className="cp-panel" aria-labelledby="cp-request-heading"><p className="cp-eyebrow">HOW CAN WE HELP?</p><h2 id="cp-request-heading">Talk about your equipment</h2><p>Use your own words. Choose equipment below, mention its ID, or answer a follow-up question. Service booking is not available here.</p>
            <div className="cp-presets" aria-label="Suggested requests">{[...current.presets.slice(0, 8), ...current.equipment.slice(0, 2).map(item => ({ equipment_id: item.equipment_id, prompt: `Is service for ${item.equipment_id} up to date?` }))].slice(0, 10).map((preset, index) => <button type="button" key={`${preset.equipment_id}-${index}`} disabled={busy || turns.length >= 6} onClick={() => edit(preset.equipment_id, preset.prompt)}>{preset.prompt}</button>)}</div>
            {turns.length > 0 && <ol className="cp-conversation" aria-label="Conversation">{turns.map(({ prompt: said, response }) => <li key={response.message_id}>
              <div className="cp-customer-message"><strong>You</strong><p>{said}</p></div>
              <div className="cp-assistant-message"><strong>InnexQ</strong><p>{response.message}</p>
                <p className="cp-understood">Understood: {response.intent.replaceAll('_', ' ')}{response.equipment_id ? ` · ${response.equipment_id}` : ' · equipment not selected'}</p>
                {response.as_of && <p className="cp-muted">Evidence checked as of <time dateTime={response.as_of}>{response.as_of}</time></p>}
                {response.citations.length > 0 && <details><summary>Evidence used ({response.citations.length})</summary><ul>{response.citations.map((source, index) => <li key={index}><strong>{source.label}</strong>: {source.value}<span className="cp-source">{source.document_id} · version {source.document_version} · page {source.page}</span></li>)}</ul></details>}
                {response.kind === 'unsupported' && <p className="cp-muted">No service booking or approval workflow was created.</p>}
              </div>
            </li>)}</ol>}
            {proposal && <div className="cp-confirm"><p>Request the existing certificate for <strong>{proposal.equipment_id}</strong>? Your confirmation starts the ownership, validity and service checks; it does not approve a release.</p><button type="button" className="cp-primary" disabled={busy} onClick={confirm}>Request this certificate</button></div>}
            <form onSubmit={event => { event.preventDefault(); submit(); }}>
              <label htmlFor={equipmentLabel}>Your equipment (optional)</label><select id={equipmentLabel} value={equipmentId} disabled={busy || turns.length >= 6 || current.equipment.length === 0} onChange={event => edit(event.target.value, prompt)}><option value="">Mention equipment in your message</option>{current.equipment.map(item => <option value={item.equipment_id} key={item.equipment_id}>{item.equipment_id} · {item.name} · {item.serial_number}</option>)}</select>
              <label htmlFor={promptLabel}>Your message</label><textarea id={promptLabel} rows={3} maxLength={1000} value={prompt} disabled={busy || turns.length >= 6} placeholder="Is service for PT-001 up to date?" onChange={event => edit(equipmentId, event.target.value)} />
              <button className="cp-primary" type="submit" disabled={busy || turns.length >= 6 || !prompt.trim()}>{busy ? 'Working…' : 'Send message'}</button>
            </form>
            {turns.length >= 6 && <p>Conversation limit reached. Start a new conversation to continue.</p>}
            {(turns.length > 0 || pending.current) && <button type="button" className="cp-new" onClick={resetConversation}>Start new conversation</button>}
            {busy && <p role="status">Waiting for InnexQ. No release decision has been assumed.</p>}
            {error && <p className="cp-error" role="alert">{error}</p>}
          </section>
          <section className="cp-panel cp-result" aria-labelledby="cp-result-heading" aria-live="polite"><p className="cp-eyebrow">YOUR REQUEST</p><h2 id="cp-result-heading">{visibleResult ? visibleResult.status === 'release_ready' ? 'Certificate ready' : visibleResult.case_status === 'closed_without_release' ? 'Request closed' : 'Operations review needed' : 'Ready when you are'}</h2>
{visibleResult ? <><span className={`cp-badge ${visibleResult.status === 'release_ready' ? 'cp-ready' : 'cp-held'}`}>{visibleResult.status === 'release_ready' ? 'Available for download' : 'Not released'}</span><p>{visibleResult.status === 'release_ready' ? 'Your existing PDF is available. We will check eligibility again when you download.' : visibleResult.case_status === 'closed_without_release' ? 'Operations has closed your request. No certificate was released.' : visibleResult.case_status === 'acknowledged' ? 'Operations is reviewing your request. No certificate has been released.' : 'Your request has been saved for Operations review. No certificate has been released.'}</p><dl><dt>Certificate</dt><dd>{visibleResult.status === 'release_ready' ? 'Available for download' : 'Not released'}</dd><dt>Case</dt><dd>{caseLabel}</dd>{visibleResult.updated_at && <><dt>Last updated</dt><dd><time dateTime={visibleResult.updated_at}>{new Date(visibleResult.updated_at).toLocaleString()}</time></dd></>}<dt>Request reference</dt><dd>{visibleResult.request_id}</dd></dl>{statusUnavailable ? <p role="alert">Live updates are unavailable. Showing the last known status. Use Refresh status to try again.</p> : visibleResult.status === 'operations_required' && visibleResult.case_status !== 'closed_without_release' && <p className="cp-muted">Checks for updates every 15 seconds while this page is visible.</p>}<div className="cp-actions">{visibleResult.status === 'release_ready' && <button className="cp-primary" type="button" disabled={busy} onClick={download}>Download existing PDF</button>}<button type="button" disabled={busy} onClick={refresh}>Refresh status</button></div>{downloadNotice && <p role="status">The PDF was handed to your browser. Check your downloads to confirm it was saved.</p>}</> : <><div className="cp-document" aria-hidden="true">PDF</div><p>Your request status will appear here after the service responds.</p><p className="cp-muted">If a required check cannot pass, the request stops for Operations. No replacement certificate is generated.</p></>}
          </section>
        </div>
      </>}
      <footer className="cp-footer">InnexQ · Governed enterprise workflows<span>Only equipment assigned to your signed-in account is available.</span></footer>
    </main>
  </div>;
}

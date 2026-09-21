import { useEffect, useId, useState, type ReactNode } from 'react';
import { Badge, Button, Input, Select, Spinner, Tab, TabList } from '@fluentui/react-components';
import type { RunEvent, RunRecord } from './contracts';
import { parseDecisionLink } from './decision-link';
import { EmailPreview } from './EmailPreview';
import { CertificateCases } from './CertificateCases';
import type { OperationsApi } from './operations-api';
import './control-room.css';

export interface ControlRoomProps {
  api: {
    listRuns(signal?: AbortSignal): Promise<RunRecord[]>;
    getRun(id: string, signal?: AbortSignal): Promise<RunRecord>;
    getEvents(id: string, signal?: AbortSignal): Promise<RunEvent[]>;
  };
  accountName: string;
  onSignOut: () => void;
  operationsApi?: OperationsApi;
}

type View = 'overview' | 'evidence' | 'decision' | 'timeline';
type Snapshot = { id: string; account: string; api: ControlRoomProps['api']; epoch: number; record: RunRecord; events: RunEvent[] };
type RunList = { account: string; api: ControlRoomProps['api']; epoch: number; records: RunRecord[] };

function readable(value: string): string {
  return value.replaceAll('_', ' ').replaceAll('.', ' · ');
}

function timestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' });
}

function Status({ state }: { state: string }) {
  const color = state === 'EXECUTED' ? 'success' : state.includes('HOLD') || state.includes('FAILED') ? 'danger' : state === 'AWAITING_APPROVAL' ? 'warning' : 'informative';
  return <Badge appearance="tint" color={color} className="iq-status">{readable(state)}</Badge>;
}

function Exact({ value }: { value: unknown }) {
  return <pre className="iq-exact">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>;
}

function Locator({ value }: { value: string }) {
  let safe = false;
  let synthetic = false;
  try {
    const url = new URL(value);
    synthetic = url.hostname === 'invalid' || url.hostname.endsWith('.invalid');
    safe = url.protocol === 'https:' && !url.username && !url.password && !synthetic;
  } catch { /* Non-web source locators remain text. */ }
  return safe ? <a className="iq-mono" href={value} target="_blank" rel="noopener noreferrer">{value} <span className="iq-sr-only">(opens in a new tab)</span></a> : <><span className="iq-mono">{value}</span>{synthetic && <span className="iq-field-label">Synthetic provenance reference · not a document download link</span>}</>;
}

function Empty({ title, children }: { title: string; children: ReactNode }) {
  return <div className="iq-empty"><div className="iq-empty-mark" aria-hidden="true">◇</div><h3>{title}</h3><p>{children}</p></div>;
}

function EnvelopeIdentity({ record }: { record: RunRecord }) {
  return <div className="iq-envelope-id">
    <div><span className="iq-eyebrow">Current immutable envelope</span><strong>{record.run.current_brief_version ? `Version ${record.run.current_brief_version}` : 'Not assembled yet'}</strong></div>
    {record.run.current_brief_hash && <div><span className="iq-field-label">SHA-256 · brief and action manifest</span><code>{record.run.current_brief_hash}</code></div>}
    {record.envelope && record.envelope.brief_hash !== record.run.current_brief_hash && <p role="alert" className="iq-alert">Envelope and Run hashes differ. Refresh and inspect the audit trail; do not use this snapshot for a decision.</p>}
  </div>;
}

function Overview({ record }: { record: RunRecord }) {
  const brief = record.envelope?.brief;
  const approval = record.approval;
  return <div className="iq-section-stack">
    <section className="iq-panel"><div className="iq-section-title"><h3>Decision summary</h3><Badge appearance="outline">Agent proposal</Badge></div>
      <p className="iq-summary">{brief?.presentation.plain_language_summary ?? record.proposal?.summary ?? 'No proposal has been assembled for this Run.'}</p>
      <p className="iq-muted">A proposal is not authorization. Recorded calculations, policy checks and human authorization are shown separately.</p>
    </section>
    <div className="iq-two-column">
      <section className="iq-panel"><h3>Workflow context</h3><dl className="iq-facts">
        <div><dt>Workflow Pack</dt><dd>Contract Renewal</dd></div><div><dt>Contract</dt><dd>{record.run.contract_id}</dd></div>
        <div><dt>Created</dt><dd><time dateTime={record.run.created_at}>{timestamp(record.run.created_at)}</time></dd></div>
        <div><dt>Updated</dt><dd><time dateTime={record.run.updated_at}>{timestamp(record.run.updated_at)}</time></dd></div>
        <div><dt>Revision</dt><dd>{record.revision}</dd></div><div><dt>Correlation ID</dt><dd className="iq-mono">{record.run.correlation_id}</dd></div>
      </dl></section>
      <section className="iq-panel"><h3>Human authorization</h3>{approval ? <>
        <Badge appearance="tint" color={approval.decision === 'approve' ? 'success' : 'informative'}>{readable(approval.decision)}</Badge>
        <dl className="iq-facts"><div><dt>Actor</dt><dd className="iq-mono">{approval.actor_user_id}</dd></div><div><dt>Submitted</dt><dd><time dateTime={approval.submitted_at}>{timestamp(approval.submitted_at)}</time></dd></div>
          <div><dt>Authorized version</dt><dd>{approval.brief_version}</dd></div><div><dt>Authorized hash</dt><dd className="iq-mono">{approval.brief_hash}</dd></div>
          <div><dt>Authority verdict</dt><dd>{readable(approval.authority_result.verdict)}</dd></div><div><dt>Scenario role</dt><dd>{readable(approval.authority_result.actor_scenario_role)}</dd></div>
        </dl>{approval.comment && <p className="iq-verbatim">{approval.comment}</p>}
      </> : <p className="iq-muted">No human decision is recorded. Approvals happen in Teams, never in this read-only view.</p>}</section>
    </div>
    <Receipts record={record} />
    <details className="iq-panel"><summary>Recorded facts · exact source values</summary><p className="iq-muted">Displayed as stored. The browser does not calculate pricing or determine authority.</p><Exact value={record.facts} /></details>
  </div>;
}

function Receipts({ record }: { record: RunRecord }) {
  const actions = record.envelope?.action_manifest.actions ?? [];
  const receipts = record.receipts ?? {};
  return <section className="iq-panel"><div className="iq-section-title"><h3>Controlled execution</h3><Badge appearance="outline">Executor receipts</Badge></div>
    <p className="iq-muted">A mail acceptance receipt confirms Microsoft Graph accepted the request, not inbox delivery. Started or unknown actions must not be blindly retried.</p>
    {actions.length === 0 ? <p>No action manifest has been assembled.</p> : <div className="iq-receipts">{actions.map(action => <article className="iq-receipt" key={action.action_id}>
      <div className="iq-section-title"><h4>{action.action_type === 'graph.send_mail' ? 'Test email' : action.action_type === 'sharepoint.create_file' ? 'SharePoint file' : readable(action.action_type)}</h4><Badge appearance="outline">{record.action_status?.[action.idempotency_key] ?? 'not started'}</Badge></div>
      <span className="iq-field-label">{action.action_type === 'graph.send_mail' ? 'Mail acceptance receipt' : 'Stored receipt'}</span>
      <code>{receipts[action.idempotency_key] ?? 'No receipt recorded'}</code>
      <span className="iq-field-label">Idempotency key</span><code>{action.idempotency_key}</code>
    </article>)}</div>}
    <details className="iq-raw"><summary>All exact receipt and action-status values</summary><Exact value={{ action_status: record.action_status, receipts: record.receipts }} /></details>
  </section>;
}

function Evidence({ record }: { record: RunRecord }) {
  const evidence = record.evidence ?? [];
  return <div className="iq-section-stack"><div className="iq-view-intro"><h3>Evidence, with provenance</h3><p>Exact stored excerpts from the synthetic corpus. Source labels describe recorded provenance, not a new retrieval by this page.</p></div>
    {evidence.length === 0 ? <Empty title="No validated evidence yet">Unvalidated model citations are not presented as validated evidence. Inspect the timeline for gaps or a safe hold.</Empty> : evidence.map(item => <article className="iq-panel" key={item.evidence_id}>
      <div className="iq-section-title"><h3>{item.source_name}</h3><div className="iq-badges"><Badge appearance="tint" color="informative">{readable(item.source_kind)}</Badge><Badge appearance="outline">{item.classification}</Badge></div></div>
      <p className="iq-source"><Locator value={item.source_locator} /></p>
      <div className="iq-field-label">Exact evidence excerpt</div><Exact value={item.excerpt} />
      <div className="iq-evidence-meta"><span>Retrieved <time dateTime={item.retrieved_at}>{timestamp(item.retrieved_at)}</time></span><span>{readable(item.actor_context.authorization_mode)}</span></div>
      <details className="iq-raw"><summary>Evidence identity and claim lineage</summary><Exact value={{ evidence_id: item.evidence_id, supports_claim_ids: item.supports_claim_ids, actor_context: item.actor_context }} /></details>
    </article>)}
    {record.proposal && <details className="iq-panel"><summary>Original agent proposal · untrusted until validated</summary><Exact value={record.proposal} /></details>}
  </div>;
}

function DecisionView({ record }: { record: RunRecord }) {
  const envelope = record.envelope;
  if (!envelope) return <Empty title="No decision envelope yet">The controller must assemble and validate a brief before a human can authorize its exact version.</Empty>;
  const brief = envelope.brief;
  return <div className="iq-section-stack">
    <div className="iq-view-intro"><h3>Decision brief · version {brief.brief_version}</h3><p>Read-only inspection of the current immutable brief and allowlisted action manifest. Values and content below are displayed exactly as stored.</p></div>
    <section className="iq-panel"><h3>Recommendation</h3><Exact value={brief.recommendation} />{brief.alternatives.length > 0 && <><h4>Recorded alternatives</h4><Exact value={brief.alternatives} /></>}</section>
    <section className="iq-panel"><div className="iq-section-title"><h3>Pricing and authority calculations</h3><Badge appearance="tint" color="informative">Deterministic tools</Badge></div>
      <p className="iq-muted">The browser performs no financial arithmetic or authority checks.</p>
      {brief.calculations.map(calculation => <article className="iq-subsection" key={calculation.calculation_id}><h4>{calculation.tool_name} <span className="iq-muted">v{calculation.tool_version}</span></h4><div className="iq-two-column"><div><h5>Exact inputs</h5><Exact value={calculation.inputs} /></div><div><h5>Authoritative outputs</h5><Exact value={calculation.outputs} /></div></div></article>)}
    </section>
    <section className="iq-panel"><h3>Policy checks</h3>{brief.policy_checks.map(check => <article className="iq-policy" key={check.check_id}><div className="iq-section-title"><h4>{check.rule_id} · v{check.rule_version}</h4><Badge appearance="tint" color={check.verdict === 'pass' ? 'success' : check.verdict === 'fail' ? 'danger' : 'warning'}>{readable(check.verdict)}</Badge></div><p>{check.explanation}</p><p className="iq-muted">Required scenario role: {check.required_scenario_role ?? 'Not specified'}</p><details className="iq-raw"><summary>Exact policy record and evidence links</summary><Exact value={check} /></details></article>)}</section>
    <section className="iq-panel"><h3>Material claims and evidence gaps</h3>{brief.evidence_gaps.length > 0 ? <div className="iq-alert"><h4>Recorded gaps</h4><Exact value={brief.evidence_gaps} /></div> : <p className="iq-muted">No evidence gaps are recorded in this brief. This does not replace the controller’s checks.</p>}<details className="iq-raw"><summary>Exact material claims and evidence IDs</summary><Exact value={brief.material_claims} /></details></section>
    <section className="iq-panel"><div className="iq-section-title"><h3>Exact proposed actions</h3><Badge appearance="outline">No write controls</Badge></div><p className="iq-muted">These parameters and contents belong to the envelope hash above. Viewing them grants no authorization and executes nothing.</p>
      {envelope.action_manifest.actions.map(action => <article className="iq-action" key={action.action_id}>
        <h4>{readable(action.action_type)}</h4><dl className="iq-facts"><div><dt>Action ID</dt><dd className="iq-mono">{action.action_id}</dd></div><div><dt>Artifact SHA-256</dt><dd className="iq-mono">{action.artifact_hash}</dd></div><div><dt>Idempotency key</dt><dd className="iq-mono">{action.idempotency_key}</dd></div></dl>
        {action.action_type === 'graph.send_mail' && action.parameters.content_type === 'HTML' && typeof action.parameters.content === 'string' && <EmailPreview content={action.parameters.content} />}
        <details><summary>Exact action parameters and content</summary><Exact value={action.parameters} />{typeof action.parameters.content === 'string' && <><h5>Exact content · source text</h5><Exact value={action.parameters.content} /></>}</details>
      </article>)}
    </section>
    <details className="iq-panel"><summary>Complete immutable envelope · exact JSON values</summary><p className="iq-muted">Pretty-printed for inspection; not a browser-generated canonical hash representation.</p><Exact value={envelope} /></details>
    {record.approval && <details className="iq-panel"><summary>Complete recorded human decision</summary><Exact value={record.approval} /></details>}
  </div>;
}

function Timeline({ events }: { events: RunEvent[] }) {
  return <section className="iq-panel"><div className="iq-section-title"><h3>Run Events</h3><Badge appearance="outline">Controller audit trail</Badge></div><p className="iq-muted">Ordered by stored sequence. Times are shown in your browser’s local time zone. Refresh to fetch a new snapshot.</p>
    {events.length === 0 ? <Empty title="No events returned">No audit events were returned for this Run.</Empty> : <ol className="iq-timeline">{[...events].sort((a, b) => a.sequence - b.sequence).map(event => <li key={event.event_id}><span className="iq-event-sequence" aria-label={`Sequence ${event.sequence}`}>{event.sequence}</span><div className="iq-event-content"><div className="iq-section-title"><h4>{readable(event.event_type)}</h4><Status state={event.state} /></div><time dateTime={event.occurred_at}>{timestamp(event.occurred_at)}</time><p className="iq-muted iq-mono">Actor: {event.actor_user_id}</p><details className="iq-raw"><summary>Event details and correlation</summary><Exact value={{ event_id: event.event_id, correlation_id: event.correlation_id, details: event.details }} /></details></div></li>)}</ol>}
  </section>;
}

export function ControlRoom({ api, accountName, onSignOut, operationsApi }: ControlRoomProps) {
  const [linked] = useState(() => parseDecisionLink(window.location.search));
  const [epoch, setEpoch] = useState(0);
  const [list, setList] = useState<RunList | null>(null);
  const [listError, setListError] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [detailError, setDetailError] = useState(false);
  const [query, setQuery] = useState('');
  const [stateFilter, setStateFilter] = useState('all');
  const [view, setView] = useState<View>(linked && !('invalid' in linked) ? 'decision' : 'overview');
  const filterId = useId();
  const searchId = useId();
  const tabPanelId = useId();

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setList(null); setListError(false);
    if (linked && 'invalid' in linked) { setListError(true); return () => controller.abort(); }
    void api.listRuns(controller.signal).then(records => {
      if (!active) return;
      if (linked && !('invalid' in linked) && !records.some(record => record.run.run_id === linked.run)) throw new Error('Linked Run unavailable');
      setList({ account: accountName, api, epoch, records });
      setSelectedId(current => records.some(record => record.run.run_id === current) ? current : linked && !('invalid' in linked) ? linked.run : records[0]?.run.run_id ?? null);
    }).catch(() => {
      if (!active) return;
      setList(null); setSelectedId(null); setSnapshot(null); setListError(true);
    });
    return () => { active = false; controller.abort(); };
  }, [api, accountName, epoch, linked]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setSnapshot(null); setDetailError(false);
    if (selectedId && list?.account === accountName && list.api === api && list.epoch === epoch && list.records.some(record => record.run.run_id === selectedId)) {
      void Promise.all([api.getRun(selectedId, controller.signal), api.getEvents(selectedId, controller.signal)]).then(([record, events]) => {
        if (!active) return;
        if (record.run.run_id !== selectedId || events.some(event => event.run_id !== selectedId || event.correlation_id !== record.run.correlation_id)) throw new Error('Run identity mismatch');
        const snapshotEvents = events.filter(event => event.sequence <= record.revision).sort((left, right) => left.sequence - right.sequence);
        if (snapshotEvents.length !== record.revision || snapshotEvents.some((event, index) => event.sequence !== index + 1)) throw new Error('Audit snapshot incomplete');
        setSnapshot({ id: selectedId, account: accountName, api, epoch, record, events: snapshotEvents });
      }).catch(() => {
        if (!active) return;
        setSnapshot(null); setDetailError(true);
      });
    }
    return () => { active = false; controller.abort(); };
  }, [api, accountName, selectedId, epoch, list]);

  const records = list?.account === accountName && list.api === api && list.epoch === epoch ? list.records : [];
  const current = snapshot?.id === selectedId && snapshot.account === accountName && snapshot.api === api && snapshot.epoch === epoch ? snapshot : null;
  const linkMismatch = current && linked && !('invalid' in linked) && selectedId === linked.run &&
    (current.record.envelope?.brief_hash !== linked.hash || current.record.envelope?.brief.brief_version !== linked.version ||
     current.record.run.current_brief_hash !== linked.hash || current.record.run.current_brief_version !== linked.version);
  const visible = records.filter(record => (stateFilter === 'all' || record.run.state === stateFilter) && `${record.run.run_id} ${record.run.contract_id} ${record.facts?.customer_name ?? ''}`.toLowerCase().includes(query.trim().toLowerCase()));
  const states = [...new Set(records.map(record => record.run.state))].sort();
  const refreshing = !list && !listError;

  return <div className="iq-app">
    <a className="iq-skip" href="#iq-main">Skip to Control Room</a>
    <aside className="iq-rail" aria-label="Product navigation"><a href="#iq-main" className="iq-brand" aria-label="InnexQ Control Room"><span className="iq-brand-symbol" aria-hidden="true">iQ</span><span>Innex<span className="iq-brand-q">Q</span></span></a><div className="iq-rail-label">WORKSPACE</div><div className="iq-rail-current"><span aria-hidden="true">▦</span> Control Room</div><div className="iq-rail-pack"><span className="iq-rail-label">WORKFLOW PACKS</span><strong>Contract Renewal</strong>{operationsApi && <strong>Certificate Fulfilment</strong>}<span>Governed from evidence<br />to execution.</span></div><div className="iq-rail-footer"><span className="iq-security-dot" aria-hidden="true" />Read-only workspace</div></aside>
    <div className="iq-workspace"><header className="iq-topbar"><span className="iq-breadcrumb">InnexQ <span aria-hidden="true">/</span> Control Room</span><div className="iq-account"><span title={accountName}>{accountName}</span><Button appearance="subtle" size="small" onClick={onSignOut}>Sign out</Button></div></header>
      <main id="iq-main" className="iq-main" tabIndex={-1}>
        <div className="iq-page-heading"><div><div className="iq-eyebrow">GOVERNED ENTERPRISE WORKFLOWS</div><h1>Control Room<span className="iq-heading-dot">.</span></h1><p>See the evidence. Understand the decision. Trace every action.</p></div><Button appearance="primary" onClick={() => setEpoch(value => value + 1)} disabled={refreshing}>Refresh Runs</Button></div>
        <div className="iq-demo-note"><Badge appearance="tint" color="warning">Synthetic demo</Badge><span>Fictional business data · real audit trail. Authorization stays in Teams; this workspace only reads.</span></div>
        <div className="iq-boundaries" aria-label="Governance boundaries"><span><b>01</b> Agent proposes</span><span><b>02</b> Code validates</span><span><b>03</b> Human authorizes</span><span><b>04</b> Executor writes</span></div>
        {operationsApi && !linked && <CertificateCases api={operationsApi} accountName={accountName} refreshEpoch={epoch} />}
        <div className="iq-room-layout">
          <section className="iq-run-browser" aria-labelledby="iq-runs-heading"><div className="iq-run-browser-heading"><h2 id="iq-runs-heading">Runs</h2><span className="iq-muted">{records.length} returned</span></div><div className="iq-filters"><label htmlFor={searchId}>Find a Run</label><Input id={searchId} placeholder="Contract, customer or Run ID" value={query} onChange={(_, data) => setQuery(data.value)} /><label htmlFor={filterId}>State</label><Select id={filterId} value={stateFilter} onChange={event => setStateFilter(event.target.value)}><option value="all">All states</option>{states.map(state => <option value={state} key={state}>{readable(state)}</option>)}</Select></div>
            {listError ? <div className="iq-list-message" role="alert"><h3>Runs could not be loaded</h3><p>No previous data is shown. Refresh to retry; if your session has expired, sign out and sign in again.</p></div> : refreshing ? <div className="iq-list-message" role="status"><Spinner size="small" label="Loading Runs" /></div> : visible.length === 0 ? <div className="iq-list-message"><h3>{records.length ? 'No matching Runs' : 'No Runs available'}</h3><p>{records.length ? 'Try another search or state filter.' : 'Runs visible to your signed-in account will appear here.'}</p></div> : <ul className="iq-run-list">{visible.map(record => <li key={record.run.run_id}><button type="button" className={`iq-run-option ${selectedId === record.run.run_id ? 'is-selected' : ''}`} aria-pressed={selectedId === record.run.run_id} onClick={() => { setSelectedId(record.run.run_id); setView('overview'); }}><span className="iq-run-option-title">{record.facts?.customer_name ?? record.run.contract_id}</span><span className="iq-run-contract">{record.run.contract_id}</span><Status state={record.run.state} /><span className="iq-run-option-footer"><span className="iq-mono" title={record.run.run_id}>{record.run.run_id.slice(0, 8)}</span><time dateTime={record.run.updated_at}>{timestamp(record.run.updated_at)}</time></span></button></li>)}</ul>}
          </section>
          <section className="iq-run-detail" aria-label="Selected Run" aria-busy={Boolean(selectedId && !current && !detailError)}>
            {linkMismatch ? <div className="iq-panel iq-alert" role="alert"><h2>This decision link is stale</h2><p>The stored version or hash does not match this card. Do not approve it. Request the current decision package; no different brief is substituted here.</p></div> : selectedId && detailError ? <div className="iq-panel iq-alert" role="alert"><h2>Run details could not be loaded</h2><p>No previous Run details are shown. Refresh to retry. This view never changes authorization or repeats execution.</p></div> : selectedId && !current ? <div className="iq-panel iq-loading" role="status"><Spinner label="Loading Run and audit trail" /></div> : current ? <>
              <div className="iq-detail-heading"><div><div className="iq-eyebrow">CONTRACT RENEWAL</div><h2>{current.record.facts?.customer_name ?? current.record.run.contract_id}</h2><p className="iq-mono iq-run-full-id">{current.record.run.run_id}</p></div><Status state={current.record.run.state} /></div>
              <EnvelopeIdentity record={current.record} />
              <TabList className="iq-tabs" selectedValue={view} onTabSelect={(_, data) => { if (data.value === 'overview' || data.value === 'evidence' || data.value === 'decision' || data.value === 'timeline') setView(data.value); }} aria-label="Run inspection"><Tab id={`${tabPanelId}-overview`} value="overview" aria-controls={tabPanelId}>Overview</Tab><Tab id={`${tabPanelId}-evidence`} value="evidence" aria-controls={tabPanelId}>Evidence</Tab><Tab id={`${tabPanelId}-decision`} value="decision" aria-controls={tabPanelId}>Decision brief</Tab><Tab id={`${tabPanelId}-timeline`} value="timeline" aria-controls={tabPanelId}>Timeline</Tab></TabList>
              <div id={tabPanelId} role="tabpanel" aria-labelledby={`${tabPanelId}-${view}`} tabIndex={0}>{view === 'overview' ? <Overview record={current.record} /> : view === 'evidence' ? <Evidence record={current.record} /> : view === 'decision' ? <DecisionView record={current.record} /> : <Timeline events={current.events} />}</div>
            </> : <div className="iq-panel"><Empty title="Select a Run">Inspect its evidence, immutable decision brief, human authorization and execution receipts.</Empty></div>}
          </section>
        </div>
        <footer className="iq-page-footer">InnexQ · Governed enterprise workflows<span>Read-only snapshot · Refresh for the latest controller state</span></footer>
      </main>
    </div>
  </div>;
}

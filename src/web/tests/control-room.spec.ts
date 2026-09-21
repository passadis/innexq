/** Offline component-only browser harness. Never included in the production build. */
import { test, expect } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { resolve } from 'node:path';

test.use({ browserName: 'chromium', channel: 'msedge', reducedMotion: 'reduce' });

const id = '11111111-1111-4111-8111-111111111111';
const at = '2026-09-08T18:00:00Z';
const hash = 'a'.repeat(64);
const demo = {
  run: { run_id: id, contract_id: 'FABRIKAM-SYNTHETIC-001', state: 'EXECUTED', current_brief_version: 1, current_brief_hash: hash, created_at: at, updated_at: at, correlation_id: id },
  workflow_pack: 'contract-renewal', revision: 4, facts: { customer_name: 'Fabrikam · synthetic test', annual_value: '100000.00', currency: 'EUR' },
  proposal: { summary: 'Synthetic contract evidence supports preparing a renewal decision for human review.', citations: [] },
  evidence: [{ evidence_id: id, source_kind: 'foundry_iq', source_name: 'Fabrikam synthetic contract', source_locator: 'https://example.test/synthetic-contract', excerpt: 'SYNTHETIC TEST EVIDENCE\nFabrikam holds a Gold service contract. The workflow prepares a source-grounded renewal proposal; an authorized human must approve the exact decision envelope before execution.', retrieved_at: at, actor_context: { actor_user_id: 'test-retrieval-identity', tenant_id: 'test-tenant', authorization_mode: 'workload_identity' }, supports_claim_ids: [id], classification: 'internal' }],
  envelope: {
    brief_hash: hash,
    brief: { run_id: id, brief_version: 1, recommendation: { option_id: 'renewal', term_months: 12, service_level: 'Gold', summary: 'Synthetic source-grounded recommendation.' }, alternatives: [], material_claims: [{ claim_id: id, text: 'Synthetic claim', evidence_ids: [id] }], calculations: [{ calculation_id: id, tool_name: 'pricing-authority', tool_version: '1.0', inputs: { annual_value: '100000.00', discount_percent: '8' }, outputs: { discounted_annual_value: '92000.00', currency: 'EUR' } }], policy_checks: [{ check_id: id, rule_id: 'discount-authority', rule_version: '1.0', verdict: 'pass', evidence_ids: [id], required_scenario_role: 'account_manager', explanation: 'Verified human approval is still required.' }], evidence_gaps: [], action_manifest_id: id, presentation: { plain_language_summary: 'Synthetic contract evidence supports preparing a renewal decision for human review.', detailed_summary: 'Exact synthetic draft', customer_language_drafts: { 'en-GB': 'Exact synthetic draft' } } },
    action_manifest: { manifest_id: id, run_id: id, brief_version: 1, actions: [
      { action_id: 'file-action', action_type: 'sharepoint.create_file', parameters: { drive_id: 'test-drive', folder_id: 'test-folder', filename: 'synthetic-renewal.txt', content: 'SYNTHETIC TEST FILE\nExact approved content.' }, artifact_hash: hash, idempotency_key: `${id}:file:v1` },
      { action_id: 'mail-action', action_type: 'graph.send_mail', parameters: { sender: 'sender@example.test', recipient: 'recipient@example.test', subject: 'Synthetic test', content: 'SYNTHETIC TEST EMAIL\nExact approved content.' }, artifact_hash: hash, idempotency_key: `${id}:mail:v1` },
    ] },
  },
  approval: { actor_user_id: 'test-authorized-human', decision: 'approve', submitted_at: at, brief_version: 1, brief_hash: hash, authority_result: { verdict: 'authorized', actor_scenario_role: 'account_manager' } },
  action_status: { [`${id}:file:v1`]: 'completed', [`${id}:mail:v1`]: 'completed' },
  receipts: { [`${id}:file:v1`]: 'test-sharepoint-file-id', [`${id}:mail:v1`]: 'accepted:test-request-id' },
};
const events = ['run.detected', 'policy.verified', 'approval.recorded', 'execution.completed'].map((event_type, index) => ({ event_id: `test-event-${index}`, run_id: id, correlation_id: id, sequence: index + 1, event_type, state: index === 3 ? 'EXECUTED' : 'POLICY_VERIFIED', occurred_at: at, actor_user_id: 'test-controller', details: { environment: 'offline-browser-test' } }));

let server: ViteDevServer;
let origin: string;
test.beforeAll(async () => {
  const virtualId = 'virtual:innexq-offline-control-room';
  server = await createServer({
    configFile: false,
    root: resolve(import.meta.dirname, '..'),
    server: { host: '127.0.0.1', port: 0 },
    plugins: [{ name: 'offline-control-room-test',
      resolveId(source) { return source === virtualId ? `\0${virtualId}` : null; },
      load(source) {
        if (source !== `\0${virtualId}`) return null;
        return `import React from 'react'; import { createRoot } from 'react-dom/client'; import { FluentProvider, webLightTheme } from '@fluentui/react-components'; import { ControlRoom } from '/src/ControlRoom.tsx'; const record=${JSON.stringify(demo)}; const events=${JSON.stringify(events)}; const api={listRuns:async()=>[record],getRun:async()=>record,getEvents:async()=>events}; createRoot(document.getElementById('root')).render(React.createElement(FluentProvider,{theme:webLightTheme},React.createElement(ControlRoom,{api,accountName:'Offline test reader',onSignOut:()=>{}})));`;
      },
      configureServer(vite) { vite.middlewares.use((request, response, next) => {
        if (request.url !== '/__test/control-room') return next();
        response.setHeader('Content-Type', 'text/html');
        response.end(`<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>InnexQ offline test only</title></head><body><div id="root"></div><script type="module" src="/@id/${virtualId}"></script></body></html>`);
      }); },
    }],
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Test server address unavailable');
  origin = `http://127.0.0.1:${address.port}`;
});
test.afterAll(async () => { await server?.close(); });

test('desktop and mobile read-only inspection without authentication or external requests', async ({ page }, testInfo) => {
  const errors: string[] = [];
  const externalRequests: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (!request.url().startsWith(origin)) externalRequests.push(request.url()); });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.goto(`${origin}/__test/control-room`);
  await expect(page.getByRole('heading', { name: 'Decision summary' })).toBeVisible();
  await expect(page.getByText('accepted:test-request-id', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /^approve$|^execute$|^reset$/i })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('control-room-desktop.png'), fullPage: true });
  await page.getByRole('tab', { name: 'Evidence' }).click();
  await expect(page.getByText('Exact evidence excerpt')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('control-room-evidence.png'), fullPage: true });
  await page.getByRole('tab', { name: 'Evidence' }).focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Exact proposed actions' })).toBeVisible();
  await page.getByRole('tab', { name: 'Timeline' }).click();
  await expect(page.getByRole('heading', { name: 'Run Events' })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('tab', { name: 'Overview' }).click();
  await page.screenshot({ path: testInfo.outputPath('control-room-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(externalRequests).toEqual([]);
  expect(errors).toEqual([]);
});

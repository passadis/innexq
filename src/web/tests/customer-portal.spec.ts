/** Offline browser-only harness. Mock token and intercepted API; never included in production. */
import { test, expect, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { resolve } from 'node:path';

test.use({ browserName: 'chromium', channel: 'msedge', reducedMotion: 'reduce' });
const apiOrigin = 'https://api.offline.azurecontainerapps.io';
const customerConfig = { tenantId: '35de4c50-7dcd-4871-8685-61789c017da2', clientId: '11111111-1111-4111-8111-111111111111', apiOrigin, apiScope: 'api://11111111-1111-4111-8111-111111111111/Certificates.Request' };
const id = '22222222-2222-4222-8222-222222222222';
const otherId = '33333333-3333-4333-8333-333333333333';
const preset = 'Please provide the existing certificate for DEMO-PT-001.';
const catalog = { customer_name: 'Fabrikam · offline synthetic test', equipment: [{ equipment_id: 'DEMO-PT-001', name: 'Electric pallet carrier', serial_number: 'DEMO-SERIAL-0001' }, { equipment_id: 'DEMO-PT-002', name: 'Warehouse pallet carrier', serial_number: 'DEMO-SERIAL-0002' }], presets: [{ equipment_id: 'DEMO-PT-001', prompt: preset }, { equipment_id: 'DEMO-PT-002', prompt: 'Please send the certificate for DEMO-PT-002.' }] };
const pdfBytes = Buffer.from('%PDF-1.7\n% OFFLINE BROWSER DOWNLOAD FIXTURE ONLY - NOT A VALID CERTIFICATE\n%%EOF\n');
const operationsCase = {
  record: { workflow_pack: 'certificate_fulfilment', request_id: id, customer_id: 'DEMO-FAB', equipment_id: 'DEMO-PT-002', decision_hash: 'a'.repeat(64), operations_case: { case_id: otherId, assigned_user_id: customerConfig.clientId, reason_codes: ['service_not_current'], state: 'open' },
    decision: { outcome: 'operations_required', policy_id: 'CERT-RELEASE-001', policy_version: 1, evaluated_at: '2026-09-11T00:00:00Z', checks: [{ name: 'ownership', verdict: 'pass', reason: 'passed' }, { name: 'certificate_validity', verdict: 'pass', reason: 'passed' }, { name: 'service_status', verdict: 'fail', reason: 'service_not_current' }], sources: { investigation: { request_id: id, extraction_api: '2024-11-30', extraction_model: 'prebuilt-layout',
      fields: [{ document_id: 'DEMO-PT-002-SERVICE-PDF', document_version: 'offline-v1', sha256: 'b'.repeat(64), label: 'Service valid until', value: '2026-09-10 · offline synthetic source text', page: 2, polygon: [0, 0, 1, 0, 1, 1, 0, 1] }],
      specialists: [{ specialist: 'request_coordinator', response_id: 'offline-response-coordinator', summary: 'Offline fixture: the customer requested the existing equipment certificate.' }, { specialist: 'document_analyst', response_id: 'offline-response-document', summary: 'Offline fixture: the cited service report records the service validity date on page 2.' }, { specialist: 'equipment_service', response_id: 'offline-response-equipment', summary: 'Offline fixture: the service period has ended. Operations investigation is needed; this summary grants no release authority.' }],
    } } },
  }, notification: { state: 'delivered', receipt_id: 'offline-teams-acceptance-fixture' },
};

let server: ViteDevServer;
let origin: string;
test.beforeAll(async () => {
  const virtualId = 'virtual:innexq-offline-customer-portal';
  server = await createServer({ configFile: false, root: resolve(import.meta.dirname, '..'), server: { host: '127.0.0.1', port: 0 }, plugins: [{ name: 'offline-customer-portal-test',
    resolveId(source) { return source === virtualId ? `\0${virtualId}` : null; },
    load(source) {
      if (source !== `\0${virtualId}`) return null;
      return `import React from 'react'; import { createRoot } from 'react-dom/client'; import { CustomerPortal } from '/src/CustomerPortal.tsx'; import { OperationsInbox } from '/src/OperationsInbox.tsx'; import { CertificateCases } from '/src/CertificateCases.tsx'; import { createCustomerApi } from '/src/customer-api.ts'; import { createOperationsApi } from '/src/operations-api.ts'; import { createCaseReviewApi } from '/src/case-review-api.ts'; import '/src/control-room.css';
        const config=${JSON.stringify(customerConfig)}; const token=async()=> 'offline-test-token-not-a-real-credential'; const overview=window.location.pathname.endsWith('/overview'); const ops=overview||window.location.pathname.endsWith('/operations')||window.location.pathname.endsWith('/operations-review');
        const api=ops?createOperationsApi({...config,apiScope:config.apiScope.replace('Certificates.Request','Runs.Read')},token):createCustomerApi(config,token);
        const reviewApi = window.location.pathname.endsWith('/operations-review') ? createCaseReviewApi({...config,apiScope:config.apiScope.replace('Certificates.Request','Runs.Read')},token,token) : undefined;
        createRoot(document.getElementById('root')).render(React.createElement(overview?CertificateCases:ops?OperationsInbox:CustomerPortal,{api,reviewApi,accountName:'Offline test account',onSignOut:()=>{}}));`;
    },
    configureServer(vite) { vite.middlewares.use((request, response, next) => {
      if (!['/__test/customer', '/__test/operations', '/__test/operations-review', '/__test/overview'].includes(request.url?.split('?')[0] ?? '')) return next();
      response.setHeader('Content-Type', 'text/html');
      response.end(`<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>InnexQ offline browser fixture only</title></head><body><div id="root"></div><script type="module" src="/@id/${virtualId}"></script></body></html>`);
    }); },
  }] });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Offline test address unavailable');
  origin = `http://127.0.0.1:${address.port}`;
});
test.afterAll(async () => { await server?.close(); });
test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus) {
    console.error('Offline rendered page:', await page.locator('body').innerText());
    await page.screenshot({ path: testInfo.outputPath('failure.png'), fullPage: true });
  }
});

test('certificate overview is readable on desktop/mobile and links only the returned case', async ({ page }, testInfo) => {
  const observations = await offlineApi(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${origin}/__test/overview`);
  const link = page.getByRole('link', { name: 'Inspect DEMO-PT-002' });
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute('href', `/?operations=${id}`);
  await expect(page.getByText(/not successful certificate downloads/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('certificate-overview-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(link).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('certificate-overview-mobile.png'), fullPage: true });
  await page.getByRole('searchbox', { name: 'Find a certificate case' }).fill('missing');
  await expect(page.getByText('No matching certificate cases.')).toBeVisible();
  expect(observations.requests.every(item => item.method === 'GET')).toBe(true);
  expect(observations.blockedExternal).toEqual([]);
  expect(observations.errors).toEqual([]);
});

async function offlineApi(page: Page, cases = [operationsCase], manager = false) {
  let review = { schema_version: '1.0', request_id: id, tenant_id: customerConfig.tenantId, case_id: otherId, assigned_user_id: customerConfig.clientId, decision_hash: 'a'.repeat(64), revision: 0, state: 'open', events: [] as unknown[] };
  const submissions: { request_id: string; equipment_id: string; prompt: string }[] = [];
  const messages: { message_id: string; equipment_id: string | null; prompt: string }[] = [];
  const requests: { method: string; path: string }[] = [];
  const blockedExternal: string[] = [], errors: string[] = [];
  page.on('pageerror', error => { errors.push(error.message); console.error('Offline browser error:', error.message); });
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin === origin) return route.continue();
    if (url.origin !== apiOrigin) { blockedExternal.push(url.origin); return route.abort('blockedbyclient'); }
    const cors = { 'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Headers': 'Authorization, Content-Type', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS' };
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    expect(request.headers().authorization).toBe('Bearer offline-test-token-not-a-real-credential');
    requests.push({ method: request.method(), path: url.pathname });
    let body: unknown;
    if (url.pathname === '/api/customer/catalog') body = catalog;
    else if (url.pathname === '/api/customer/messages' && request.method() === 'POST') {
      const input = request.postDataJSON(); messages.push(input);
      const inquiry = input.prompt.startsWith('Is the service');
      const equipment = input.equipment_id || 'DEMO-PT-001';
      body = { message_id: input.message_id, equipment_id: equipment, intent: inquiry ? 'service_status' : 'certificate_request', kind: inquiry ? 'answer' : 'confirmation_required', can_confirm: !inquiry,
        message: inquiry ? 'Offline fixture: recorded service is current. No service booking or certificate request was created.' : `Request the existing certificate for ${equipment}?`,
        as_of: inquiry ? '2026-09-17T12:00:00Z' : null,
        citations: inquiry ? [{ document_id: 'DEMO-PT-001-SERVICE-PDF', document_version: 'offline-v1', page: 1, label: 'Valid until', value: '2026-12-10' }] : [] };
    } else if (/^\/api\/customer\/messages\/[0-9a-f-]+\/confirm$/.test(url.pathname) && request.method() === 'POST') {
      const proposal = messages.find(item => item.message_id === url.pathname.split('/').at(-2));
      expect(proposal).toBeDefined(); expect(request.postDataJSON()).toEqual({});
      const input = { request_id: proposal!.message_id, equipment_id: proposal!.equipment_id || 'DEMO-PT-001', prompt: proposal!.prompt }; submissions.push(input);
      body = { request_id: input.request_id, status: input.equipment_id === 'DEMO-PT-001' ? 'release_ready' : 'operations_required', message: 'Offline fixture result.' };
    } else if (/^\/api\/customer\/requests\/[0-9a-f-]+\/pdf$/.test(url.pathname)) return route.fulfill({ status: 200, headers: { ...cors, 'Content-Type': 'application/pdf' }, body: pdfBytes });
    else if (/^\/api\/customer\/requests\/[0-9a-f-]+$/.test(url.pathname)) {
      const input = submissions.find(item => item.request_id === url.pathname.split('/').at(-1));
      body = { request_id: input?.request_id, status: input?.equipment_id === 'DEMO-PT-001' ? 'release_ready' : 'operations_required', message: 'Offline stored status.' };
    } else if (url.pathname === '/api/operations/certificates') body = cases;
    else if (url.pathname === `/api/operations/certificates/${id}/review`) body = { review, can_manage: !manager };
    else if (url.pathname === `/api/operations/certificates/${id}/actions` && request.method() === 'POST') {
      expect(manager).toBe(false);
      const command = request.postDataJSON(); expect(command.expected_revision).toBe(review.revision);
      expect(command.case_id).toBe(otherId); expect(command.decision_hash).toBe(review.decision_hash);
      review = { ...review, revision: review.revision + 1, state: command.action === 'close_without_release' ? 'closed_without_release' : command.action === 'acknowledge' ? 'acknowledged' : review.state,
        events: [...review.events, { sequence: review.revision + 1, actor_user_id: customerConfig.clientId, occurred_at: '2026-09-15T00:00:00Z', command }] };
      body = review;
    }
    else throw new Error(`Unexpected offline request: ${url.pathname}`);
    return route.fulfill({ status: 200, headers: { ...cors, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  });
  return { messages, submissions, requests, blockedExternal, errors };
}

test('Operations can acknowledge, add a note and close without release on mobile', async ({ page }, testInfo) => {
  const observations = await offlineApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${origin}/__test/operations-review?operations=${id}`);
  await page.getByRole('button', { name: 'Acknowledge', exact: true }).click();
  await expect(page.getByText('Acknowledged', { exact: true })).toBeVisible();
  await page.getByLabel('Internal note or closure reason').fill('Offline test: service evidence needs investigation.');
  await page.getByRole('button', { name: 'Add internal note', exact: true }).click();
  await expect(page.getByText('Offline test: service evidence needs investigation.', { exact: true })).toBeVisible();
  await page.getByLabel('Internal note or closure reason').fill('Offline test: closed without a PDF release.');
  await page.getByRole('button', { name: 'Close without release', exact: true }).click();
  await expect(page.getByText('Closed without release', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Acknowledge', exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('case-review-closed-mobile.png'), fullPage: true });
  expect(observations.requests.filter(item => item.method === 'POST')).toHaveLength(3);
  expect(observations.requests.some(item => item.path.endsWith('/pdf'))).toBe(false);
  expect(observations.blockedExternal).toEqual([]); expect(observations.errors).toEqual([]);
});

test('Manager reads the linked held case with no write controls', async ({ page }, testInfo) => {
  const observations = await offlineApi(page, [operationsCase], true);
  await page.goto(`${origin}/__test/operations-review?operations=${id}`);
  await expect(page.getByText(/Manager · Read-only/)).toBeVisible();
  await expect(page.getByRole('button', { name: /acknowledge|add internal note|close without release/i })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('case-review-manager-desktop.png'), fullPage: true });
  expect(observations.requests.every(item => item.method === 'GET')).toBe(true);
  expect(observations.blockedExternal).toEqual([]); expect(observations.errors).toEqual([]);
});

test('customer desktop/mobile preset and typed requests use the real client endpoint, status and Blob download offline', async ({ page }, testInfo) => {
  const observations = await offlineApi(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${origin}/__test/customer`);
  await expect(page.getByRole('heading', { name: catalog.customer_name })).toBeVisible();
  await expect(page.getByRole('combobox')).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('customer-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: preset }).click();
  await expect(page.getByRole('textbox')).toHaveValue(preset);
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByRole('button', { name: 'Request this certificate' })).toBeVisible();
  expect(observations.submissions).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('customer-confirmation-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: 'Request this certificate' }).click();
  await expect(page.getByRole('heading', { name: 'Certificate ready' })).toBeVisible();
  await page.getByRole('button', { name: 'Refresh status' }).click();
  await expect(page.getByRole('button', { name: 'Download existing PDF' })).toBeEnabled();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download existing PDF' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^InnexQ-certificate-[0-9a-f-]+\.pdf$/);
  const stream = await download.createReadStream();
  if (!stream) throw new Error('Offline download stream missing');
  const chunks = []; for await (const chunk of stream) chunks.push(chunk);
  expect(Buffer.concat(chunks)).toEqual(pdfBytes);
  await expect(page.getByText(/handed to your browser/)).toBeVisible();
  await expect(page.locator('a[download]')).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('customer-ready-desktop.png'), fullPage: true });
  await page.getByRole('combobox').selectOption('DEMO-PT-002');
  const typed = 'Could you send the existing certificate for my second pallet carrier?';
  await page.getByRole('textbox').fill(typed);
  await page.getByRole('button', { name: 'Send message' }).click();
  await page.getByRole('button', { name: 'Request this certificate' }).click();
  await expect(page.getByRole('heading', { name: 'Operations review needed' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Download existing PDF' })).toHaveCount(0);
  expect(observations.submissions.map(item => item.prompt)).toEqual([preset, typed]);
  expect(observations.submissions[0].request_id).not.toEqual(observations.submissions[1].request_id);
  expect(observations.requests.filter(item => item.method === 'POST').map(item => item.path)).toEqual([
    '/api/customer/messages', `/api/customer/messages/${observations.submissions[0].request_id}/confirm`,
    '/api/customer/messages', `/api/customer/messages/${observations.submissions[1].request_id}/confirm`,
  ]);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.getByRole('link', { name: 'InnexQ Customer Portal' }).evaluate(element => element.getBoundingClientRect().height)).toBeLessThanOrEqual(40);
  await page.screenshot({ path: testInfo.outputPath('customer-held-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(observations.blockedExternal).toEqual([]);
  expect(observations.errors).toEqual([]);
});

test('service inquiry shows dated evidence without creating a certificate request', async ({ page }, testInfo) => {
  const observations = await offlineApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${origin}/__test/customer`);
  await expect(page.getByRole('combobox')).toHaveValue('');
  await page.getByRole('textbox').fill('Is the service for PT-001 updated?');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByText(/Offline fixture: recorded service is current/)).toBeVisible();
  await page.getByText('Evidence used (1)', { exact: true }).click();
  await expect(page.getByText(/offline-v1/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Request this certificate' })).toHaveCount(0);
  expect(observations.submissions).toEqual([]);
  expect(observations.requests.filter(item => item.method === 'POST').map(item => item.path)).toEqual(['/api/customer/messages']);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('customer-service-answer-mobile.png'), fullPage: true });
  expect(observations.blockedExternal).toEqual([]); expect(observations.errors).toEqual([]);
});

test('Operations desktop/mobile renders recorded citations and honest notification status, and never substitutes a missing deep link', async ({ page }, testInfo) => {
  const observations = await offlineApi(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${origin}/__test/operations?operations=${id}`);
  await expect(page.getByRole('heading', { name: 'DEMO-PT-002' })).toBeVisible();
  await expect(page.getByText('Accepted by Teams', { exact: true })).toBeVisible();
  await expect(page.getByText(/not proof that an operator read/)).toBeVisible();
  await expect(page.getByText('Page 2', { exact: true })).toBeVisible();
  await expect(page.getByText('Response: offline-response-document', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /approve|release|execute|send/i })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('operations-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath('operations-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.goto(`${origin}/__test/operations?operations=${otherId}`);
  await expect(page.getByRole('alert')).toContainText('No different case is substituted');
  await expect(page.getByRole('heading', { name: 'DEMO-PT-002' })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('operations-missing-case.png'), fullPage: true });
  expect(observations.requests.every(item => item.method === 'GET')).toBe(true);
  expect(observations.blockedExternal).toEqual([]);
  expect(observations.errors).toEqual([]);
});

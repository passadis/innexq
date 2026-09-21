/** Uses the real Python email renderer and real browser; never sends mail. */
import { test, expect } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

test.use({ browserName: 'chromium', channel: 'msedge' });
let server: ViteDevServer;
let origin: string;
test.beforeAll(async () => {
  const root = resolve(import.meta.dirname, '../../..');
  const python = "import json; from uuid import UUID; from innexq_api.presentation import renewal_email; from innexq_gateway import calculate_pricing; print(json.dumps(renewal_email({'contract_id':'CON-FAB-2025-001','customer_name':'Fabrikam Industrial AB','service_level':'Gold','term_months':'12'},calculate_pricing('180000.00','8'),UUID(int=1),1,'innexq-demo.txt','https://passadisoutlook498.sharepoint.com/sites/InnexQ/InnexQDocs/Output')))";
  const content = JSON.parse(execFileSync('uv', ['run', 'python', '-c', python], { cwd: root, encoding: 'utf8', env: { ...process.env, UV_CACHE_DIR: resolve(root, '.uv-cache') } }));
  const hostile = '<script>window.__previewExecuted=true;parent.document.body.innerHTML="unsafe"</script><img src="https://blocked.example/pixel"><iframe src="https://blocked.example/frame"></iframe><style>body{background-image:url(https://blocked.example/style)}</style>';
  server = await createServer({ configFile: false, root: resolve(import.meta.dirname, '..'), server: { host: '127.0.0.1', port: 0 },
    plugins: [{ name: 'offline-email-preview',
      resolveId(source) { return source === 'virtual:email-preview' ? '\0virtual:email-preview' : null; },
      load(source) {
        if (source !== '\0virtual:email-preview') return null;
        return `import React from 'react';import {createRoot} from 'react-dom/client';import {EmailPreview} from '/src/EmailPreview.tsx';const content=${JSON.stringify(content)}+(location.search?'${hostile}':'');createRoot(document.getElementById('root')).render(React.createElement(EmailPreview,{content}));`;
      },
      configureServer(vite) { vite.middlewares.use((req, res, next) => {
        if (!req.url?.startsWith('/__test/email')) return next();
        res.setHeader('Content-Type', 'text/html');
        res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-src 'self'");
        res.end('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Offline email test</title></head><body><div id="root"></div><script type="module" src="/@id/virtual:email-preview"></script></body></html>');
      }); },
    }],
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('No local test address');
  origin = `http://127.0.0.1:${address.port}`;
});
test.afterAll(async () => { await server?.close(); });

test('real email layout renders on desktop/mobile and the sandbox blocks active content', async ({ page }, info) => {
  const outbound: string[] = [];
  await page.route('https://**', route => { outbound.push(route.request().url()); return route.abort(); });
  await page.setViewportSize({ width: 760, height: 1100 });
  await page.goto(origin + '/__test/email');
  const frame = page.frameLocator('iframe[title="Approved email layout preview"]');
  await expect(frame.getByText('Your renewal summary')).toBeVisible();
  await expect(frame.getByText('EUR 165600.00', { exact: true })).toBeVisible();
  await expect(frame.getByRole('link', { name: 'Open renewal document', includeHidden: true })).toHaveAttribute('href', /sharepoint\.com\/sites\/InnexQ\/InnexQDocs\/Output\/innexq-demo.txt$/);
  await page.screenshot({ path: info.outputPath('email-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 1100 });
  await page.screenshot({ path: info.outputPath('email-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.goto(origin + '/__test/email?hostile=1');
  await expect(frame.getByText('Your renewal summary')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Email layout preview' })).toBeVisible();
  expect(outbound).toEqual([]);
});

/** Offline seed utility only. No live app dependency, identity, upload or mail. */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { chromium } from '@playwright/test';

const root = resolve(import.meta.dirname, '../../..');
const asOf = process.argv[2];
if (!/^\d{4}-\d{2}-\d{2}$/.test(asOf ?? '')) throw new Error('Supply explicit YYYY-MM-DD seed date');
const packet = JSON.parse(execFileSync('uv', ['run', '--frozen', 'python',
  'scripts/build_enterprise_demo.py', '--as-of', asOf], {
  cwd: root, encoding: 'utf8', maxBuffer: 2_000_000,
  env: { ...process.env, UV_CACHE_DIR: resolve(root, '.uv-cache') },
}));
const base = resolve(root, '.test-artifacts');
await mkdir(base, { recursive: true });
// New directory every time: no overwrite, reset, deletion or accepted artifact mutation.
const output = await mkdtemp(resolve(base, `enterprise-${asOf}-`));
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const manifest = [];
try {
  const context = await browser.newContext({ javaScriptEnabled: false, serviceWorkers: 'block' });
  await context.route('**/*', route => route.abort());
  const page = await context.newPage();
  for (const [index, document] of packet.documents.entries()) {
    if (!/^DEMO-[A-Z0-9-]+\.pdf$/.test(document.filename)) throw new Error('Unsafe filename');
    const target = resolve(output, document.filename);
    if (!target.startsWith(output + sep)) throw new Error('Output escaped seed directory');
    await page.setContent(document.html, { waitUntil: 'load' });
    const text = await page.locator('body').innerText();
    if (!text.includes('SYNTHETIC DEMO - NOT VALID FOR REAL EQUIPMENT')) throw new Error('Missing disclosure');
    const pdf = await page.pdf({ format: 'A4', printBackground: true, preferCSSPageSize: true,
      displayHeaderFooter: true, headerTemplate: '<span></span>',
      footerTemplate: '<div style="font-size:8px;width:100%;text-align:center">SYNTHETIC DEMO - NOT VALID FOR REAL EQUIPMENT | <span class="pageNumber"></span> / <span class="totalPages"></span></div>' });
    if (pdf.subarray(0, 5).toString() !== '%PDF-') throw new Error('Invalid PDF output');
    await writeFile(target, pdf, { flag: 'wx' });
    manifest.push({ filename: document.filename, bytes: pdf.length,
      sha256: createHash('sha256').update(pdf).digest('hex') });
    if (index === 0) {
      await page.setViewportSize({ width: 900, height: 1200 });
      await page.screenshot({ path: resolve(output, 'contract-preview.png'), fullPage: true });
    }
  }
  await writeFile(resolve(output, 'catalog.json'), JSON.stringify(packet.catalog, null, 2) + '\n', { flag: 'wx' });
  await writeFile(resolve(output, 'manifest.json'), JSON.stringify({ as_of: asOf,
    synthetic: true, uploaded: false, approved_for_delivery: false, documents: manifest }, null, 2) + '\n', { flag: 'wx' });
  console.log(JSON.stringify({ output, customers: packet.catalog.customers.length,
    contracts: packet.catalog.contracts.length, equipment: packet.catalog.equipment.length,
    requests: packet.catalog.presets.length, pdfs: manifest.length, uploaded: false }, null, 2));
} finally {
  await browser.close();
}

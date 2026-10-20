// Draws the website's example pictures with the real extension panel.
//
//   PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/capture.mjs
//   python3 site/tools/optimise_images.py
//
// The extension's own code (extension/hover_lite) runs in a browser page with
// chrome.* stubbed the way extension/tests/preview/panel.html stubs it, and each
// invented product in examples.json is delivered to it the way the engine would.
// The pictures are therefore what the panel looks like, not a drawing of it.
// Playwright is not a dependency of this repository; point PLAYWRIGHT_MODULE at
// any copy of it (and CHROMIUM at a browser binary if it cannot find one).
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const out = path.resolve(here, '../assets/examples');
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
const data = JSON.parse(fs.readFileSync(path.join(here, 'examples.json'), 'utf8')).products;
fs.mkdirSync(out, { recursive: true });

const server = http.createServer((req, res) => {
  const file = path.join(root, 'extension', decodeURIComponent(req.url.split('?')[0]));
  if (!file.startsWith(path.join(root, 'extension')) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
  const type = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' }[path.extname(file)] || 'application/octet-stream';
  res.writeHead(200, { 'content-type': type });
  fs.createReadStream(file).pipe(res);
}).listen(0, '127.0.0.1');
await new Promise((resolve) => server.on('listening', resolve));
const base = `http://127.0.0.1:${server.address().port}/tests/preview/panel.html?state=idle&seen`;

const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});

const entryFor = (key) => {
  const p = data[key];
  return { ok: true, listing: { equipment: {} }, result: {
    lookup_id: `example-${key}`, coverage: 'RISKS_FOUND', identity: { model: p.title }, context: {},
    packs: [{ pack_id: p.pack, version: '1.0.0' }], app_route: `result/${key}`,
    app_routes: { result: `result/${key}`, compare: `compare/${key}` },
    subjects: [{ kind: 'product', subject_id: key, label: p.title }],
    claims: p.claims.map((c, i) => ({ claim_id: `${key}-${i}`, pack_id: p.pack, subject_id: key, ...c })),
  } };
};

const quickFor = (key) => {
  const p = data[key];
  return { job_id: 'quick-1', kind: 'quick_look', state: 'succeeded', done: true,
    created_at: new Date(Date.now() - 60000).toISOString(), finished_at: new Date().toISOString(),
    result: { product: p.title, assumed: '', specs: [],
      risks: p.claims.slice(0, 3).map((c) => ({ ...c, sources: c.sources.map((s) => ({ ...s, quote: 'Owners report the same problem after a few months of use.' })) })),
      coverage: { pages_read: 6, pages_relevant: 4, pages_extracted: 3, publishers_read: 4, sources_cited: 5 },
      listing: { url: 'https://example.org/listing' }, evidence_pages: [] } };
};

async function session(scheme, viewport, scale, prepare) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: scale, colorScheme: scheme });
  const page = await context.newPage();
  await page.goto(base);
  await page.waitForTimeout(400);
  await page.addStyleTag({ content: 'html,body{background:transparent!important}' });
  await prepare(page);
  return { page, close: () => context.close() };
}

const stub = (quick) => (page) => page.evaluate((q) => {
  const send = window.chrome.runtime.sendMessage.bind(window.chrome.runtime);
  window.chrome.runtime.sendMessage = (m, cb) => {
    if (m.type === 'RESEARCH_PLANE') return cb({ ok: true, plane: { backend: 'local' } });
    if (m.type === 'AGENTS') return cb({ ok: true, chosen: 'local', agents: [{ id: 'local', label: 'Local agent', kind: 'local' }] });
    if (m.type === 'RESEARCH_PRODUCT') return cb({ ok: true, job: { job_id: 'quick-1', kind: 'quick_look' } });
    if (m.type === 'JOB_STATUS') return cb({ ok: true, job: q });
    return send(m, cb);
  };
}, quick);

const deliver = (page, entry) => page.evaluate((e) => window.__preview.deliver('result', e), entry);
const panel = (page) => page.locator('kriko-panel-host >> .lite-panel');
const hidePage = (page) => page.addStyleTag({ content: '.page{display:none!important}' });
const SIZE = { width: 432, height: 800 };

for (const scheme of ['light', 'dark']) {
  // One panel per product: the list of what is known.
  for (const key of Object.keys(data)) {
    const s = await session(scheme, SIZE, 2, async (page) => { await stub(null)(page); await hidePage(page); });
    await deliver(s.page, entryFor(key));
    await s.page.waitForTimeout(1600);
    await panel(s.page).screenshot({ path: path.join(out, `${key}-${scheme}.png`), omitBackground: true });
    await s.close();
  }
  // One claim opened: what to ask, and the source behind it.
  {
    const s = await session(scheme, SIZE, 2, async (page) => { await stub(null)(page); await hidePage(page); });
    await deliver(s.page, entryFor('laptop'));
    await s.page.waitForTimeout(1600);
    await s.page.locator('kriko-panel-host >> .lite-rc-toggle').first().click();
    await s.page.waitForTimeout(700);
    await panel(s.page).screenshot({ path: path.join(out, `claim-open-${scheme}.png`), omitBackground: true });
    await s.close();
  }
  // A product no catalog knows: research it with your own agent.
  {
    const s = await session(scheme, SIZE, 2, async (page) => { await stub(quickFor('headphones'))(page); await hidePage(page); await page.evaluate(() => { document.title = 'Headphones B · Wireless | Example shop'; }); });
    await s.page.evaluate(() => window.__preview.deliver('result', { ok: false, code: 'UNKNOWN_PRODUCT', productName: 'Headphones B · Wireless' }));
    await s.page.waitForTimeout(700);
    await s.page.locator('kriko-panel-host >> .lite-research-product').click();
    await s.page.waitForTimeout(500);
    await s.page.locator('kriko-panel-host >> .lite-research-start').click();
    await s.page.waitForTimeout(2200);
    await panel(s.page).screenshot({ path: path.join(out, `research-${scheme}.png`), omitBackground: true });
    await s.close();
  }
  // The panel beside a listing.
  {
    const s = await session(scheme, { width: 760, height: 800 }, 2, async (page) => {
      await stub(null)(page);
      await hidePage(page);
      await page.addStyleTag({ content: 'html,body{background:#f3f4f7!important}' });
      await page.evaluate(() => {
        document.title = 'Laptop A · 256 GB | Example shop';
        document.body.insertAdjacentHTML('afterbegin', `
          <div style="height:56px;background:#fff;border-bottom:1px solid #e1e3ea;display:flex;align-items:center;padding:0 28px;gap:22px;font:14px system-ui;color:#5a6070"><b style="color:#1a1f2e;font-size:18px">Example shop</b><span>Laptops</span><span>Phones</span></div>
          <div style="padding:32px 28px;font-family:system-ui;color:#1a1f2e;width:340px">
            <div style="width:300px;height:230px;border-radius:12px;background:linear-gradient(135deg,#dfe3ee,#c4cbdc);display:grid;place-items:center"><div style="width:190px;height:124px;border-radius:8px 8px 4px 4px;background:#8791aa;box-shadow:0 11px 0 -2px #6d7690"></div></div>
            <div style="font-size:26px;font-weight:700;line-height:1.2;margin-top:22px">Laptop A, 14-inch, 16 GB RAM, 256 GB SSD</div>
            <div style="color:#6b7284;margin-top:8px;font-size:15px">Thin and light · up to 3,000 MB/s storage</div>
            <div style="font-size:28px;font-weight:700;color:#b34700;margin:14px 0">£649.00</div>
            <div style="display:inline-block;padding:12px 26px;border-radius:8px;background:#1a1f2e;color:#fff;font-weight:600">Add to basket</div></div>`);
      });
    });
    await deliver(s.page, entryFor('laptop'));
    await s.page.waitForTimeout(1600);
    await s.page.screenshot({ path: path.join(out, `hero-${scheme}.png`) });
    await s.close();
  }
}
await browser.close();
server.close();
console.log('wrote', fs.readdirSync(out).filter((f) => f.endsWith('.png')).length, 'pictures to', out);

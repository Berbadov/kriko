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
const examples = JSON.parse(fs.readFileSync(path.join(here, 'examples.json'), 'utf8'));
const data = examples.products;
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
    app_routes: { result: `result/${key}`, compare: 'compare' },
    subjects: [{ kind: 'product', subject_id: key, label: p.title }],
    claims: p.claims.map((c, i) => ({ claim_id: `${key}-${i}`, pack_id: p.pack, subject_id: key, ...c })),
  } };
};

// A quick look at a product no catalog holds: the first findings, each with the
// words it quotes.
const quickFor = () => {
  const p = examples.research;
  return { job_id: 'quick-1', kind: 'quick_look', state: 'succeeded', done: true,
    created_at: new Date(Date.now() - 60000).toISOString(), finished_at: new Date().toISOString(),
    result: { product: p.title, assumed: '', specs: [],
      risks: p.claims.map((c) => ({ ...c })),
      coverage: { pages_read: 6, pages_relevant: 4, pages_extracted: 3, publishers_read: 3, sources_cited: 3 },
      listing: { url: 'https://example.org/listing' }, evidence_pages: [] } };
};

// The panel's theme is the reader's stored choice, not the browser's, so each
// picture names it. `extra` is more of the preview page's own query string: the
// panel asks for the reader's agents the moment it first needs them, which is
// before any stub made here could answer, so a picture that starts a run asks
// the preview for its.
async function session(scheme, viewport, scale, prepare, extra = '') {
  const context = await browser.newContext({ viewport, deviceScaleFactor: scale, colorScheme: scheme });
  const page = await context.newPage();
  await page.goto(`${base}&theme=${scheme}${extra}`);
  await page.waitForTimeout(400);
  await page.addStyleTag({ content: 'html,body{background:transparent!important}' });
  await prepare(page);
  return { page, close: () => context.close() };
}

// What the worker would answer, for the messages the preview page does not.
// `shortlist` is the app's research queue as the panel reads it; `own` are the
// severities the product on this page would show once it joins.
const stub = ({ quick = null, shortlist = [], own = [] } = {}) => (page) => page.evaluate(({ q, list, mine }) => {
  const send = window.chrome.runtime.sendMessage.bind(window.chrome.runtime);
  window.chrome.runtime.sendMessage = (m, cb) => {
    if (m.type === 'RESEARCH_PLANE') return cb({ ok: true, plane: { backend: 'local' } });
    if (m.type === 'AGENTS') return cb({ ok: true, chosen: 'local', agents: [{ id: 'local', label: 'Local agent', kind: 'local' }] });
    if (m.type === 'RESEARCH_PRODUCT') return cb({ ok: true, job: { job_id: 'quick-1', kind: 'quick_look' } });
    if (m.type === 'JOB_STATUS') return cb({ ok: true, job: q });
    if (m.type === 'COMPARE_LIST') return cb({ ok: true, max: 8, items: list.map((one) => ({ ...one })) });
    if (m.type === 'QUEUE_ADD') {
      if (!list.some((one) => one.url === location.href)) list.unshift({ queue_id: 'q-here', url: location.href, name: m.payload.name, severities: mine });
      return cb({ ok: true, added: true, count: list.length, max: 8 });
    }
    return send(m, cb);
  };
}, { q: quick, list: shortlist, mine: own });

const deliver = (page, entry) => page.evaluate((e) => window.__preview.deliver('result', e), entry);
const panel = (page) => page.locator('kriko-panel-host >> .lite-panel');
const hidePage = (page) => page.addStyleTag({ content: '.page{display:none!important}' });
const SIZE = { width: 432, height: 800 };
const severities = (key) => data[key].claims.map((c) => c.severity);

// A drawn bicycle: the listing beside the panel in hero-*.png is invented too.
const BIKE = `<svg viewBox="0 0 300 190" width="250" xmlns="http://www.w3.org/2000/svg" fill="none" stroke-linecap="round" stroke-linejoin="round">
  <g stroke="#3b4256" stroke-width="7"><circle cx="70" cy="130" r="42"/><circle cx="232" cy="130" r="42"/>
  <path d="M70 130 140 130 118 72 200 66 M200 66 232 130 M118 72 70 130 M118 72 104 72 M200 66 214 50 238 50"/></g>
  <path d="M140 130 205 78" stroke="#8791aa" stroke-width="15"/><circle cx="140" cy="130" r="9" fill="#3b4256" stroke="none"/></svg>`;

for (const scheme of ['light', 'dark']) {
  // One panel per product: the list of what is known.
  for (const key of Object.keys(data)) {
    const s = await session(scheme, SIZE, 2, async (page) => { await stub()(page); await hidePage(page); });
    await deliver(s.page, entryFor(key));
    await s.page.waitForTimeout(1600);
    await panel(s.page).screenshot({ path: path.join(out, `${key}-${scheme}.png`), omitBackground: true });
    await s.close();
  }
  // One claim opened: what to ask, and the source behind it.
  {
    const s = await session(scheme, SIZE, 2, async (page) => { await stub()(page); await hidePage(page); });
    await deliver(s.page, entryFor('ebike'));
    await s.page.waitForTimeout(1600);
    await s.page.locator('kriko-panel-host >> .lite-rc-toggle').first().click();
    await s.page.waitForTimeout(700);
    await panel(s.page).screenshot({ path: path.join(out, `claim-open-${scheme}.png`), omitBackground: true });
    await s.close();
  }
  // Compare: this product joins two others, and each row counts what is known.
  {
    const s = await session(scheme, SIZE, 2, async (page) => {
      await stub({ shortlist: examples.shortlist.map((one) => ({ ...one })), own: severities('ebike') })(page);
      await hidePage(page);
    });
    await deliver(s.page, entryFor('ebike'));
    await s.page.waitForTimeout(1600);
    await s.page.locator('kriko-panel-host >> .lite-compare-add').click();
    await s.page.waitForTimeout(1100);
    await panel(s.page).screenshot({ path: path.join(out, `compare-${scheme}.png`), omitBackground: true });
    await s.close();
  }
  // A product no catalog knows: research it with your own agent.
  {
    const name = examples.research.title;
    const s = await session(scheme, SIZE, 2, async (page) => {
      await stub({ quick: quickFor() })(page);
      await hidePage(page);
      await page.evaluate((n) => { document.title = `${n} | Example shop`; }, name);
    }, '&research=found');
    await s.page.evaluate((n) => window.__preview.deliver('result', { ok: false, code: 'UNKNOWN_PRODUCT', productName: n }), name);
    await s.page.waitForTimeout(700);
    await s.page.locator('kriko-panel-host >> .lite-cta').click();
    await s.page.waitForTimeout(500);
    await s.page.locator('kriko-panel-host >> .lite-research-start').click();
    await s.page.waitForTimeout(2200);
    await panel(s.page).screenshot({ path: path.join(out, `research-${scheme}.png`), omitBackground: true });
    await s.close();
  }
  // The panel beside a listing.
  {
    const s = await session(scheme, { width: 760, height: 800 }, 2, async (page) => {
      await stub()(page);
      await hidePage(page);
      await page.addStyleTag({ content: 'html,body{background:#f3f4f7!important}' });
      await page.evaluate((bike) => {
        document.title = 'E-bike M, 2022 | Example shop';
        document.body.insertAdjacentHTML('afterbegin', `
          <div style="height:56px;background:#fff;border-bottom:1px solid #e1e3ea;display:flex;align-items:center;padding:0 28px;gap:22px;font:14px system-ui;color:#5a6070"><b style="color:#1a1f2e;font-size:18px">Example shop</b><span>Bikes</span><span>Phones</span></div>
          <div style="padding:32px 28px;font-family:system-ui;color:#1a1f2e;width:340px">
            <div style="width:300px;height:230px;border-radius:12px;background:linear-gradient(135deg,#dfe3ee,#c4cbdc);display:grid;place-items:center">${bike}</div>
            <div style="font-size:26px;font-weight:700;line-height:1.2;margin-top:22px">E-bike M, 2022, step-through, 500 Wh battery</div>
            <div style="color:#6b7284;margin-top:8px;font-size:15px">Two years old · 7 speeds · 1,900 km</div>
            <div style="font-size:28px;font-weight:700;color:#b34700;margin:14px 0">£1,150.00</div>
            <div style="display:inline-block;padding:12px 26px;border-radius:8px;background:#1a1f2e;color:#fff;font-weight:600">Contact the seller</div></div>`);
      }, BIKE);
    });
    await deliver(s.page, entryFor('ebike'));
    await s.page.waitForTimeout(1600);
    await s.page.screenshot({ path: path.join(out, `hero-${scheme}.png`) });
    await s.close();
  }
}
await browser.close();
server.close();
console.log('wrote', fs.readdirSync(out).filter((f) => f.endsWith('.png')).length, 'pictures to', out);

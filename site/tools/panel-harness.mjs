// The extension's real panel, in a browser page, fed invented products the way the engine would.
//
// Shared by capture.mjs (the site's example pictures) and capture-guide.mjs (the guide's GIFs).
// The extension's own code (extension/hover_lite) runs in a page with chrome.* stubbed the way
// extension/tests/preview/panel.html stubs it, and each invented product in examples.json is
// delivered to it the way the engine would. What is drawn is what the panel looks like.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
export const examples = JSON.parse(fs.readFileSync(path.join(here, 'examples.json'), 'utf8'));
export const data = examples.products;

/** Serves the extension folder; returns the preview page's address and a way to stop. */
export async function servePanel() {
  const server = http.createServer((req, res) => {
    const file = path.join(root, 'extension', decodeURIComponent(req.url.split('?')[0]));
    if (!file.startsWith(path.join(root, 'extension')) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
    const type = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' }[path.extname(file)] || 'application/octet-stream';
    res.writeHead(200, { 'content-type': type });
    fs.createReadStream(file).pipe(res);
  }).listen(0, '127.0.0.1');
  await new Promise((resolve) => server.on('listening', resolve));
  const base = `http://127.0.0.1:${server.address().port}/tests/preview/panel.html?state=idle&seen`;
  return { base, close: () => server.close() };
}

export const entryFor = (key) => {
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
export const quickFor = () => {
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
// the preview for its. `contextOptions` is for a recording (`initScript` runs in every page before its own).
export async function session(browser, base, scheme, viewport, scale, prepare, extra = '', contextOptions = {}) {
  const { initScript, ...options } = contextOptions;
  const context = await browser.newContext({ viewport, deviceScaleFactor: scale, colorScheme: scheme, ...options });
  if (initScript) await context.addInitScript(initScript);
  const page = await context.newPage();
  await page.goto(`${base}&theme=${scheme}${extra}`);
  await page.waitForTimeout(400);
  await page.addStyleTag({ content: 'html,body{background:transparent!important}' });
  await prepare(page);
  return { page, context, close: () => context.close() };
}

// What the worker would answer, for the messages the preview page does not.
// `shortlist` is the app's research queue as the panel reads it; `own` are the
// severities the product on this page would show once it joins.
export const stub = ({ quick = null, shortlist = [], own = [] } = {}) => (page) => page.evaluate(({ q, list, mine }) => {
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

export const deliver = (page, entry) => page.evaluate((e) => window.__preview.deliver('result', e), entry);
export const panel = (page) => page.locator('kriko-panel-host >> .lite-panel');
export const hidePage = (page) => page.addStyleTag({ content: '.page{display:none!important}' });
export const SIZE = { width: 432, height: 980 };
export const severities = (key) => data[key].claims.map((c) => c.severity);

// A drawn bicycle: the listing beside the panel in hero-*.png is invented too.
export const BIKE = `<svg viewBox="0 0 300 190" width="250" xmlns="http://www.w3.org/2000/svg" fill="none" stroke-linecap="round" stroke-linejoin="round">
  <g stroke="#3b4256" stroke-width="7"><circle cx="70" cy="130" r="42"/><circle cx="232" cy="130" r="42"/>
  <path d="M70 130 140 130 118 72 200 66 M200 66 232 130 M118 72 70 130 M118 72 104 72 M200 66 214 50 238 50"/></g>
  <path d="M140 130 205 78" stroke="#8791aa" stroke-width="15"/><circle cx="140" cy="130" r="9" fill="#3b4256" stroke="none"/></svg>`;


/** The panel beside an invented listing: a shop page the way a visitor sees it. */
export async function showListing(page) {
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
}

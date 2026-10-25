// Draws the website's desktop pictures with the real desktop interface.
//
//   PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/capture-app.mjs
//   python3 site/tools/optimise_images.py
//
// The window is the app's own build (kriko-ui/dist, so run `npm run build` in
// kriko-ui first) talking to a real engine: a sidecar started in an empty home
// folder of its own, whose saved checks, queue and comparison are the invented
// e-bikes of examples.json and app_examples.json (seed_app_examples.py). Nothing
// of the reader's own machine can reach a picture: the engine's home is a
// temporary folder, its extension port is off, and the proxy below is the only
// door the page has.
//
// Environment: PLAYWRIGHT_MODULE (required unless playwright resolves), PYTHON
// (default `python`), CHROMIUM (a browser binary, if Playwright cannot find
// one), ONLY (a comma list of picture names to draw).
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../..');
const dist = path.resolve(repo, 'kriko-ui/dist');
const out = path.resolve(process.env.OUT || path.join(here, '../assets/desktop'));
const python = process.env.PYTHON || 'python';
const only = (process.env.ONLY || '').split(',').filter(Boolean);
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
if (!fs.existsSync(path.join(dist, 'index.html'))) throw new Error('kriko-ui/dist is missing: run `npm run build` in kriko-ui first');
fs.mkdirSync(out, { recursive: true });

// ── a private engine, seeded ────────────────────────────────────────────────
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'kriko-site-'));
fs.mkdirSync(path.join(home, '.kriko'));
// Placeholder keys, so the app offers its own Kriko Agent as the reader's agent.
// They are not real and nothing here runs a search, so nothing ever sends them.
fs.writeFileSync(path.join(home, '.kriko', 'env'), 'MERCURY_API_KEY=placeholder-not-a-key\nDEEPSEEK_API_KEY=placeholder-not-a-key\n');
// The engine lists the coding agents it finds on PATH. A picture should show the
// agent the app ships, not whichever CLI this machine happens to have, so the
// engine sees Python and Windows and nothing else (when PYTHON is a full path).
const system = process.env.SystemRoot || 'C:\\Windows';
const searchPath = path.isAbsolute(python)
  ? [path.dirname(python), path.join(system, 'System32'), system].join(path.delimiter)
  : process.env.PATH;
if (!path.isAbsolute(python)) console.log('PYTHON is not a full path: agents installed on this machine may appear in the pictures');
const env = { ...process.env, PATH: searchPath, USERPROFILE: home, HOME: home, PYTHONPATH: path.join(repo, 'src'), PYTHONIOENCODING: 'utf-8' };
const seeded = spawnSync(python, [path.join(here, 'seed_app_examples.py'), path.join(home, '.kriko', 'app.sqlite')], { env, encoding: 'utf8' });
if (seeded.status !== 0) throw new Error(`seeding failed: ${seeded.stderr}`);
const engine = spawn(python, ['-m', 'app.sidecar', '--extension-port', '0'], { env, cwd: repo, stdio: ['pipe', 'pipe', 'pipe'] });
const enginePort = await new Promise((resolve, reject) => {
  let seen = '';
  const timer = setTimeout(() => reject(new Error(`the engine did not announce its port: ${seen}`)), 60000);
  engine.stdout.on('data', (chunk) => {
    seen += chunk;
    const match = /KRIKO_PORT (\d+)/.exec(seen);
    if (match) { clearTimeout(timer); resolve(Number(match[1])); }
  });
  engine.on('exit', () => reject(new Error(`the engine exited: ${seen}`)));
});

// ── the window: the built interface, and the engine behind /api ─────────────
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.png': 'image/png', '.webp': 'image/webp', '.json': 'application/json' };
const server = http.createServer((req, res) => {
  if (req.url.startsWith('/api/')) {
    // The way the shell calls it: from outside the page, so with no Origin.
    const headers = { ...req.headers, host: `127.0.0.1:${enginePort}` };
    delete headers.origin;
    delete headers.referer;
    const upstream = http.request({ host: '127.0.0.1', port: enginePort, path: req.url, method: req.method, headers }, (reply) => {
      res.writeHead(reply.statusCode, reply.headers);
      reply.pipe(res);
    });
    upstream.on('error', () => { res.writeHead(502); res.end(); });
    req.pipe(upstream);
    return;
  }
  let rel = decodeURIComponent(req.url.split('?')[0]);
  if (rel === '/') rel = '/index.html';
  const file = path.join(dist, rel);
  if (!file.startsWith(dist) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
}).listen(0, '127.0.0.1');
await new Promise((resolve) => server.on('listening', resolve));
const base = `http://127.0.0.1:${server.address().port}`;

// ── the pictures ────────────────────────────────────────────────────────────
// The wide window for a desktop screen, and a narrow one (the app lays itself out
// again below a width) for a phone, where the wide picture could not be read.
const SIZES = { '': { width: 1440, height: 900 }, '-compact': { width: 760, height: 1000 } };
// Each picture and the sizes the page uses it at: the comparison is the wide one
// (and has a narrow copy for a phone); the other two sit in a pair and are only
// ever shown as narrow windows, where their text can be read.
const shots = {
  home: { sizes: ['-compact'], go: async () => {} },
  product: { sizes: ['-compact'], go: async (page) => {
    await page.getByText('E-bike M · 2022').first().click();
    await page.getByText(/^Evidence · \d+ sources?/).first().click();
  } },
  // By place, not by name: in the narrow window the navigation is icons only. It
  // reads Chat, Compare, Queue, History, New chat.
  compare: { sizes: ['', '-compact'], go: async (page) => { await page.locator('nav button').nth(1).click(); } },
};

const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
let failed = false;
try {
  for (const [name, { sizes, go }] of Object.entries(shots)) {
    if (only.length && !only.includes(name)) continue;
    for (const suffix of sizes) for (const scheme of ['light', 'dark']) {
      const viewport = SIZES[suffix];
      const context = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: scheme });
      const page = await context.newPage();
      page.on('pageerror', (error) => { failed = true; console.log('PAGEERROR', name, scheme, error.message); });
      await page.goto(base, { waitUntil: 'networkidle' });
      await page.getByText('What do you want to check?').waitFor({ timeout: 20000 });
      await go(page);
      await page.waitForTimeout(1800);
      await page.screenshot({ path: path.join(out, `${name}${suffix}-${scheme}.png`) });
      console.log('drew', `${name}${suffix}-${scheme}.png`);
      await context.close();
    }
  }
} catch (error) {
  failed = true;
  console.log('FAILED', String(error.message || error).split(/\r?\n/).slice(0, 4).join(' | '));
} finally {
  await browser.close();
  server.close();
  // Closing its stdin is how the engine is told to go; it holds its files until
  // it has, so the folder is removed only after it has gone (or been killed).
  engine.stdin.end();
  const gone = new Promise((resolve) => engine.once('exit', resolve));
  await Promise.race([gone, new Promise((resolve) => setTimeout(resolve, 8000))]);
  if (engine.exitCode === null) { engine.kill(); await Promise.race([gone, new Promise((resolve) => setTimeout(resolve, 3000))]); }
  try { fs.rmSync(home, { recursive: true, force: true, maxRetries: 8, retryDelay: 400 }); } catch { console.log(`left behind: ${home}`); }
  process.exit(failed ? 1 : 0);
}

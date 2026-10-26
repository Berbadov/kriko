// Records the guide's GIFs with the real apps: the extension's panel and the desktop window.
//
//   PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs FFMPEG=/path/to/ffmpeg \
//     PYTHON=/full/path/to/python node site/tools/capture-guide.mjs
//
// Each scene is a short script of mouse moves and presses against the same invented data as the
// site's pictures (panel-harness.mjs for the panel, app-harness.mjs for the window). A pointer is
// drawn into the page, because a recording shows no mouse. Playwright films the page, ffmpeg cuts
// the part that matters and writes two files for each scene in assets/guide/:
//   <name>.gif          what the guide shows
//   <name>-poster.webp  one still, for a reader who has asked for less motion
// Environment: PLAYWRIGHT_MODULE, FFMPEG (default `ffmpeg`), PYTHON, CHROMIUM, ONLY (a comma list
// of scene names), OUT.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { deliver, entryFor, examples, hidePage, quickFor, servePanel, session as panelSession, showListing, stub } from './panel-harness.mjs';
import { startApp } from './app-harness.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(process.env.OUT || path.join(here, '../assets/guide'));
const ffmpeg = process.env.FFMPEG || 'ffmpeg';
const only = (process.env.ONLY || '').split(',').filter(Boolean);
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
fs.mkdirSync(out, { recursive: true });
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'kriko-guide-'));

// The pointer: drawn into the page, with a ring where it presses.
const POINTER = `(() => {
  const make = () => {
    if (document.getElementById('__pointer')) return;
    const cursor = document.createElement('div');
    cursor.id = '__pointer';
    cursor.style.cssText = 'position:fixed;left:0;top:0;width:30px;height:30px;z-index:2147483647;pointer-events:none;transform:translate(-90px,-90px);filter:drop-shadow(2px 3px 2px rgba(11,16,32,.35))';
    cursor.innerHTML = '<svg viewBox="0 0 32 32" width="30" height="30"><path d="M4 2 L4 25 L10 20 L14 29 L19 27 L15 18 L23 18 Z" fill="#fff" stroke="#0b1020" stroke-width="2.2" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(cursor);
    const ring = document.createElement('div');
    ring.style.cssText = 'position:fixed;left:0;top:0;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;border:3px solid #2447e6;opacity:0;z-index:2147483646;pointer-events:none';
    document.documentElement.appendChild(ring);
    addEventListener('mousemove', (e) => { cursor.style.transform = 'translate(' + e.clientX + 'px,' + e.clientY + 'px)'; }, true);
    addEventListener('mousedown', (e) => {
      ring.style.transition = 'none'; ring.style.left = e.clientX + 'px'; ring.style.top = e.clientY + 'px'; ring.style.opacity = '1'; ring.style.transform = 'scale(.4)';
      requestAnimationFrame(() => requestAnimationFrame(() => { ring.style.transition = 'transform .45s ease-out, opacity .45s ease-out'; ring.style.transform = 'scale(1.5)'; ring.style.opacity = '0'; }));
    }, true);
  };
  if (document.documentElement) make(); else document.addEventListener('DOMContentLoaded', make);
})();`;

const glide = async (page, target, { steps = 26, dx = 0, dy = 0 } = {}) => {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  await page.mouse.move(box.x + box.width / 2 + dx, box.y + box.height / 2 + dy, { steps });
};
const press = async (page, target, options) => {
  await glide(page, target, options);
  await page.waitForTimeout(240);
  await page.mouse.down();
  await page.waitForTimeout(90);
  await page.mouse.up();
};

// What `film` does with a finished recording: cut [start, start+length] and make the two files.
function encode(video, name, { start, length, width, fps, posterAt }) {
  const run = (args) => {
    const r = spawnSync(ffmpeg, ['-y', '-v', 'error', ...args], { encoding: 'utf8' });
    if (r.status !== 0) throw new Error(`ffmpeg failed for ${name}: ${r.stderr}`);
  };
  const cut = ['-ss', String(start), '-t', String(length), '-i', video];
  const scale = `fps=${fps},scale=${width}:-2:flags=lanczos`;
  run([...cut, '-vf', `${scale},split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle`, '-loop', '0', path.join(out, `${name}.gif`)]);
  run(['-ss', String(start + posterAt), '-i', video, '-frames:v', '1', '-vf', `scale=${width}:-2:flags=lanczos`, '-c:v', 'libwebp', '-quality', '82', path.join(out, `${name}-poster.webp`)]);
  const kb = (f) => Math.round(fs.statSync(path.join(out, f)).size / 1024);
  console.log(`${name}: gif ${kb(`${name}.gif`)} KB, poster ${kb(`${name}-poster.webp`)} KB, ${length.toFixed(1)} s`);
}

// A scene: `open` makes a page (and may do things the film should not show), `play` is the part that is shown.
async function film(name, { viewport, scheme = 'light', width, fps = 12, open, play, posterAt }) {
  const t0 = Date.now();
  const opened = await open({ viewport, scheme, recordVideo: { dir: scratch, size: viewport }, initScript: POINTER });
  const page = opened.page;
  const start = (Date.now() - t0) / 1000 + 0.2;
  await play(page);
  const end = (Date.now() - t0) / 1000 + 0.4;
  await opened.close();
  const video = await page.video().path();
  encode(video, name, { start, length: end - start, width, fps, posterAt: posterAt ?? (end - start) * 0.85 });
}

// ── the scenes ────────────────────────────────────────────────────────────────
const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
const panelServer = await servePanel();
const panelAt = (options, prepare, extra = '') => panelSession(browser, panelServer.base, options.scheme, options.viewport, 1, prepare, extra, { recordVideo: options.recordVideo, initScript: options.initScript });
const app = await startApp();
const appAt = async (options) => {
  const context = await browser.newContext({ viewport: options.viewport, deviceScaleFactor: 1, colorScheme: options.scheme, recordVideo: options.recordVideo });
  await context.addInitScript(options.initScript);
  const page = await context.newPage();
  await page.goto(app.base, { waitUntil: 'networkidle' });
  await page.getByText('What do you want to check?').waitFor({ timeout: 20000 });
  await page.waitForTimeout(500);
  return { page, close: () => context.close() };
};
const host = (page) => page.locator('kriko-panel-host');
const WINDOW = { width: 1180, height: 760 };

const scenes = {
  // the panel beside a listing: it fills in, one finding opens
  'check-a-listing': () => film('check-a-listing', {
    viewport: { width: 760, height: 800 }, width: 600,
    open: (o) => panelAt(o, async (page) => {
      await stub()(page);
      await hidePage(page);
      await showListing(page);
      await deliver(page, entryFor('ebike'));
      // the panel is already filled in; it is held back so the film can show it arrive
      await page.addStyleTag({ content: 'kriko-panel-host{opacity:0;transform:translateX(36px)}' });
      await page.waitForTimeout(1500);
    }),
    play: async (page) => {
      await page.mouse.move(520, 620);
      await page.waitForTimeout(900);
      await page.addStyleTag({ content: 'kriko-panel-host{opacity:1!important;transform:none!important;transition:opacity .5s ease-out,transform .5s ease-out}' });
      await page.waitForTimeout(1500);
      await press(page, host(page).locator('.lite-rc-toggle').first());
      await page.waitForTimeout(2000);
      await glide(page, host(page).locator('.lite-rc-toggle').first(), { dx: -150, dy: 150, steps: 30 });
      await page.waitForTimeout(700);
    },
  }),
  // a product no catalog holds: research it with your own agent
  'quick-look': () => film('quick-look', {
    viewport: { width: 432, height: 800 }, width: 432,
    open: (o) => panelAt(o, async (page) => {
      await stub({ quick: quickFor() })(page);
      await hidePage(page);
      await page.evaluate((n) => { document.title = `${n} | Example shop`; }, examples.research.title);
    }, '&research=found'),
    play: async (page) => {
      await page.mouse.move(300, 560);
      await page.evaluate((n) => window.__preview.deliver('result', { ok: false, code: 'UNKNOWN_PRODUCT', productName: n }), examples.research.title);
      await page.waitForTimeout(1300);
      await press(page, host(page).locator('.lite-cta'));
      await page.waitForTimeout(900);
      await press(page, host(page).locator('.lite-research-start'));
      await page.waitForTimeout(2200);
    },
  }),
  // the desktop window: a saved check, and the evidence behind it
  'saved-check': () => film('saved-check', {
    viewport: WINDOW, width: 720,
    open: appAt,
    play: async (page) => {
      await page.mouse.move(900, 500);
      await page.waitForTimeout(1100);
      await press(page, page.getByText('E-bike M · 2022').first());
      await page.waitForTimeout(1700);
      await press(page, page.getByText(/^Evidence · \d+ sources?/).first());
      await page.waitForTimeout(2200);
    },
  }),
  // lining products up, and showing only where they differ
  'compare': () => film('compare', {
    viewport: WINDOW, width: 720,
    open: appAt,
    play: async (page) => {
      await page.mouse.move(800, 400);
      await page.waitForTimeout(900);
      await press(page, page.locator('nav button').nth(1));
      await page.waitForTimeout(2000);
      await press(page, page.getByText('Differences only').first(), { dx: 60 });
      await page.waitForTimeout(2200);
      await press(page, page.getByText('Differences only').first(), { dx: 60 });
      await page.waitForTimeout(900);
    },
  }),
  // how much doubt to see: a setting, and what it does to the findings of a check
  'doubt': () => film('doubt', {
    viewport: WINDOW, width: 720,
    open: appAt,
    play: async (page) => {
      await page.mouse.move(800, 420);
      await page.waitForTimeout(700);
      await press(page, page.getByText('E-bike T · 2023').first());
      await page.waitForTimeout(1900);
      await press(page, page.getByRole('button', { name: 'Settings' }).first());
      await page.waitForTimeout(800);
      await press(page, page.getByRole('radio', { name: 'Hide thin' }).or(page.getByRole('button', { name: 'Hide thin' })).first());
      await page.waitForTimeout(1100);
      await press(page, page.getByRole('button', { name: /^close/i }).first());
      await page.waitForTimeout(2300);
    },
  }),
};

let failed = false;
try {
  for (const [name, run] of Object.entries(scenes)) {
    if (only.length && !only.includes(name)) continue;
    try { await run(); } catch (error) { failed = true; console.log('FAILED', name, String(error.message || error).split(/\r?\n/).slice(0, 5).join(' | ')); }
  }
} finally {
  await browser.close();
  panelServer.close();
  await app.stop();
  try { fs.rmSync(scratch, { recursive: true, force: true, maxRetries: 6, retryDelay: 300 }); } catch { /* the films are scratch */ }
  process.exit(failed ? 1 : 0);
}

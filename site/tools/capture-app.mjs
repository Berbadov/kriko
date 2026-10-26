// Draws the website's desktop pictures with the real desktop interface.
//
//   PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/capture-app.mjs
//   python3 site/tools/optimise_images.py
//
// The window is the app's own build on a real, seeded engine (app-harness.mjs).
//
// Environment: PLAYWRIGHT_MODULE (required unless playwright resolves), PYTHON
// (default `python`; a full path also hides this machine's agents), CHROMIUM (a
// browser binary, if Playwright cannot find one), ONLY (a comma list of picture
// names to draw), OUT (where to write).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { startApp } from './app-harness.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(process.env.OUT || path.join(here, '../assets/desktop'));
const only = (process.env.ONLY || '').split(',').filter(Boolean);
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
fs.mkdirSync(out, { recursive: true });

// The engine, seeded, and the window on it (app-harness.mjs).
const { base, stop } = await startApp();

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
  await stop();
  process.exit(failed ? 1 : 0);
}

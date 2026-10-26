// Draws the website's example pictures with the real extension panel.
//
//   PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/capture.mjs
//   python3 site/tools/optimise_images.py
//
// The panel and its invented products come from panel-harness.mjs. Playwright is
// not a dependency of this repository; point PLAYWRIGHT_MODULE at any copy of it
// (and CHROMIUM at a browser binary if it cannot find one). OUT names another
// folder to write to.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { data, deliver, entryFor, examples, hidePage, panel, quickFor, servePanel, session as panelSession, severities, showListing, SIZE, stub } from './panel-harness.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(process.env.OUT || path.join(here, '../assets/examples'));
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
fs.mkdirSync(out, { recursive: true });
const { base, close } = await servePanel();
const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
const session = (...args) => panelSession(browser, base, ...args);

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
      await showListing(page);
    });
    await deliver(s.page, entryFor('ebike'));
    await s.page.waitForTimeout(1600);
    await s.page.screenshot({ path: path.join(out, `hero-${scheme}.png`) });
    await s.close();
  }
}
await browser.close();
close();
console.log('wrote', fs.readdirSync(out).filter((f) => f.endsWith('.png')).length, 'pictures to', out);

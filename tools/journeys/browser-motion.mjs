// Browser dashboard motion journey; the API edge uses fixtures.
// Serve the built app at BASE with /static paths, then run with Playwright.
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdirSync } from 'node:fs';
const { chromium } = createRequire(import.meta.url)('playwright');
const base = process.argv[2] || 'http://127.0.0.1:8799';
(async () => {
  const browser = await chromium.launch();
  const out = process.argv[3] || '.walk/motion';
  mkdirSync(out, {recursive: true});
  try {
    for (const reducedMotion of ['no-preference', 'reduce']) {
      const page = await browser.newPage({reducedMotion, viewport: {width: 1280, height: 900}});
      const errors = [];
      page.on('pageerror', error => errors.push(String(error)));
      await page.route('**/api/**', async route => {
        const path = new URL(route.request().url()).pathname;
        const data = path === '/api/prefs' ? {harnesses: [], chosen: {}} :
          path === '/api/health' ? {version: '1.1.0', ready: true} : {items: []};
        await route.fulfill({json: data});
      });
      await page.goto(`${base}/#/run`);
      await page.locator('canvas').waitFor();
      const frames = [];
      for (let i = 0; i < 3; i++) {
        frames.push(createHash('sha256').update(await page.locator('canvas').evaluate(el => el.toDataURL())).digest('hex'));
        await page.waitForTimeout(500);
      }
      assert.equal(new Set(frames).size, reducedMotion === 'reduce' ? 1 : 3);
      if (reducedMotion === 'reduce') assert.match(await page.locator('figure figcaption').textContent(), /done · committed/);
      if (reducedMotion === 'no-preference') {
        // Control the visibility edge in headless Chromium; the production
        // document listener and animation loop remain untouched.
        await page.evaluate(() => {
          Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});
          document.dispatchEvent(new Event('visibilitychange'));
        });
        await page.waitForTimeout(100);
        const paused = await page.locator('canvas').evaluate(el => el.toDataURL());
        await page.waitForTimeout(500);
        assert.equal(await page.locator('canvas').evaluate(el => el.toDataURL()), paused);
        await page.evaluate(() => {
          delete document.hidden;
          document.dispatchEvent(new Event('visibilitychange'));
        });
        await page.waitForTimeout(500);
        assert.notEqual(await page.locator('canvas').evaluate(el => el.toDataURL()), paused);
        console.log('Controlled hidden-tab event pauses the scene; visibility resumes it');
      }
      await page.screenshot({path: `${out}/run-${reducedMotion}.png`});
      assert.deepEqual(errors, []);
      await page.close();
      console.log(`${reducedMotion}: ${new Set(frames).size} distinct canvas frames, no page errors`);
    }
    const loader = await browser.newPage({viewport: {width: 1280, height: 900}});
    await loader.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (['/api/operations', '/api/jobs', '/api/usage', '/api/history'].includes(path)) return;
      await route.fulfill({json: {items: [], version: '1.1.0'}});
    });
    await loader.goto(`${base}/#/home`);
    await loader.getByText('Reading recent activity…').waitFor();
    assert.equal(await loader.locator('.loading svg').count(), 1);
    await loader.screenshot({path: `${out}/loader.png`});
    console.log('Home loader includes the jack mark');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});

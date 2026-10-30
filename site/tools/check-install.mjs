// Run against serve:site. Playwright is optional for the static website itself.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const moduleName = process.env.PLAYWRIGHT_MODULE;
const { chromium } = await import(moduleName ? pathToFileURL(moduleName).href : 'playwright');
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
});
const base = process.env.SITE_URL || 'http://127.0.0.1:4173';
const screenshotDir = process.env.SCREENSHOTS;
if (screenshotDir) fs.mkdirSync(screenshotDir, { recursive: true });

// Pick a generated product with reports in both languages, without a model list.
const slug = fs.readdirSync(path.join(root, 'problems')).sort().find(dir => {
  const product = path.join(root, 'problems', dir, 'index.html');
  return fs.existsSync(product) && fs.readFileSync(product, 'utf8').includes('<article class="claim')
    && fs.existsSync(path.join(root, 'tr/problems', dir, 'index.html'));
});
assert.ok(slug, 'a bilingual product page exists');

try {
  for (const javaScriptEnabled of [false, true]) {
    const page = await browser.newPage({ javaScriptEnabled });
    for (const [name, route, width] of [
      ['install-en-mobile', '/install/', 390],
      ['install-tr-mobile', '/tr/install/', 390],
      ['product-en-desktop', `/problems/${slug}/`, 1280],
      ['product-tr-mobile', `/tr/problems/${slug}/`, 390],
    ]) {
      await page.setViewportSize({ width, height: 900 });
      const response = await page.goto(`${base}${route}`, { waitUntil: 'networkidle' });
      assert.equal(response.status(), 200, route);
      const dimensions = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
      assert.ok(dimensions.scroll <= dimensions.width, `${route}, JavaScript ${javaScriptEnabled}: no horizontal overflow`);
      if (route.includes('/install/')) {
        await page.locator('#download details summary').click();
        assert.ok(await page.locator('#download pre').isVisible(), 'verification works without JavaScript');
        // The command scrolls within its own box, never the whole page.
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        await page.locator('#download details summary').click();
        assert.match(await page.locator('#download a.button').getAttribute('href'), /github\.com\/Berbadov\/kriko\/releases\/latest\/download\/kriko-.*-setup\.exe$/);
      } else {
        const install = route.startsWith('/tr/') ? '/tr/install/' : '/install/';
        assert.ok(await page.locator(`a[href="${install}"]`).count() >= 2, 'installation is available near the summary and findings');
      }
      if (screenshotDir && javaScriptEnabled) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({ path: path.join(screenshotDir, `${name}.png`), fullPage: true });
      }
      console.log(`${route}, JavaScript ${javaScriptEnabled}: passed`);
    }
    if (javaScriptEnabled) {
      await page.goto(`${base}/install/`);
      await page.locator('.menu-toggle').click();
      assert.ok(await page.locator('#main-nav a[href="/install/"]').isVisible());
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'), 'false');
    }
    await page.close();
  }
} finally {
  await browser.close();
}

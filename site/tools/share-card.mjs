// Draws the picture a shared link to kriko.cc unfurls into, from share-card.html.
//
//   PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/share-card.mjs
//
// The page, the fonts and the pictures are the site's own, so only the layout lives in
// share-card.html. Writes site/assets/share-card.jpg (1200x630).
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(path.join(here, 'share-card.html')).href);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  const out = path.join(here, '..', 'assets', 'share-card.jpg');
  await page.screenshot({ path: out, type: 'jpeg', quality: 90 });
  console.log('wrote', out);
} finally {
  await browser.close();
}

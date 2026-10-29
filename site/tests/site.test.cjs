const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { JSDOM } = require('jsdom');

const root = path.resolve(__dirname, '..');
const PAGES = [
  { file: 'index.html', url: 'https://kriko.cc/', lang: 'en' },
  { file: 'tr/index.html', url: 'https://kriko.cc/tr/', lang: 'tr' },
  { file: 'privacy/index.html', url: 'https://kriko.cc/privacy/', lang: 'en' },
  { file: 'guide/index.html', url: 'https://kriko.cc/guide/', lang: 'en' },
  { file: 'tr/guide/index.html', url: 'https://kriko.cc/tr/guide/', lang: 'tr' },
];
const HOME = PAGES.slice(0, 2);
const GUIDE = PAGES.slice(3, 5);
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const load = (page) => new JSDOM(read(page.file), { url: page.url }).window.document;
const css = read('styles.css');
// Every JSON-LD block a page carries, flattened to the nodes it declares.
const graphOf = (page) => [...load(page).querySelectorAll('script[type="application/ld+json"]')]
  .flatMap((script) => { const block = JSON.parse(script.textContent); return block['@graph'] || [block]; });

test('every page declares its language, one heading, a description and its own address', () => {
  for (const page of PAGES) {
    const d = load(page);
    assert.equal(d.documentElement.lang, page.lang, page.file);
    assert.equal(d.querySelectorAll('h1').length, 1, `${page.file} needs exactly one h1`);
    assert.ok(d.querySelector('meta[name="description"]').content.length > 40, page.file);
    assert.equal(d.querySelector('link[rel="canonical"]').href, page.url);
    assert.ok(d.querySelector('meta[name="viewport"]'), page.file);
  }
});

test('the English and Turkish pages point at each other and the language switch marks the current one', () => {
  for (const page of HOME) {
    const d = load(page);
    const alternates = Object.fromEntries([...d.querySelectorAll('link[rel="alternate"]')].map((l) => [l.hreflang, l.href]));
    assert.equal(alternates.en, 'https://kriko.cc/');
    assert.equal(alternates.tr, 'https://kriko.cc/tr/');
    assert.equal(alternates['x-default'], 'https://kriko.cc/');
    assert.equal(d.querySelector('.language-switch [aria-current="page"]').lang, page.lang);
  }
});

test('the guide in English and Turkish points at each other, and its language switch stays on the guide', () => {
  for (const page of GUIDE) {
    const d = load(page);
    const alternates = Object.fromEntries([...d.querySelectorAll('link[rel="alternate"]')].map((l) => [l.hreflang, l.href]));
    assert.equal(alternates.en, 'https://kriko.cc/guide/');
    assert.equal(alternates.tr, 'https://kriko.cc/tr/guide/');
    assert.equal(alternates['x-default'], 'https://kriko.cc/guide/');
    assert.equal(d.querySelector('.language-switch [aria-current="page"]').lang, page.lang);
    assert.deepEqual([...d.querySelectorAll('.language-switch a')].map((a) => a.getAttribute('href')), ['/guide/', '/tr/guide/']);
  }
});

test('a link to this site stays in the reader\'s language, and leads to a page and a place that exist', () => {
  const ids = {};
  const idsOf = (file) => (ids[file] ||= new Set([...load({ file, url: 'https://kriko.cc/' }).querySelectorAll('[id]')].map((el) => el.id)));
  for (const page of PAGES) {
    const d = load(page);
    for (const a of d.querySelectorAll('a[href^="/"]')) {
      const href = a.getAttribute('href');
      const [pathname, fragment] = href.split('#');
      const target = pathname === '/' ? 'index.html' : `${pathname.replace(/^\//, '')}index.html`;
      assert.ok(fs.existsSync(path.join(root, target)), `${page.file} links to ${href}, which has no page`);
      if (fragment) assert.ok(idsOf(target).has(fragment), `${page.file} links to ${href}, which names no such place`);
      if (page.lang === 'tr' && !a.closest('.language-switch') && !pathname.startsWith('/privacy/')) {
        assert.ok(pathname.startsWith('/tr/'), `${page.file} sends a Turkish reader to ${href}`);
      }
    }
  }
});

test('every local file a page names exists, and nothing is loaded from another site', () => {
  for (const page of PAGES) {
    const d = load(page);
    const dir = path.dirname(path.join(root, page.file));
    for (const el of d.querySelectorAll('[src], link[href], source[srcset]')) {
      const value = el.getAttribute('src') || el.getAttribute('href') || el.getAttribute('srcset');
      if (el.matches('link[rel="canonical"], link[rel="alternate"]')) continue;
      assert.ok(!/^(https?:)?\/\//.test(value), `${page.file} loads ${value} from another site`);
      assert.ok(fs.existsSync(path.resolve(dir, value.split('?')[0])), `${page.file} names a missing file: ${value}`);
    }
    assert.equal(d.querySelectorAll('link[href*="font"], style[src]').length, 0, `${page.file} loads a font service`);
  }
});

test('the download button hands over the installer file, and GitHub is its own link', () => {
  const INSTALLER = /^https:\/\/github\.com\/Berbadov\/kriko\/releases\/latest\/download\/kriko-\d+\.\d+\.\d+-x86_64-setup\.exe$/;
  for (const page of HOME) {
    const d = load(page);
    const downloads = [...d.querySelectorAll('a[href$="-setup.exe"]')];
    assert.equal(downloads.length, 2, `${page.file} offers the installer from the hero and from the install section`);
    for (const link of downloads) {
      assert.match(link.getAttribute('href'), INSTALLER, `${page.file}: ${link.getAttribute('href')} does not hand over the installer`);
    }
    assert.ok(d.querySelector('.actions a[href="https://github.com/Berbadov/kriko"]'), `${page.file} has no GitHub button beside the download`);
  }
});

test('every picture has alternative text and a size, and every dark version has a light one', () => {
  for (const page of PAGES) {
    const d = load(page);
    for (const img of d.querySelectorAll('img')) {
      assert.ok(img.getAttribute('alt') !== null, `${page.file}: ${img.getAttribute('src')} has no alt`);
      assert.ok(img.getAttribute('width') && img.getAttribute('height'), `${page.file}: ${img.getAttribute('src')} has no size, so the page would jump while it loads`);
    }
    for (const source of d.querySelectorAll('picture source[media*="dark"]')) {
      assert.ok(source.closest('picture').querySelector('img'), `${page.file} has a dark picture with no light one`);
    }
  }
});

test('the stylesheet and script carry the hash of their own content, on every page', () => {
  for (const page of PAGES) {
    const d = load(page);
    const dir = path.dirname(path.join(root, page.file));
    for (const el of d.querySelectorAll('script[src], link[rel="stylesheet"]')) {
      const value = el.getAttribute('src') || el.getAttribute('href');
      const [asset, query] = value.split('?');
      const bytes = fs.readFileSync(path.resolve(dir, asset));
      assert.equal(new URLSearchParams(query).get('v'), crypto.createHash('sha256').update(bytes).digest('hex').slice(0, 12), `${page.file}: ${value}`);
    }
  }
});

// A link pasted into X, Bluesky, Slack or a chat unfurls into this picture; a 128px icon there
// reads as a broken link. It is also what the page promises, so the page must name one that exists.
test('a shared link to a page unfurls into a large picture that exists, with a description and the page\'s own address', () => {
  for (const page of [...HOME, ...GUIDE]) {
    const d = load(page);
    const meta = (key) => d.querySelector(`meta[property="${key}"], meta[name="${key}"]`);
    assert.equal(meta('twitter:card').content, 'summary_large_image', page.file);
    assert.equal(meta('og:url').content, page.url, `${page.file}: the shared address is not the page's own`);
    const image = meta('og:image').content;
    assert.match(image, /^https:\/\/kriko\.cc\/assets\/[\w-]+\.jpg$/, `${page.file}: ${image}`);
    const file = path.join(root, image.replace('https://kriko.cc/', ''));
    assert.ok(fs.existsSync(file), `${page.file}: ${image} is not a file`);
    const bytes = fs.readFileSync(file);
    // A JPEG's size sits in its start-of-frame marker.
    const frame = bytes.indexOf(Buffer.from([0xff, 0xc0]));
    assert.equal(bytes.readUInt16BE(frame + 5), Number(meta('og:image:height').content), `${page.file}: the stated height is not the picture's`);
    assert.equal(bytes.readUInt16BE(frame + 7), Number(meta('og:image:width').content), `${page.file}: the stated width is not the picture's`);
    assert.ok(bytes.length < 400 * 1024, `${page.file}: ${image} is over 400 KB, which some apps refuse`);
    assert.ok(meta('og:image:alt').content.length > 40, `${page.file}: the share picture is not described`);
  }
});

test('the film on the home page waits for a press, has a still and a way to save it, and is small enough to host', () => {
  for (const page of HOME) {
    const d = load(page);
    const dir = path.dirname(path.join(root, page.file));
    const video = d.querySelector('#film video');
    assert.ok(video, `${page.file} has no film`);
    assert.ok(video.hasAttribute('controls'), `${page.file}: the film has no controls`);
    assert.ok(!video.hasAttribute('autoplay'), `${page.file}: the film starts with sound by itself`);
    assert.equal(video.getAttribute('preload'), 'none', `${page.file}: the film would download before it is wanted`);
    assert.ok(video.getAttribute('aria-label').length > 40, `${page.file}: the film is not described`);
    const still = path.resolve(dir, video.getAttribute('poster'));
    assert.ok(fs.existsSync(still), `${page.file}: the film's still is missing`);
    const file = path.resolve(dir, video.querySelector('source').getAttribute('src'));
    // Cloudflare Pages refuses a file over 25 MiB; keep well under it.
    assert.ok(fs.statSync(file).size < 12 * 1024 * 1024, `${page.file}: the film is over 12 MB`);
    assert.ok(video.querySelector('a[href$=".mp4"]'), `${page.file}: a browser that cannot play it has no link to the file`);
    assert.ok(d.querySelector('#film figcaption').textContent.length > 20, `${page.file}: the film has no caption`);
  }
});

test('robots.txt names the sitemap, the sitemap lists exactly the pages that exist, and an unknown address gets a real 404 page', () => {
  assert.match(read('robots.txt'), /^Sitemap: https:\/\/kriko\.cc\/sitemap\.xml$/m);
  const listed = [...read('sitemap.xml').matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]).sort();
  assert.deepEqual(listed, PAGES.map((page) => page.url).sort());
  const d = new JSDOM(read('404.html'), { url: 'https://kriko.cc/404.html' }).window.document;
  assert.match(d.querySelector('meta[name="robots"]').content, /noindex/);
  // It answers at any address, so a relative path would break one folder down.
  for (const el of d.querySelectorAll('link[href], img[src], source[srcset], a[href]')) {
    const value = el.getAttribute('href') || el.getAttribute('src') || el.getAttribute('srcset');
    assert.ok(value.startsWith('/'), `404.html names ${value} relatively`);
    if (!/\.(css|svg|png)(\?|$)/.test(value)) continue;
    const [asset, query] = value.split('?');
    const bytes = fs.readFileSync(path.join(root, asset));
    if (asset === '/styles.css') assert.equal(new URLSearchParams(query).get('v'), crypto.createHash('sha256').update(bytes).digest('hex').slice(0, 12), 'the stylesheet hash is stale');
  }
});

test('the home page tells an answer engine what Kriko is, with the questions a reader can open', () => {
  for (const page of HOME) {
    const d = load(page);
    const graph = graphOf(page);
    const ofType = (type) => graph.find((node) => node['@type'] === type);
    const app = ofType('SoftwareApplication');
    assert.ok(app, `${page.file} does not describe the app`);
    assert.equal(app.name, 'Kriko');
    assert.equal(app.applicationCategory, 'UtilitiesApplication');
    assert.equal(app.offers.price, '0', `${page.file}: the app is not described as free`);
    assert.equal(app.offers.priceCurrency, 'USD');
    assert.equal(app.isAccessibleForFree, true);
    assert.match(app.downloadUrl, /^https:\/\/github\.com\/Berbadov\/kriko\/releases\//, `${page.file}: the app names no installer`);
    assert.ok(app.description.length > 40, `${page.file}: the app is not described`);
    assert.equal(app.inLanguage, page.lang);
    const org = ofType('Organization');
    assert.equal(org.name, 'Kriko');
    assert.deepEqual(org.sameAs, ['https://github.com/Berbadov/kriko']);
    assert.ok(ofType('WebSite').inLanguage.includes(page.lang));
    const faq = ofType('FAQPage');
    assert.ok(faq, `${page.file} shows questions but declares no FAQPage`);
    assert.deepEqual(faq.mainEntity.map((q) => q.name), [...d.querySelectorAll('.faq summary')].map((s) => s.textContent.trim()), `${page.file}: the declared questions are not the ones on the page`);
    for (const question of faq.mainEntity) assert.ok(question.acceptedAnswer.text.length > 20, `${page.file}: ${question.name} has no answer`);
  }
});

test('the guide tells an answer engine its steps, from the sections a reader scrolls through', () => {
  for (const page of GUIDE) {
    const d = load(page);
    const how = graphOf(page).find((node) => node['@type'] === 'HowTo');
    assert.ok(how, `${page.file} has no HowTo`);
    const sections = [...d.querySelectorAll('.guide-step')];
    assert.ok(sections.length > 2);
    assert.equal(how.step.length, sections.length);
    assert.deepEqual(how.step.map((step) => step.name), sections.map((s) => s.querySelector('h2').textContent.trim()));
    assert.equal(how.inLanguage, page.lang);
    for (const step of how.step) {
      assert.ok(step.text.length > 20, step.name);
      assert.match(step.url, /^https:\/\/kriko\.cc\/(tr\/)?guide\/#[a-z]+$/, step.name);
    }
  }
});

test('llms.txt says what Kriko is, links every catalog, and is what the tooling writes', () => {
  const before = read('llms.txt');
  try {
    execFileSync(process.execPath, [path.join(root, 'tools/render_llms.cjs')], { stdio: 'pipe' });
  } catch (error) {
    assert.fail(`render_llms failed:\n${error.stderr}`);
  }
  const now = read('llms.txt');
  if (now !== before) fs.writeFileSync(path.join(root, 'llms.txt'), before);
  assert.equal(now, before, 'llms.txt is stale: run node site/tools/render_llms.cjs and commit the result');
  assert.match(before, /^# Kriko\n\n> Kriko is a free, open-source/, 'llms.txt does not open with what Kriko is');
  for (const link of ['https://kriko.cc/', 'https://kriko.cc/guide/', 'https://kriko.cc/privacy/', 'https://kriko.cc/tr/', 'https://kriko.cc/problems/safety/']) {
    assert.ok(before.includes(`](${link})`), `llms.txt does not link ${link}`);
  }
  const hub = load({ file: 'problems/index.html', url: 'https://kriko.cc/problems/' });
  for (const card of hub.querySelectorAll('.cards .card')) {
    const url = new URL(card.getAttribute('href'), 'https://kriko.cc').href;
    assert.ok(before.includes(`](${url})`), `llms.txt does not link ${url}`);
  }
});

test('robots.txt lets the answer engines in and names the file written for them', () => {
  const robots = read('robots.txt');
  for (const bot of ['Googlebot', 'Bingbot', 'GPTBot', 'OAI-SearchBot', 'ChatGPT-User', 'ClaudeBot', 'Claude-SearchBot', 'PerplexityBot', 'Google-Extended']) {
    assert.match(robots, new RegExp(`^User-agent: ${bot}$`, 'm'), `robots.txt does not name ${bot}`);
  }
  assert.match(robots, /^Allow: \/$/m, 'a named crawler is not allowed in');
  assert.match(robots, /^Disallow: \/tools\/$/m);
  assert.match(robots, /https:\/\/kriko\.cc\/llms\.txt/, 'robots.txt does not point at llms.txt');
});

test('the Turkish page is what the English page and the translations make', () => {
  const before = Object.fromEntries(PAGES.map((p) => [p.file, read(p.file)]));
  try {
    execFileSync(process.execPath, [path.join(root, 'tools/render-locales.cjs')], { stdio: 'pipe' });
  } catch (error) {
    for (const [file, text] of Object.entries(before)) fs.writeFileSync(path.join(root, file), text);
    assert.fail(`render-locales failed:\n${error.stderr}`);
  }
  for (const [file, text] of Object.entries(before)) {
    const now = read(file);
    if (now !== text) fs.writeFileSync(path.join(root, file), text);
    assert.equal(now, text, `${file} is stale: run node site/tools/render-locales.cjs and commit the result`);
  }
});

function tokens(block) {
  return Object.fromEntries([...block.matchAll(/--([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map((m) => [m[1], m[2]]));
}
const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

test('text is readable on its background in the light theme and in the dark one', () => {
  const light = tokens(css.slice(css.indexOf(':root {'), css.indexOf('@media (prefers-color-scheme: dark)')));
  const dark = tokens(css.slice(css.indexOf('@media (prefers-color-scheme: dark)'), css.indexOf('* { box-sizing')));
  assert.ok(Object.keys(dark).length >= 6, 'the dark theme overrides the colour tokens');
  for (const [name, theme] of [['light', light], ['dark', { ...light, ...dark }]]) {
    assert.ok(contrast(theme.ink, theme.bg) >= 7, `${name}: body text on the page`);
    assert.ok(contrast(theme.ink, theme.soft) >= 7, `${name}: body text on a tinted section`);
    assert.ok(contrast(theme.muted, theme.bg) >= 4.5, `${name}: secondary text on the page`);
    assert.ok(contrast(theme.muted, theme.soft) >= 4.5, `${name}: secondary text on a tinted section`);
    assert.ok(contrast(theme.link, theme.bg) >= 4.5, `${name}: links on the page`);
    assert.ok(contrast(theme.link, theme.soft) >= 4.5, `${name}: links on a tinted section`);
    assert.ok(contrast(theme['on-accent'], theme.accent) >= 4.5, `${name}: button text`);
  }
});

test('no text is set smaller than 15px, and body text is at least 18px', () => {
  for (const [, size, unit] of css.matchAll(/font-size:\s*([\d.]+)(rem|px|em)/g)) {
    const px = unit === 'px' ? Number(size) : Number(size) * 16;
    assert.ok(px >= 15 || unit === 'em', `font-size ${size}${unit} is under 15px`);
  }
  const body = css.match(/body \{[^}]*font:\s*400\s*([\d.]+)rem/);
  assert.ok(body && Number(body[1]) * 16 >= 18, 'body text is under 18px');
});

test('every file the stylesheet names exists, and no font comes from another site', () => {
  const urls = [...css.matchAll(/url\(["']?([^"')]+)["']?\)/g)].map((m) => m[1]);
  assert.ok(urls.length >= 8, 'the stylesheet names its typefaces and the sky pictures');
  for (const value of urls) {
    assert.ok(!/^(https?:)?\/\//.test(value), `${value} comes from another site`);
    assert.ok(fs.existsSync(path.join(root, value)), `styles.css names a missing file: ${value}`);
  }
  assert.ok(!/@import/.test(css), 'the stylesheet imports nothing');
});

test('the menu opens and closes on a narrow screen, and the pages work without it', () => {
  const page = PAGES[0];
  const dom = new JSDOM(read(page.file), { url: page.url, runScripts: 'outside-only' });
  dom.window.eval(read('script.js'));
  const { document } = dom.window;
  const toggle = document.querySelector('.menu-toggle');
  const nav = document.getElementById('main-nav');
  assert.ok(document.documentElement.classList.contains('menu-ready'));
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  toggle.click();
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  assert.ok(nav.classList.contains('is-open'));
  document.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape' }));
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(document.activeElement, toggle);
  toggle.click();
  document.querySelector('main').dispatchEvent(new dom.window.Event('pointerdown', { bubbles: true }));
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.ok(!/<script(?![^>]*(?:\bsrc=|application\/ld\+json))/.test(read(page.file)), 'the page carries no inline script');
  assert.ok(document.querySelector('.faq details'), 'the questions are details elements, so they work without script');
});

test('the privacy policy runs no script and both home pages link to it', () => {
  assert.equal(load(PAGES[2]).querySelectorAll('script').length, 0);
  for (const page of [...HOME, ...GUIDE]) {
    assert.ok(load(page).querySelector('footer a[href="/privacy/"]'), `${page.file} has no link to the privacy policy`);
  }
});

test('every invented product has its pictures in both themes, and the pages say the first one is an example', () => {
  const examples = JSON.parse(read('tools/examples.json')).products;
  for (const key of Object.keys(examples)) {
    for (const theme of ['light', 'dark']) assert.ok(fs.existsSync(path.join(root, `assets/examples/${key}-${theme}.webp`)), `${key}-${theme}`);
  }
  for (const page of HOME) {
    const d = load(page);
    assert.ok(d.querySelector('#examples .section-lead').textContent.length > 60, page.file);
    assert.ok(d.querySelector('.stage figcaption'), `${page.file}: the first picture says nothing about being an example`);
  }
});

test('every film in the guide has a still, a size small enough to load, and a caption', () => {
  for (const page of GUIDE) {
    const d = load(page);
    const dir = path.dirname(path.join(root, page.file));
    const demos = [...d.querySelectorAll('[data-demo]')];
    assert.ok(demos.length >= 5, `${page.file} films too little of the app`);
    for (const demo of demos) {
      const name = demo.dataset.demo;
      const image = demo.querySelector('picture img');
      const still = demo.querySelector('picture source[media*="prefers-reduced-motion"]');
      assert.ok(image && /\.gif$/.test(image.getAttribute('src')), `${page.file}: ${name} is not a GIF`);
      assert.ok(image.getAttribute('alt').length > 60, `${page.file}: ${name} does not describe what happens`);
      assert.ok(still && fs.existsSync(path.resolve(dir, still.getAttribute('srcset'))), `${page.file}: ${name} has no still for a reader who asked for less motion`);
      assert.ok(demo.querySelector('figcaption').textContent.length > 20, `${page.file}: ${name} has no caption`);
      const gif = path.resolve(dir, image.getAttribute('src'));
      assert.ok(fs.statSync(gif).size < 2.5 * 1024 * 1024, `${page.file}: ${path.basename(gif)} is over 2.5 MB`);
    }
    for (const a of d.querySelectorAll('.toc a')) {
      assert.ok(d.getElementById(a.getAttribute('href').slice(1)), `${page.file}: the contents name ${a.getAttribute('href')}, which is not there`);
    }
    assert.ok(!/<script(?![^>]*(?:\bsrc=|application\/ld\+json))/.test(read(page.file)), `${page.file} carries an inline script`);
  }
});

test('the pause button swaps the film for its still and back, and starts paused for a reader who asked for less motion', () => {
  const run = (reduced) => {
    const dom = new JSDOM(read(GUIDE[0].file), { url: GUIDE[0].url, runScripts: 'outside-only' });
    if (reduced) dom.window.matchMedia = () => ({ matches: true });
    dom.window.eval(read('script.js'));
    return dom.window.document;
  };
  const first = (d) => {
    const demo = d.querySelector('[data-demo]');
    return { image: demo.querySelector('img'), button: demo.querySelector('.demo-toggle') };
  };

  let d = run(false);
  assert.equal(d.querySelectorAll('.demo-toggle').length, d.querySelectorAll('[data-demo]').length);
  let { image, button } = first(d);
  const film = image.getAttribute('src');
  assert.equal(button.textContent, 'Pause');
  button.click();
  assert.match(image.getAttribute('src'), /-poster\.webp$/);
  assert.equal(button.textContent, 'Play');
  button.click();
  assert.equal(image.getAttribute('src'), film);
  assert.equal(button.textContent, 'Pause');

  d = run(true);
  ({ image, button } = first(d));
  assert.equal(button.textContent, 'Play', 'a reader who asked for less motion starts paused');
  button.click();
  assert.equal(image.getAttribute('src'), film);
  assert.equal(d.querySelector('[data-demo]').querySelector('picture source'), null, 'playing drops the still, so the film shows');
});

test('the Turkish guide has its buttons in Turkish', () => {
  const dom = new JSDOM(read(GUIDE[1].file), { url: GUIDE[1].url, runScripts: 'outside-only' });
  dom.window.eval(read('script.js'));
  const button = dom.window.document.querySelector('.demo-toggle');
  assert.equal(button.textContent, 'Duraklat');
  assert.match(button.getAttribute('aria-label'), /^Animasyonu duraklat: /);
});

// The pages under problems/ are written by tools/render_problems.py from the catalogs.
const generated = () => ['problems', 'tr/problems'].flatMap(function walk(dir) {
  return fs.readdirSync(path.join(root, dir), { withFileTypes: true }).flatMap((entry) => {
    const next = `${dir}/${entry.name}`;
    return entry.isDirectory() ? walk(next) : [next];
  });
}).filter((file) => file.endsWith('index.html'));

test('every generated problem page is complete, points at its twin, runs no script and names a source for each claim', () => {
  const files = generated();
  assert.ok(files.length >= 4, 'there are no generated problem pages');
  const stylesheet = crypto.createHash('sha256').update(fs.readFileSync(path.join(root, 'styles.css'))).digest('hex').slice(0, 12);
  for (const file of files) {
    const url = `https://kriko.cc/${file.replace(/index\.html$/, '')}`;
    const d = new JSDOM(read(file), { url }).window.document;
    assert.equal(d.documentElement.lang, file.startsWith('tr/') ? 'tr' : 'en', file);
    assert.equal(d.querySelectorAll('h1').length, 1, `${file} needs exactly one h1`);
    assert.ok(d.querySelector('meta[name="description"]').content.length > 40, file);
    assert.equal(d.querySelector('link[rel="canonical"]').href, url);
    // The only script is structured data for a search engine: JSON that parses, never code.
    for (const script of d.querySelectorAll('script')) {
      assert.equal(script.type, 'application/ld+json', `${file} runs a script`);
      assert.ok(JSON.parse(script.textContent)['@context'], `${file}: its structured data names no context`);
    }
    assert.ok(d.querySelector('script[type="application/ld+json"]'), `${file} has no structured data`);
    assert.ok(d.querySelector('meta[name="twitter:title"]') && d.querySelector('meta[property="og:locale"]'), `${file} is missing its social tags`);
    assert.ok(d.querySelector('link[rel="stylesheet"]').href.endsWith(`/styles.css?v=${stylesheet}`), `${file}: the stylesheet hash is stale`);
    for (const alternate of d.querySelectorAll('link[rel="alternate"][hreflang]')) {
      const twin = new URL(alternate.href).pathname.replace(/^\//, '');
      if (alternate.hreflang !== 'x-default') assert.ok(fs.existsSync(path.join(root, twin, 'index.html')), `${file} points at ${twin}, which does not exist`);
    }
    for (const claim of d.querySelectorAll('.claim')) {
      assert.ok(claim.querySelector('.src a[href^="http"]'), `${file}: a claim names no source`);
    }
  }
});

test('every problem page is reached from the hub in the same language, and no link inside them is dead', () => {
  for (const [prefix, hub] of [['', 'problems/index.html'], ['tr/', 'tr/problems/index.html']]) {
    const seen = new Set([hub]);
    const queue = [hub];
    while (queue.length) {
      const file = queue.shift();
      const d = new JSDOM(read(file), { url: `https://kriko.cc/${file.replace(/index\.html$/, '')}` }).window.document;
      for (const a of d.querySelectorAll('main a[href^="/"]')) {
        const target = a.getAttribute('href').split('#')[0];
        if (!target.startsWith(`/${prefix}problems/`)) continue;
        const next = `${target.replace(/^\//, '')}index.html`;
        assert.ok(fs.existsSync(path.join(root, next)), `${file} links to ${target}, which does not exist`);
        if (!seen.has(next)) { seen.add(next); queue.push(next); }
      }
    }
    const own = generated().filter((file) => file.startsWith(`${prefix}problems/`));
    assert.deepEqual([...seen].sort(), own.sort(), `${prefix || 'en'}: a problem page is not reachable from the hub, or the hub points off the set`);
  }
});

test('the problem sitemap lists exactly the generated pages, and robots.txt names it', () => {
  assert.match(read('robots.txt'), /^Sitemap: https:\/\/kriko\.cc\/sitemap-problems\.xml$/m);
  const listed = [...read('sitemap-problems.xml').matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]).sort();
  assert.deepEqual(listed, generated().map((file) => `https://kriko.cc/${file.replace(/index\.html$/, '')}`).sort());
});

test('a product page answers the two questions a buyer asks, and names the pages behind its findings', () => {
  for (const [file, label, ask] of [['problems/mercedes-eqb/index.html', 'Mercedes EQB', /^What is known to go wrong with Mercedes EQB\?$/],
    ['tr/problems/mercedes-eqb/index.html', 'Mercedes EQB', /^Mercedes EQB ile ilgili bilinen sorunlar neler\?$/]]) {
    const product = new JSDOM(read(file)).window.document;
    const blocks = [...product.querySelectorAll('script')].map((s) => JSON.parse(s.textContent));
    const faq = blocks.find((block) => block['@type'] === 'FAQPage');
    assert.ok(faq, `${file} answers no question`);
    assert.equal(faq.mainEntity.length, 2, file);
    assert.match(faq.mainEntity[0].name, ask, `${file}: the first question is not the one a buyer types`);
    for (const question of faq.mainEntity) {
      assert.match(question.name, /\?$/, question.name);
      assert.ok(question.acceptedAnswer.text.length > 40, `${file}: ${question.name} has no answer`);
    }
    const article = blocks.find((block) => block['@type'] === 'Article');
    assert.equal(article.about.name, label, `${file}: the article is not about the product`);
    assert.ok(article.isPartOf, `${file}: the article belongs to no site`);
    // A declared citation that the page does not print would be a source only a machine sees.
    const printed = new Set([...product.querySelectorAll('.src a')].map((a) => a.getAttribute('href')));
    assert.ok(article.citation.length >= 3, `${file} cites ${article.citation.length} sources`);
    for (const url of article.citation) assert.ok(printed.has(url), `${file}: ${url} is cited but not on the page`);
  }
});

test('a product page says where it sits, with breadcrumbs that match what a reader sees', () => {
  const product = new JSDOM(read('problems/mercedes-eqb/index.html')).window.document;
  const blocks = [...product.querySelectorAll('script')].map((s) => JSON.parse(s.textContent));
  const crumbs = blocks.find((block) => block['@type'] === 'BreadcrumbList');
  assert.deepEqual(crumbs.itemListElement.map((item) => item.name), [...product.querySelectorAll('.crumb a')].map((a) => a.textContent).concat(['Mercedes EQB']));
  assert.match(blocks.find((block) => block['@type'] === 'Article').dateModified, /^\d{4}-\d{2}-\d{2}$/);
  assert.match(product.title, /safety risks/, 'a page that reports a fire names the risk in its title');
});

test('the sitemap says when each page was last checked, and the page of every safety report is listed', () => {
  const sitemap = read('sitemap-problems.xml');
  const days = [...sitemap.matchAll(/<lastmod>([^<]+)<\/lastmod>/g)].map((match) => match[1]);
  assert.ok(days.length > 100, 'the problem pages carry no lastmod');
  assert.ok(days.every((day) => /^\d{4}-\d{2}-\d{2}$/.test(day)), 'a lastmod is not a date');
  for (const url of ['https://kriko.cc/problems/safety/', 'https://kriko.cc/tr/problems/safety/']) assert.ok(sitemap.includes(`<loc>${url}</loc>`), url);
});

test('no sponsored box is on a home page, the guide or the privacy policy', () => {
  for (const file of ['index.html', 'tr/index.html', 'guide/index.html', 'tr/guide/index.html', 'privacy/index.html']) {
    assert.ok(!read(file).includes('class="sponsored"'), `${file} carries a sponsored box`);
  }
});

test('the privacy policy describes the sponsored boxes whenever any is listed, and says they load nothing', () => {
  const listed = JSON.parse(read('sponsors.json'));
  assert.ok(Array.isArray(listed));
  const policy = load(PAGES[2]);
  const section = policy.querySelector('#sponsored');
  if (listed.length) assert.ok(section, 'a sponsor is listed but the privacy policy does not name sponsored boxes');
  if (section) assert.match(section.nextElementSibling.textContent, /runs no script and sets no cookie/);
  assert.ok(!/no advertising\./.test(policy.querySelector('.short').textContent) || !listed.length, 'the policy still promises no advertising');
});

test('both home pages link to the problem pages in their own language', () => {
  for (const [page, href] of [[PAGES[0], '/problems/'], [PAGES[1], '/tr/problems/']]) {
    assert.ok(load(page).querySelector(`footer a[href="${href}"]`), `${page.file} has no footer link to ${href}`);
  }
});

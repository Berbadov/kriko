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
];
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const load = (page) => new JSDOM(read(page.file), { url: page.url }).window.document;
const css = read('styles.css');

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
  for (const page of PAGES.slice(0, 2)) {
    const d = load(page);
    const alternates = Object.fromEntries([...d.querySelectorAll('link[rel="alternate"]')].map((l) => [l.hreflang, l.href]));
    assert.equal(alternates.en, 'https://kriko.cc/');
    assert.equal(alternates.tr, 'https://kriko.cc/tr/');
    assert.equal(alternates['x-default'], 'https://kriko.cc/');
    assert.equal(d.querySelector('.language-switch [aria-current="page"]').lang, page.lang);
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

test('the menu opens and closes on a narrow screen, and the pages work without it', () => {
  const page = PAGES[0];
  const dom = new JSDOM(read(page.file), { url: page.url, runScripts: 'outside-only' });
  dom.window.eval(read('script.js'));
  const { document } = dom.window;
  const toggle = document.querySelector('.menu-toggle');
  const nav = document.getElementById('main-nav');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  toggle.click();
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  assert.ok(nav.classList.contains('is-open'));
  document.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape' }));
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.ok(!/<script(?![^>]*\bsrc=)/.test(read(page.file)), 'the page carries no inline script');
  assert.ok(document.querySelector('.faq details'), 'the questions are details elements, so they work without script');
});

test('the privacy policy runs no script and both home pages link to it', () => {
  assert.equal(load(PAGES[2]).querySelectorAll('script').length, 0);
  for (const page of PAGES.slice(0, 2)) {
    assert.ok(load(page).querySelector('footer a[href="/privacy/"]'), `${page.file} has no link to the privacy policy`);
  }
});

test('every invented product has its pictures in both themes, and the pages say the first one is an example', () => {
  const examples = JSON.parse(read('tools/examples.json')).products;
  for (const key of Object.keys(examples)) {
    for (const theme of ['light', 'dark']) assert.ok(fs.existsSync(path.join(root, `assets/examples/${key}-${theme}.webp`)), `${key}-${theme}`);
  }
  for (const page of PAGES.slice(0, 2)) {
    const d = load(page);
    assert.ok(d.querySelector('#examples .section-lead').textContent.length > 60, page.file);
    assert.ok(d.querySelector('.hero-shot figcaption'), `${page.file}: the first picture says nothing about being an example`);
  }
});

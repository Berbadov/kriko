// Builds the Turkish pages from the English ones and stamps asset versions.
//
//   node site/tools/render-locales.cjs
//
// Each English page in PAGES is a source, and its Turkish page is generated from it and
// `locales/tr.json`: every unit of text (a paragraph, a heading, a button's
// label, a list item) is looked up whole, as written in the English page, so a
// sentence with a bold word in it is translated as one sentence and not in
// pieces. A unit with no translation is reported, and the build fails.
// The same step puts a content hash on the stylesheet and script of every
// page, so a visitor with an old copy cached gets the new one.
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { JSDOM } = require('jsdom');

const root = path.resolve(__dirname, '..');
const translations = JSON.parse(fs.readFileSync(path.join(root, 'locales/tr.json'), 'utf8'));

// `meta` names the entry of tr.json that holds the page's title, description and share text.
const PAGES = [
  { source: 'index.html', output: 'tr/index.html', canonical: 'https://kriko.cc/tr/', meta: '@meta' },
  { source: 'guide/index.html', output: 'tr/guide/index.html', canonical: 'https://kriko.cc/tr/guide/', meta: '@meta:guide' },
];
// Pages with no Turkish version still carry the hashes.
const STAMPED = [...PAGES.map((page) => page.source), 'privacy/index.html', '404.html'];
// A link to one of these goes to the Turkish version of it; /privacy/ is English only.
const LOCALISED = /^\/(?:guide\/|problems\/)?(?:#.*)?$/;

const hash = (file) => createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex').slice(0, 12);

// 1. Content-hash the local stylesheet and script, in the page's own source text.
const ASSETS = ['styles.css', 'script.js'];
function stamp(file) {
  const target = path.join(root, file);
  let html = fs.readFileSync(target, 'utf8');
  const depth = file.split('/').length - 1;
  for (const asset of ASSETS) {
    // The 404 page answers at any address, so it names its files from the root.
    const prefix = file === '404.html' ? '/' : '../'.repeat(depth);
    const pattern = new RegExp(`((?:href|src)=")${prefix}${asset.replace('.', '\\.')}(?:\\?v=[0-9a-f]+)?(")`, 'g');
    html = html.replace(pattern, `$1${prefix}${asset}?v=${hash(asset)}$2`);
  }
  fs.writeFileSync(target, html);
}
for (const file of STAMPED) if (fs.existsSync(path.join(root, file))) stamp(file);

// 2. Turkish.
const missing = new Set();
const BLOCKS = 'p,h1,h2,h3,ul,ol,li,div,section,details,figure,nav,header,footer,main,table';

// Numbers, language codes and the product's own name read the same in both languages.
const SAME = /^(?:[\d\s.,/+·-]+|EN|TR|Kriko|GitHub)$/;

function translateUnit(element) {
  const key = element.innerHTML.trim();
  if (SAME.test(key)) return;
  if (translations[key] === undefined) { missing.add(key); return; }
  element.innerHTML = translations[key];
}

function walk(node) {
  for (const child of [...node.children]) {
    if (['SCRIPT', 'STYLE', 'SVG', 'PICTURE'].includes(child.tagName.toUpperCase())) continue;
    const hasText = [...child.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (hasText && !child.querySelector(BLOCKS)) translateUnit(child);
    else walk(child);
  }
}

function render({ source, output, canonical, meta: metaKey }) {
  const dom = new JSDOM(fs.readFileSync(path.join(root, source), 'utf8'));
  const document = dom.window.document;
  walk(document.body);

  for (const el of document.querySelectorAll('[alt], [aria-label], [data-demo]')) {
    for (const attribute of ['alt', 'aria-label', 'data-demo']) {
      const value = el.getAttribute(attribute);
      if (value === null || value === '' || SAME.test(value)) continue;
      if (translations[value] === undefined) { missing.add(value); continue; }
      el.setAttribute(attribute, translations[value]);
    }
  }

  const meta = translations[metaKey];
  if (!meta) { missing.add(metaKey); return; }
  document.documentElement.lang = 'tr';
  document.title = meta.title;
  document.querySelector('meta[name="description"]').content = meta.description;
  document.querySelector('meta[property="og:title"]').content = meta['og:title'];
  document.querySelector('meta[property="og:description"]').content = meta['og:description'];
  document.querySelector('meta[property="og:url"]').content = canonical;
  document.querySelector('meta[property="og:image:alt"]').content = meta['og:image:alt'];
  document.querySelector('link[rel="canonical"]').href = canonical;
  for (const a of document.querySelectorAll('.language-switch a')) {
    if (a.lang === 'tr') a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  // The links that stay on this site lead to its Turkish pages. The language switch is how a
  // reader gets back, so it keeps the English address.
  for (const a of document.querySelectorAll('a[href]')) {
    if (a.closest('.language-switch')) continue;
    const href = a.getAttribute('href');
    if (LOCALISED.test(href)) a.setAttribute('href', `/tr${href}`);
  }

  // The Turkish page is one folder deeper than its source, so its relative paths go up one more.
  for (const el of document.querySelectorAll('[src], [href], [srcset], [poster]')) {
    for (const attribute of ['src', 'href', 'srcset', 'poster']) {
      const value = el.getAttribute(attribute);
      if (value && /^(\.\.\/|assets\/|styles\.css|script\.js)/.test(value)) el.setAttribute(attribute, `../${value}`);
    }
  }

  fs.mkdirSync(path.dirname(path.join(root, output)), { recursive: true });
  fs.writeFileSync(path.join(root, output), dom.serialize());
}

for (const page of PAGES) render(page);

if (missing.size) {
  console.error(`${missing.size} text(s) have no Turkish translation in locales/tr.json:`);
  for (const key of missing) console.error(`  ${JSON.stringify(key)}`);
  process.exit(1);
}
console.log(`Rendered ${PAGES.length} Turkish pages. All text translated.`);

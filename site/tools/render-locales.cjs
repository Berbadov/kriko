// Run after editing index.html, examples.js or locales/tr.json.
// English is the source page; /tr/ is a fully rendered, no-JavaScript translation.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const context = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(root, 'examples.js'), 'utf8'), context);
const fields = vm.runInNewContext('(' + fs.readFileSync(path.join(root, 'script.js'), 'utf8').match(/const productFields = (\{[\s\S]*?\n  \});/)[1] + ')');
const translations = JSON.parse(fs.readFileSync(path.join(root, 'locales/tr.json'), 'utf8'));

function populate(document, lang) {
  const products = context.window.KRIKO_EXAMPLES[lang];
  const product = products.laptop;
  for (const [key, selectors] of Object.entries(fields)) {
    for (const selector of selectors) document.querySelector(selector).textContent = product.fields[key];
  }
  document.querySelectorAll('.listing-specs span').forEach((el, i) => { el.textContent = product.specs[i]; });
  document.querySelectorAll('[data-art]').forEach(el => { el.toggleAttribute('hidden', el.dataset.art !== 'laptop'); });
  document.querySelectorAll('.product-option').forEach(el => { el.setAttribute('aria-pressed', String(el.dataset.product === 'laptop')); });
  document.querySelectorAll('.product-example').forEach(el => {
    el.classList.toggle('is-selected', el.dataset.product === 'laptop');
    el.querySelector('h3').textContent = products[el.dataset.product].fields.name;
  });
  document.querySelectorAll('.evidence-source').forEach((el, i) => {
    const source = product.sources[i];
    el.querySelector('.source-initial').textContent = source.initial;
    el.querySelector('strong').textContent = source.label;
    el.querySelector('strong + span').textContent = source.detail;
    el.querySelector('.source-excerpt').textContent = source.excerpt;
  });
  document.querySelector('.hero-visual').setAttribute('aria-label', lang === 'tr' ? 'Dizüstü A için temsili Kriko önizlemesi' : 'Illustrative Kriko preview for Laptop A');
}

const english = new JSDOM(fs.readFileSync(path.join(root, 'index.html'), 'utf8'));
populate(english.window.document, 'en');
fs.writeFileSync(path.join(root, 'index.html'), english.serialize());
const turkish = new JSDOM(english.serialize());
const d = turkish.window.document;
const missing = new Set();
const attributes = ['aria-label', 'alt', 'title'];
function translate(value) {
  const key = value.trim();
  if (!key || /^[\d\s/↗↓+♡?€∞.]+$/.test(key) || ['EN', 'TR', 'EN + TR', 'GitHub ↗', 'Kriko', 'k', 'S', 'C / 01', 'Q / ∞', 'Quick look', 'Windows', '16 GB RAM', '256 GB SSD'].includes(key)) return value;
  if (translations[key] === undefined) { missing.add(key); return value; }
  return value.replace(key, translations[key]);
}
function walk(node) {
  for (const child of node.childNodes) {
    if (child.nodeType === 3) child.textContent = translate(child.textContent);
    else if (child.nodeType === 1 && !['SCRIPT', 'STYLE', 'SVG'].includes(child.tagName)) {
      for (const attr of attributes) if (child.hasAttribute(attr)) child.setAttribute(attr, translate(child.getAttribute(attr)));
      walk(child);
    }
  }
}
// Dynamic example fields are translated from their own structured dataset.
const dynamic = new Set(Object.values(context.window.KRIKO_EXAMPLES.en.laptop.fields));
for (const item of context.window.KRIKO_EXAMPLES.en.laptop.sources) Object.values(item).forEach(x => dynamic.add(x));
for (const product of Object.values(context.window.KRIKO_EXAMPLES.en)) dynamic.add(product.fields.name);
context.window.KRIKO_EXAMPLES.en.laptop.specs.forEach(x => dynamic.add(x));
walk(d.body);
populate(d, 'tr');
d.documentElement.lang = 'tr';
d.title = 'Kriko — Satın almadan önce neye bakacağını bil.';
const description = 'Sıfır veya ikinci el ürünlerde gözden kaçan ayrıntıları keşfet. Kriko, kullanıcı deneyimlerini ve onarım bulgularını kaynaklarıyla birlikte araştırır.';
d.querySelector('meta[name="description"]').content = description;
d.querySelector('meta[property="og:title"]').content = 'Kriko — İlan, hikâyenin yarısını anlatır.';
d.querySelector('meta[property="og:description"]').content = description;
d.querySelector('link[rel="canonical"]').href = 'https://kriko.cc/tr/';
d.querySelector('.language-switch [lang="en"]').removeAttribute('aria-current');
d.querySelector('.language-switch [lang="tr"]').setAttribute('aria-current', 'page');
for (const el of d.querySelectorAll('[src], link[rel="stylesheet"]')) {
  const attr = el.hasAttribute('src') ? 'src' : 'href';
  const value = el.getAttribute(attr);
  if (value && !/^(https?:|\/|#)/.test(value)) el.setAttribute(attr, '../' + value);
}
d.querySelector('link[rel="icon"]').setAttribute('href', '../assets/icon-32.png');
d.querySelector('meta[property="og:image"]').content = 'https://kriko.cc/assets/icon-128.png';
fs.mkdirSync(path.join(root, 'tr'), { recursive: true });
fs.writeFileSync(path.join(root, 'tr/index.html'), turkish.serialize());
const untranslated = [...missing].filter(x => !dynamic.has(x) && !x.startsWith('Illustrative Kriko preview'));
if (untranslated.length) {
  console.error('Missing Turkish translations:', JSON.stringify(untranslated, null, 2));
  process.exitCode = 1;
} else console.log('Rendered English and Turkish pages. All static text translated.');

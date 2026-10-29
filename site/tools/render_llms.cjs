// Write llms.txt: the site as one page a language model can read.
//
//   node site/tools/render_llms.cjs
//
// The file at https://kriko.cc/llms.txt is the plain-text map answer engines look
// for before they crawl: what Kriko is, where the substance is, and how to cite
// it. It is built from the problem pages the site actually publishes, not from a
// list kept by hand, so a catalog that gains a page gains its line here and a
// category that disappears takes its line with it. Nothing is dated and nothing
// is random, so a second run changes no byte; the site test fails when the file
// is stale, which is the reminder to run this after `render_problems.py`.
//
// Read by `site/tests/site.test.cjs`; see https://llmstxt.org for the shape.

const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const root = path.resolve(__dirname, '..');
const ORIGIN = 'https://kriko.cc';
const OUTPUT = 'llms.txt';

const clean = (value) => value.replace(/\s+/g, ' ').trim();
const load = (file) => new JSDOM(fs.readFileSync(path.join(root, file), 'utf8')).window.document;

// A category card on the hub: its name, how much it holds, and the products at the top of it.
function catalogues(document) {
  return [...document.querySelectorAll('.cards .card')].map((card) => {
    const href = card.getAttribute('href');
    const held = clean(card.querySelector('span').textContent);
    const products = clean(card.querySelector('small').textContent).replace(/\s*…$/, '');
    return {
      url: href.startsWith('http') ? href : ORIGIN + href,
      name: clean(card.querySelector('strong').textContent),
      held,
      counts: (held.match(/\d+/g) || []).map(Number),
      products,
    };
  });
}

function safety(document) {
  const link = document.querySelector('.all a');
  if (!link) return null;
  const count = (clean(link.textContent).match(/\d+/) || [])[0];
  return { url: ORIGIN + link.getAttribute('href'), count };
}

function render() {
  const english = load('problems/index.html');
  const turkish = load('tr/problems/index.html');
  const list = catalogues(english);
  if (list.length === 0) throw new Error('problems/index.html lists no catalogs: run render_problems.py first');
  const products = list.reduce((sum, item) => sum + (item.counts[0] || 0), 0);
  const reports = list.reduce((sum, item) => sum + (item.counts[1] || 0), 0);
  const risk = safety(english);
  const turkishCount = catalogues(turkish).length;

  const lines = [
    '# Kriko',
    '',
    '> Kriko is a free, open-source Windows app and browser extension that shows what is known to go wrong with the exact product you are looking at, with the source beside every finding.',
    '',
    'Kriko answers one question: what is known to go wrong with this specific product? It reads',
    'a listing in the browser, matches that product against installed catalogs of sourced reports,',
    'and shows the findings beside the page. Every finding links to the page it came from: owner',
    'forums, repair guides, workshop notices and official recalls. Catalog lookups run on the',
    "reader's computer and work offline. Online research uses an agent the reader chooses, and a",
    "paid provider bills that reader's own account. There is no account.",
    '',
    '- Platform: a 64-bit Windows desktop app, and a browser extension for Chrome, Edge and Brave.',
    '- Price: free and open source, MIT license.',
    "- Data: catalogs, history and the shortlist stay on the reader's computer.",
    '- Coverage: a product with no finding is a gap in coverage, not a clean record.',
    '- Languages: English at the addresses below; Turkish under /tr/.',
    '',
    '## Main pages',
    '- [Kriko](https://kriko.cc/): what Kriko is, how it works, and the Windows installer.',
    '- [How to use Kriko](https://kriko.cc/guide/): each step as a short film of the real app.',
    `- [Known problems](${ORIGIN}/problems/): ${list.length} catalogs, ${products} products and ${reports} sourced reports.`,
    risk ? `- [Product safety reports](${risk.url}): ${risk.count} products with a report of fire, explosion or shock.` : null,
    '- [Privacy](https://kriko.cc/privacy/): what stays on the computer and what online research sends.',
    '- [Source code](https://github.com/Berbadov/kriko): the MIT-licensed repository.',
    '- [Releases](https://github.com/Berbadov/kriko/releases): the installer and portable archive.',
    '',
    '## Known problems by catalog',
    'Each catalog page lists its products; each product page lists what is reported to go wrong with it, and links the page behind every finding.',
    '',
    ...list.map((item) => `- [${item.name}](${item.url}): ${item.held}.${item.products ? ` ${item.products} and more.` : ''}`),
    '',
    '## Turkish',
    `- [Kriko (Türkçe)](${ORIGIN}/tr/): the home page in Turkish.`,
    `- [Bilinen sorunlar](${ORIGIN}/tr/problems/): ${turkishCount} kategori, ürün bazında kaynaklı sorunlar.`,
    `- [Kullanım kılavuzu](${ORIGIN}/tr/guide/): her adımın kısa bir filmi.`,
    '',
    '## How to cite',
    '- Cite the product page and the source page named under the finding; every finding links to both.',
    '- A finding is a sourced report, not a diagnosis of one unit. When the wording matters, quote the source, not the catalog.',
    '- A product page with no findings is a coverage gap, not a clean record.',
    '',
  ];

  return lines.filter((line) => line !== null).join('\n');
}

const text = render();
const target = path.join(root, OUTPUT);
fs.writeFileSync(target, text);
console.log(`Wrote ${OUTPUT}: ${text.split('\n').length} lines.`);

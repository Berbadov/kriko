// Structured data for the hand-built pages, read from the text a reader sees.
//
//   node site/tools/render-locales.cjs   (calls this, then writes the pages)
//
// A search engine can read a slogan and guess. An answer engine has to be told,
// in its own words, what Kriko is, what it costs, which platform it runs on and
// what the page's questions and steps are. Every statement here is therefore
// derived from the page itself: the FAQ questions are the <summary> lines, the
// guide steps are the sections the reader scrolls through, and the installer
// address is the download button already on the page.
//
// Because the page is the source, the Turkish page gets Turkish statements with
// no second copy to keep in step, and the schema cannot describe a FAQ the
// reader cannot see. `site/tests/site.test.cjs` holds both to that.
//
// The block is marked (`data-kriko-schema`) so a re-run replaces it instead of
// stacking a second one. Nothing here invents a fact: there is no rating, no
// review count and no version, because those are not on the page.

const ORIGIN = 'https://kriko.cc';
const MARK = 'data-kriko-schema';
const fs = require('node:fs');

const text = (element) => (element ? element.textContent.replace(/\s+/g, ' ').trim() : '');
const meta = (document, selector) => {
  const element = document.querySelector(selector);
  return element ? (element.getAttribute('content') || text(element)).trim() : '';
};
const absolute = (href) => (href && /^https?:/.test(href) ? href : href ? ORIGIN + href : undefined);

const organisation = (description) => ({
  '@type': 'Organization',
  '@id': `${ORIGIN}/#organization`,
  name: 'Kriko',
  url: `${ORIGIN}/`,
  logo: `${ORIGIN}/assets/icon-128.png`,
  description,
  sameAs: ['https://github.com/Berbadov/kriko'],
});

const website = (description) => ({
  '@type': 'WebSite',
  '@id': `${ORIGIN}/#website`,
  name: 'Kriko',
  url: `${ORIGIN}/`,
  inLanguage: ['en', 'tr'],
  description,
  publisher: { '@id': `${ORIGIN}/#organization` },
});

// The FAQ the reader can open, question for question.
function faq(document) {
  const questions = [...document.querySelectorAll('.faq details')]
    .map((item) => ({
      '@type': 'Question',
      name: text(item.querySelector('summary')),
      acceptedAnswer: {
        '@type': 'Answer',
        text: [...item.querySelectorAll('p')].map(text).join(' ').trim(),
      },
    }))
    .filter((question) => question.name && question.acceptedAnswer.text);
  return questions.length ? { '@type': 'FAQPage', mainEntity: questions } : null;
}

// The guide's own sections: the heading, the first paragraph of each, and its anchor.
function howTo(document, url) {
  const steps = [...document.querySelectorAll('.guide-step')]
    .map((section) => {
      const paragraph = [...section.querySelectorAll('.guide-copy p')].find((p) => !p.classList.contains('label'));
      return {
        '@type': 'HowToStep',
        name: text(section.querySelector('h2')),
        text: text(paragraph),
        url: section.id ? `${url}#${section.id}` : url,
      };
    })
    .filter((step) => step.name && step.text);
  if (steps.length < 2) return null;
  return {
    '@type': 'HowTo',
    name: text(document.querySelector('h1')),
    description: meta(document, 'meta[name="description"]'),
    inLanguage: document.documentElement.lang || 'en',
    url,
    step: steps,
  };
}

function breadcrumb(trail) {
  return {
    '@type': 'BreadcrumbList',
    itemListElement: trail.map(([name, item], index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name,
      ...(item ? { item } : {}),
    })),
  };
}

// The home page's product: free, for Windows, with a real download behind it.
function softwareApplication(document, lang, url) {
  const installer = [...document.querySelectorAll('a[href$="-setup.exe"]')].map((a) => a.getAttribute('href'))[0];
  const guide = url.startsWith(`${ORIGIN}/tr/`) ? `${ORIGIN}/tr/guide/` : `${ORIGIN}/guide/`;
  return {
    '@type': 'SoftwareApplication',
    '@id': `${ORIGIN}/#app`,
    name: 'Kriko',
    applicationCategory: 'UtilitiesApplication',
    applicationSubCategory: 'Product research',
    operatingSystem: 'Windows',
    inLanguage: lang,
    description: meta(document, 'meta[name="description"]'),
    url: `${ORIGIN}/`,
    downloadUrl: absolute(installer),
    softwareHelp: guide,
    license: 'https://github.com/Berbadov/kriko/blob/main/LICENSE',
    isAccessibleForFree: true,
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
    publisher: { '@id': `${ORIGIN}/#organization` },
  };
}

// One @graph per page: the entity, the site, and whatever the page itself says.
function graph(document, { url, lang, page, about }) {
  const description = meta(document, 'meta[name="description"]');
  const nodes = [organisation(about || description), website(description)];
  if (page === 'home') {
    nodes.push(softwareApplication(document, lang, url));
    const questions = faq(document);
    if (questions) nodes.push(questions);
  }
  if (page === 'guide') {
    const home = url.startsWith(`${ORIGIN}/tr/`) ? `${ORIGIN}/tr/` : `${ORIGIN}/`;
    nodes.push(breadcrumb([['Kriko', home], [text(document.querySelector('h1')), undefined]]));
    const steps = howTo(document, url);
    if (steps) nodes.push(steps);
  }
  return { '@context': 'https://schema.org', '@graph': nodes };
}

const json = (document, options) =>
  JSON.stringify(graph(document, options))
    // A `<` inside a string would close the script element early.
    .replace(/</g, '\\u003c');

function marked() {
  return `script[${MARK}]`;
}

// For a document already in memory (the Turkish page, built by render-locales).
function applyToDocument(document, options) {
  for (const old of document.querySelectorAll(marked())) old.remove();
  const head = document.head;
  // The source page ends its head with indentation; without this the new block
  // lands after a blank, space-filled line and a diff check calls it noise.
  while (head.lastChild && head.lastChild.nodeType === 3 && !head.lastChild.textContent.trim()) head.lastChild.remove();
  const script = document.createElement('script');
  script.setAttribute('type', 'application/ld+json');
  script.setAttribute(MARK, '');
  script.textContent = json(document, options);
  head.append('\n  ', script, '\n');
}

// For an English page, which stays hand-written: only the marked block moves,
// so a re-run leaves the rest of the file byte-for-byte as it was.
function applyToFile(document, file, options) {
  const block = `<script type="application/ld+json" ${MARK}>${json(document, options)}</script>`;
  let html = fs.readFileSync(file, 'utf8');
  html = html.replace(/\n?[ \t]*<script type="application\/ld\+json" data-kriko-schema(?:="")?>[\s\S]*?<\/script>/g, '');
  html = html.replace(/([ \t]*)<\/head>/, `  ${block}\n</head>`);
  fs.writeFileSync(file, html);
}

module.exports = { MARK, applyToDocument, applyToFile, graph, json };

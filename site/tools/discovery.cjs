// Build discovery data from the final page, after translation and link rewriting.
// Questions and answers have one source: the visible, server-delivered HTML.
const ORIGIN = 'https://kriko.cc';
const REPO = 'https://github.com/Berbadov/kriko';

function discovery(document) {
  const url = document.querySelector('link[rel="canonical"]').href;
  const lang = document.documentElement.lang;
  const home = `${ORIGIN}${lang === 'tr' ? '/tr/' : '/'}`;
  const page = {
    '@type': 'WebPage', '@id': `${url}#page`, url,
    name: document.title,
    description: document.querySelector('meta[name="description"]').content,
    inLanguage: lang, isPartOf: { '@id': `${ORIGIN}/#website` },
    about: { '@id': `${ORIGIN}/#app` },
  };
  const graph = [
    { '@type': 'Organization', '@id': `${ORIGIN}/#organization`, name: 'Kriko',
      url: `${ORIGIN}/`, sameAs: [REPO],
      logo: { '@type': 'ImageObject', url: `${ORIGIN}/assets/icon-128.png` } },
    { '@type': 'WebSite', '@id': `${ORIGIN}/#website`, url: `${ORIGIN}/`,
      name: 'Kriko', inLanguage: ['en', 'tr'], publisher: { '@id': `${ORIGIN}/#organization` } },
    { '@type': 'SoftwareApplication', '@id': `${ORIGIN}/#app`, name: 'Kriko',
      url: `${ORIGIN}/`, applicationCategory: 'UtilitiesApplication', operatingSystem: 'Windows',
      license: 'https://opensource.org/license/mit', sameAs: [REPO],
      publisher: { '@id': `${ORIGIN}/#organization` },
      ...(document.querySelector('a[href$="-setup.exe"]')
        ? { downloadUrl: document.querySelector('a[href$="-setup.exe"]').href } : {}),
    },
    page,
  ];
  const questions = [...document.querySelectorAll('.faq details')];
  if (questions.length) {
    page['@type'] = ['WebPage', 'FAQPage'];
    page.mainEntity = questions.map(el => ({
      '@type': 'Question', name: el.querySelector('summary').textContent.trim(),
      acceptedAnswer: { '@type': 'Answer', text: [...el.querySelectorAll('p')]
        .map(p => p.textContent.trim()).join('\n\n') },
    }));
  }
  if (url !== home) {
    const id = `${url}#breadcrumbs`;
    page.breadcrumb = { '@id': id };
    graph.push({ '@type': 'BreadcrumbList', '@id': id, itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Kriko', item: home },
      { '@type': 'ListItem', position: 2, name: document.querySelector('h1').textContent.trim(), item: url },
    ] });
  }
  return JSON.stringify({ '@context': 'https://schema.org', '@graph': graph }).replace(/</g, '\\u003c');
}

module.exports = { discovery };

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');

for (const file of ['index.html', 'tr/index.html', 'guide/index.html', 'tr/guide/index.html', 'install/index.html', 'tr/install/index.html']) {
  test(`${file}: crawlers receive localized entities and visible answers without running JavaScript`, () => {
    const d = new JSDOM(fs.readFileSync(path.join(root, file), 'utf8')).window.document;
    const graph = JSON.parse(d.querySelector('#discovery-data').textContent)['@graph'];
    const url = d.querySelector('link[rel="canonical"]').href;
    const page = graph.find(node => node['@id'] === `${url}#page`);
    assert.equal(page.inLanguage, d.documentElement.lang);
    assert.equal(page.name, d.title);
    assert.equal(page.description, d.querySelector('meta[name="description"]').content);
    assert.equal(page.isPartOf['@id'], 'https://kriko.cc/#website');
    const app = graph.find(node => node['@type'] === 'SoftwareApplication');
    assert.equal(app['@id'], 'https://kriko.cc/#app');
    const download = d.querySelector('a[href$="-setup.exe"]');
    if (download) assert.equal(app.downloadUrl, download.href);
    assert.equal(app.license, 'https://opensource.org/license/mit');
    const details = [...d.querySelectorAll('.faq details')];
    if (details.length) {
      assert.ok(page['@type'].includes('FAQPage'));
      assert.deepEqual(page.mainEntity.map(q => [q.name, q.acceptedAnswer.text]), details.map(el => [
        el.querySelector('summary').textContent.trim(),
        [...el.querySelectorAll('p')].map(p => p.textContent.trim()).join('\n\n'),
      ]));
      assert.ok(page.mainEntity.length >= 7);
    } else {
      const crumbs = graph.find(node => node['@type'] === 'BreadcrumbList');
      assert.equal(crumbs.itemListElement.at(-1).item, url);
    }
  });
}

test('structured data safely carries page text containing HTML delimiters', () => {
  const { discovery } = require('../tools/discovery.cjs');
  const d = new JSDOM(fs.readFileSync(path.join(root, 'index.html'), 'utf8')).window.document;
  const summary = d.querySelector('.faq summary');
  summary.textContent = '</script><script>unexpected()</script>';
  const data = discovery(d);
  assert.ok(!data.includes('<'));
  const graph = JSON.parse(data)['@graph'];
  assert.equal(graph.find(node => node['@type'].includes('FAQPage')).mainEntity[0].name, summary.textContent);
});

import assert from 'node:assert/strict';

import { fetchProductMetadata, parseProductMetadata, validHttpsUrl } from '../src/engine/products';
import { runTurn, type Completion } from '../src/engine/providers';

assert.equal(validHttpsUrl('http://shop.example/item'), '');
assert.equal(validHttpsUrl('https://localhost/item'), '');
assert.equal(validHttpsUrl('https://192.168.1.2/item'), '');
assert.equal(validHttpsUrl('https://shop.example/item'), 'https://shop.example/item');
assert.equal(validHttpsUrl('https://fc-moto.de/item'), 'https://fc-moto.de/item');
assert.equal(parseProductMetadata('<meta property="og:image" content="javascript:alert(1)">'), null);
assert.deepEqual(parseProductMetadata('<meta property="og:image" content="https://cdn.example/p.jpg?x=1&amp;y=2"><meta property="product:price:amount" content="19.99"><meta property="product:price:currency" content="EUR">'), {
  imageUrl: 'https://cdn.example/p.jpg?x=1&y=2', price: 'EUR 19.99',
});
assert.deepEqual(parseProductMetadata('<meta property="og:image" content="/images/item.jpg">', 'https://shop.example/products/42'), {
  imageUrl: 'https://shop.example/images/item.jpg',
});
assert.deepEqual(parseProductMetadata('<script type="application/ld+json">{"@type":"Product","image":"https://cdn.example/p.png","offers":{"price":12,"priceCurrency":"USD"}}</script>'), {
  imageUrl: 'https://cdn.example/p.png', price: 'USD 12',
});
assert.equal(parseProductMetadata('<meta property="og:image" content="https://cdn.example/&#999999999999999999999;.jpg">'), null);

class FakeXHR {
  static instance: FakeXHR;
  static nextResponseURL = 'https://shop.example/item';
  static throwOnSend = false;
  readyState = 0;
  status = 200;
  responseURL = FakeXHR.nextResponseURL;
  responseText = '<meta property="og:image" content="https://cdn.example/item.jpg">';
  onprogress: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;
  onreadystatechange: (() => void) | null = null;
  open() {}
  setRequestHeader() {}
  getResponseHeader() { return 'text/html; charset=utf-8'; }
  send() {
    if (FakeXHR.throwOnSend) throw new Error('native XHR send failed');
    this.onprogress?.(); this.readyState = 4; this.onreadystatechange?.();
  }
  abort() { this.onabort?.(); }
  constructor() { FakeXHR.instance = this; }
}

async function main() {
  const original = globalThis.XMLHttpRequest;
  // Hermes supplies XHR even when fetch Response.body.getReader is unavailable.
  globalThis.XMLHttpRequest = FakeXHR as unknown as typeof XMLHttpRequest;
  try {
    assert.deepEqual(await fetchProductMetadata('https://shop.example/item'), { imageUrl: 'https://cdn.example/item.jpg' });
    FakeXHR.nextResponseURL = 'https://attacker.example/item';
    assert.equal(await fetchProductMetadata('https://shop.example/item'), null, 'cross-host redirects are rejected');
    FakeXHR.nextResponseURL = 'https://shop.example/category';
    assert.equal(await fetchProductMetadata('https://shop.example/item'), null, 'same-host redirects to a different listing are rejected');
    FakeXHR.nextResponseURL = 'https://shop.example/item';
    FakeXHR.throwOnSend = true;
    assert.equal(await fetchProductMetadata('https://shop.example/item'), null, 'synchronous transport errors do not fail research');
    FakeXHR.throwOnSend = false;

    let round = 0;
    let preferencePrompt = '';
    const tool: Completion = { text: '', finish: 'tool_calls', toolCalls: [{
      id: 'products-1', name: 'search', arguments: JSON.stringify({ query: 'portable espresso maker', kind: 'products' }),
    }], usage: { promptTokens: 10, completionTokens: 2, totalTokens: 12 } };
    const answer: Completion = { text: 'A candidate listing is available. [1]', finish: 'stop', toolCalls: [],
      usage: { promptTokens: 20, completionTokens: 4, totalTokens: 24 } };
    const result = await runTurn({
      keys: { mercury: 'mercury', deepseek: 'deepseek' }, history: [], question: 'Find a portable espresso maker.',
      researchPreferences: { products: ['quiet laptop', 'USB-C monitor'], sourceCount: 8, includeIsolated: false, includeOneTimeIssues: false },
    }, {
      complete: async (request) => {
        preferencePrompt = String(request.messages[0]?.content ?? '');
        return ++round === 1 ? tool : answer;
      },
      search: async () => ({ error: '', hits: [{ url: 'https://shop.example/item', title: 'Portable espresso maker', snippet: '', pageText: 'Listing details '.repeat(20) }] }),
      fetch: async () => ({ title: '', pageText: '', error: '' }),
    });
    assert.match(preferencePrompt, /up to 8 distinct useful source URLs/);
    assert.match(preferencePrompt, /quiet laptop; USB-C monitor/);
    assert.equal(result.sources[0]?.productCard, true);
    assert.equal(result.sources[0]?.productImageUrl, 'https://cdn.example/item.jpg');
    assert.deepEqual(result.usage, { promptTokens: 30, completionTokens: 6, totalTokens: 36 });
    assert.ok(result.steps.some((step) => step.text === 'diagnostic:tokens:30:6:36'));
  } finally {
    globalThis.XMLHttpRequest = original;
  }
  console.log('product metadata checks passed');
}

void main();

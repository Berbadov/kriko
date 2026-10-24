/** Deterministic offline checks for the mobile agent's bounded research loop.
 * Run after compiling this file and its imports to CommonJS with TypeScript.
 */

import assert from 'node:assert/strict';

import { runTurn, type Completion, type MercuryRequest } from '../src/engine/providers';
import { isReviewSiteUrl, normalizeReviewSite, resolveReviewSite, scopeReviewQuery } from '../src/engine/reviews';

const keys = { mercury: 'test-mercury', deepseek: 'test-search' };
const baseRequest = {
  keys,
  history: [],
  question: 'What should I check before buying this product?',
};

function tool(query: string, id = `search-${query}`): Completion {
  return {
    text: '',
    finish: 'tool_calls',
    toolCalls: [{ id, name: 'search', arguments: JSON.stringify({ query, kind: 'forums' }) }],
  };
}

function final(text = '**Verdict:** Check the documented failure record. **Check:** Verify the exact model.'):
  Completion {
  return { text, finish: 'stop', toolCalls: [] };
}

function requestTools(request: MercuryRequest): string[] {
  return request.tools.map((item) => {
    const root = item as { function?: { name?: string } };
    return root.function?.name ?? '';
  });
}

async function sufficientEvidenceStopsResearch(): Promise<void> {
  let completeCalls = 0;
  let searches = 0;
  const result = await runTurn(baseRequest, {
    complete: async (request) => {
      completeCalls += 1;
      assert.equal(requestTools(request).includes('search'), completeCalls === 1);
      return completeCalls === 1 ? tool('model failure forums') : final();
    },
    search: async () => {
      searches += 1;
      return {
        error: '',
        hits: [
          { url: 'https://owners.example.org/a', title: 'Owner report A', snippet: '', pageText: 'A'.repeat(240) },
          { url: 'https://repair.example.net/b', title: 'Repair report B', snippet: '', pageText: 'B'.repeat(240) },
          { url: 'https://owners.example.org/c', title: 'Owner report C', snippet: '', pageText: 'C'.repeat(240) },
        ],
      };
    },
    fetch: async () => ({ title: '', pageText: '', error: 'unused' }),
  });
  assert.equal(searches, 1, 'enough readable evidence should end retrieval early');
  assert.equal(result.searches, 1);
  assert.equal(result.text, '- **Verdict:** Check the documented failure record\n- **Check:** Verify the exact model');
  assert.equal(result.error, '');
}

async function duplicateAndShortPagesDoNotCountAsEvidence(): Promise<void> {
  let calls = 0;
  let searches = 0;
  const result = await runTurn(baseRequest, {
    complete: async (request) => {
      calls += 1;
      if (calls === 1) return tool('same pages');
      if (calls === 2) {
        assert.ok(request.tools.length > 0, 'weak snippets must not trigger early synthesis');
        return tool('next query');
      }
      return final('A clear answer.\n\nA separate paragraph with useful context.');
    },
    search: async (query) => {
      searches += 1;
      if (query === 'same pages') return { error: '', hits: [
        { url: 'https://owners.example.org/a', title: 'Owner report', snippet: 'x'.repeat(500), pageText: 'x'.repeat(220) },
        { url: 'https://owners.example.org/a', title: 'Duplicate owner report', snippet: '', pageText: 'x'.repeat(220) },
        { url: 'https://repair.example.net/b', title: 'Repair report', snippet: 'Short snippet only', pageText: 'tiny' },
      ] };
      return { error: '', hits: [
        { url: 'https://owners.example.org/a', title: 'Owner report', snippet: '', pageText: 'x'.repeat(220) },
      ] };
    },
    fetch: async () => ({ title: '', pageText: '', error: 'unused' }),
  });
  assert.equal(searches, 2);
  assert.equal(result.text, 'A clear answer.\n\nA separate paragraph with useful context.');
}

async function duplicateQueriesAndLowNoveltyAreCapped(): Promise<void> {
  const requests: MercuryRequest[] = [];
  const searched: string[] = [];
  const result = await runTurn(baseRequest, {
    complete: async (request) => {
      requests.push(request);
      if (requests.length === 1) return tool('repeat query', 's1');
      if (requests.length === 2) return tool('repeat query', 's2');
      if (requests.length === 3) return tool('empty query', 's3');
      return final();
    },
    search: async (query) => {
      searched.push(query);
      return query === 'repeat query'
        ? { error: '', hits: [{ url: 'https://forum.example.org/a', title: 'Thread', snippet: 'One result', pageText: '' }] }
        : { error: '', hits: [] };
    },
    fetch: async () => ({ title: '', pageText: '', error: 'unused' }),
  });
  assert.deepEqual(searched, ['repeat query', 'empty query'], 'a repeated query must reuse its first result');
  assert.equal(result.searches, 2, 'searches reports provider calls, not duplicate tool requests');
  assert.ok(requests.at(-1)?.tools.length === 0, 'low novelty should switch to synthesis');
  assert.equal(result.error, '');
  assert.ok(result.text.length > 0);
}

async function stubbornToolRequestGetsSynthesisRetry(): Promise<void> {
  let calls = 0;
  const result = await runTurn(baseRequest, {
    complete: async (request) => {
      calls += 1;
      if (calls === 1) return tool('one search');
      if (calls === 2) {
        assert.equal(request.tools.length, 0);
        return tool('another search');
      }
      assert.equal(request.tools.length, 0);
      return final();
    },
    search: async () => ({
      error: '',
      hits: [
        { url: 'https://owners.example.org/a', title: 'Owner report A', snippet: '', pageText: 'A'.repeat(240) },
        { url: 'https://repair.example.net/b', title: 'Repair report B', snippet: '', pageText: 'B'.repeat(240) },
        { url: 'https://owners.example.org/c', title: 'Owner report C', snippet: '', pageText: 'C'.repeat(240) },
      ],
    }),
    fetch: async () => ({ title: '', pageText: '', error: 'unused' }),
  });
  assert.equal(calls, 3, 'a model that asks for unavailable tools gets one explicit synthesis retry');
  assert.equal(result.error, '');
  assert.ok(result.text.length > 0);
}

async function oneRemainingLookupIsReservedForFetching(): Promise<void> {
  const toolSets: string[][] = [];
  let completes = 0;
  const result = await runTurn({ ...baseRequest, thoroughness: 0 }, {
    complete: async (request) => {
      completes += 1;
      toolSets.push(requestTools(request));
      if (completes === 1) {
        return {
          text: '',
          finish: 'tool_calls',
          toolCalls: [
            { id: 's1', name: 'search', arguments: JSON.stringify({ query: 'one' }) },
            { id: 's2', name: 'search', arguments: JSON.stringify({ query: 'two' }) },
          ],
        };
      }
      if (completes === 2) {
        assert.deepEqual(requestTools(request), ['fetch']);
        return {
          text: '',
          finish: 'tool_calls',
          toolCalls: [{ id: 'f1', name: 'fetch', arguments: JSON.stringify({ url: 'https://forum.example.org/one' }) }],
        };
      }
      return final();
    },
    search: async (query) => ({
      error: '',
      hits: [{
        url: `https://forum.example.org/${query}`,
        title: 'Search result',
        snippet: 'A snippet only',
        pageText: '',
      }],
    }),
    fetch: async () => ({ title: 'Readable page', pageText: 'Full page text', error: '' }),
  });
  assert.deepEqual(toolSets[1], ['fetch'], 'the last retrieval allowance should be narrowed to fetch');
  assert.equal(result.reads, 1);
  assert.equal(result.error, '');
  assert.ok(result.text.length > 0);
}

async function siteReviewModeRequiresAnExactSite(): Promise<void> {
  let completes = 0;
  let searches = 0;
  const result = await runTurn({
    ...baseRequest,
    researchMode: 'site_reviews',
    question: 'What do buyers say about this product?',
  }, {
    complete: async () => { completes += 1; return final(); },
    search: async () => { searches += 1; return { error: '', hits: [] }; },
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.match(result.error, /exact site/);
  assert.equal(completes, 0);
  assert.equal(searches, 0);
}

function reviewHostParsingIsExplicitAndBounded(): void {
  assert.equal(normalizeReviewSite('https://www.Store.Example.com/product/1'), 'store.example.com');
  assert.equal(normalizeReviewSite('https://user:secret@store.example.com/item'), '');
  assert.equal(resolveReviewSite('', undefined, 'Read comments on store.example.com'), 'store.example.com');
  assert.equal(resolveReviewSite('', undefined, 'Compare store.example.com and other.example'), '');
  assert.equal(scopeReviewQuery('long product model feedback', 'store.example.com'), 'long product model feedback site:store.example.com');
  assert.ok(isReviewSiteUrl('https://forum.store.example.com/reviews', 'store.example.com'));
  assert.ok(!isReviewSiteUrl('https://store.example.com.attacker.test/reviews', 'store.example.com'));
}

async function siteReviewSearchAndFetchStayOnThatHost(): Promise<void> {
  let completes = 0;
  let fetches = 0;
  let query = '';
  const result = await runTurn({
    ...baseRequest,
    researchMode: 'site_reviews',
    reviewSite: 'reviews.example.com',
    question: 'Summarize comments about this model.',
  }, {
    complete: async () => {
      completes += 1;
      if (completes === 1) return tool('model feedback');
      if (completes === 2) return {
        text: '', finish: 'tool_calls',
        toolCalls: [{
          id: 'offsite-fetch', name: 'fetch',
          arguments: JSON.stringify({ url: 'https://other.example/reviews/item' }),
        }],
      };
      return final('Buyers report mixed experiences [1].');
    },
    search: async (value) => {
      query = value;
      return { error: '', hits: [
        { url: 'https://shop.reviews.example.com/comments/1', title: 'Buyer comments', snippet: 'Comments', pageText: 'A'.repeat(240) },
        { url: 'https://other.example/review/2', title: 'Offsite review', snippet: 'Should be filtered', pageText: 'B'.repeat(500) },
      ] };
    },
    fetch: async () => { fetches += 1; return { title: '', pageText: '', error: '' }; },
  });
  assert.ok(query.includes('site:reviews.example.com'), 'every site review search must include its normalized site scope');
  assert.equal(fetches, 0, 'an offsite URL must not be fetched');
  assert.equal(result.searches, 1);
  assert.equal(result.sources.length, 1);
  assert.equal(result.sources[0].host, 'shop.reviews.example.com');
  assert.equal(result.error, '');
}

async function exactProductPageIsReadFirstAndCountsAsEvidence(): Promise<void> {
  let requestedUrl = '';
  let prompt = '';
  const result = await runTurn({
    ...baseRequest,
    researchMode: 'site_reviews',
    reviewSite: 'https://reviews.example.com/products/item-42',
    question: 'What do commenters on this product page say?',
  }, {
    complete: async (request) => {
      prompt = String(request.messages.at(-1)?.content ?? '');
      assert.equal(request.requireTools, false, 'a supplied product page is read before the model decides whether another search helps');
      return final('The page shows that commenters mention fit [1].');
    },
    search: async () => ({ error: '', hits: [] }),
    fetch: async (url) => {
      requestedUrl = url;
      return { title: 'Item 42 comments', pageText: 'Comment text. '.repeat(30), error: '' };
    },
  });
  assert.equal(requestedUrl, 'https://reviews.example.com/products/item-42');
  assert.ok(prompt.includes(requestedUrl), 'the exact supplied URL should be in the model context');
  assert.equal(result.reads, 1);
  assert.equal(result.searches, 0);
  assert.equal(result.unverified, false);
  assert.equal(result.sources.length, 1);
}

async function ordinaryFollowUpCanAnswerWithoutSearching(): Promise<void> {
  let searches = 0;
  const result = await runTurn({
    ...baseRequest,
    question: 'What did you mean by the second point?',
    history: [{
      id: 'prior', role: 'assistant', text: 'The second point was to confirm the warranty term.',
      createdAt: Date.now(),
    }],
  }, {
    complete: async (request) => {
      assert.equal(request.requireTools, false);
      return final('I meant checking how long the seller will honor the warranty.');
    },
    search: async () => { searches += 1; return { error: '', hits: [] }; },
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.equal(searches, 0);
  assert.equal(result.searches, 0);
  assert.equal(result.unverified, true);
  assert.equal(result.error, '');
}

async function retailerCommentsAreNotDiscardedAsMarketing(): Promise<void> {
  let rounds = 0;
  const result = await runTurn({ ...baseRequest, researchMode: 'site_reviews', reviewSite: 'amazon.com' }, {
    complete: async (request) => {
      if (++rounds === 1) return tool('product buyer comments');
      const messages = request.messages.filter((message) => message.role === 'tool');
      const evidence = JSON.parse(String(messages[0]?.content));
      assert.equal(evidence.results[0].url, 'https://www.amazon.com/product-reviews/example');
      assert.ok(!evidence.note.includes('identity or price only'), 'retailer-hosted customer comments must remain usable');
      return final('One buyer reported a charging issue; this is an isolated report. [1]');
    },
    search: async () => ({ error: '', hits: [{
      url: 'https://www.amazon.com/product-reviews/example', title: 'Buyer comments',
      snippet: '', pageText: 'Customer review: the charging case stopped working after a month. '.repeat(5),
    }] }),
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.equal(result.error, '');
  assert.equal(result.sources.length, 1);
}

async function main(): Promise<void> {
  await sufficientEvidenceStopsResearch();
  await duplicateAndShortPagesDoNotCountAsEvidence();
  await duplicateQueriesAndLowNoveltyAreCapped();
  await stubbornToolRequestGetsSynthesisRetry();
  await oneRemainingLookupIsReservedForFetching();
  await siteReviewModeRequiresAnExactSite();
  reviewHostParsingIsExplicitAndBounded();
  await siteReviewSearchAndFetchStayOnThatHost();
  await exactProductPageIsReadFirstAndCountsAsEvidence();
  await ordinaryFollowUpCanAnswerWithoutSearching();
  await retailerCommentsAreNotDiscardedAsMarketing();
  console.log('adaptive turn checks passed');
}

void main();

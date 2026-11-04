import assert from 'node:assert/strict';
import { runTurn, type Completion } from '../src/engine/providers';
import { classifyCheapQuestion } from '../src/engine/cheap-routing';
import { cacheAnswer, clearAnswerCache, getCachedAnswer } from '../src/engine/answer-cache';

const keys = { mercury: 'mercury-test', deepseek: 'deepseek-test', mistral: 'mistral-private-test' };
const answer: Completion = { text: 'A concise static answer.', finish: 'stop', toolCalls: [], usage: { promptTokens: 12, completionTokens: 5, totalTokens: 17 } };

async function routingAndCache(): Promise<void> {
  clearAnswerCache();
  assert.equal(classifyCheapQuestion('Translate bonjour to English'), 'ministral-8b-2512');
  assert.equal(classifyCheapQuestion('Rewrite this sentence: I has a book'), 'ministral-3b-2512');
  assert.equal(classifyCheapQuestion('Rewrite: Ürünü bugün gönder', 'tr'), 'ministral-8b-2512');
  assert.equal(classifyCheapQuestion('Translate “good morning” to Turkish'), 'ministral-8b-2512');
  assert.equal(classifyCheapQuestion('What is photosynthesis?'), 'ministral-8b-2512');
  assert.equal(classifyCheapQuestion('What is aspirin?'), null);
  assert.equal(classifyCheapQuestion('What is USD TRY exchange rate?'), null);
  assert.equal(classifyCheapQuestion('Açıkla: fotosentez'), 'ministral-8b-2512');
  for (const q of [
    'What is the latest price of this phone?', 'Explain my contract', 'What is a URL https://example.com',
    'How do I treat a headache?', 'What is the best laptop?', 'Summarize this page',
  ]) assert.equal(classifyCheapQuestion(q), null, q);

  let modelCalls = 0;
  let mercuryCalls = 0;
  const request = { keys, history: [], question: 'Define photosynthesis' };
  const first = await runTurn(request, {
    complete: async (input) => {
      modelCalls++;
      assert.equal(input.endpoint, 'https://api.mistral.ai/v1/chat/completions');
      assert.equal(input.model, 'ministral-3b-2512');
      assert.equal(input.tools.length, 0);
      assert.equal(input.includeReasoningEffort, false);
      assert.equal(input.maxTokens, 512);
      input.onUsage?.({ promptTokens: 12, completionTokens: 5, totalTokens: 17 });
      input.onUsage?.({ promptTokens: 12, completionTokens: 9, totalTokens: 21 });
      return answer;
    },
    search: async () => ({ error: '', hits: [] }),
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.equal(first.text, answer.text);
  assert.deepEqual(first.usage, { promptTokens: 12, completionTokens: 9, totalTokens: 21 }, 'cumulative SSE usage replaces earlier snapshots');
  const hit = await runTurn(request, {
    complete: async () => { modelCalls++; throw new Error('cache should bypass provider'); },
    search: async () => ({ error: '', hits: [] }),
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.equal(hit.text, answer.text);
  assert.equal(hit.usage, undefined, 'cache hits have no provider usage');
  assert.match(hit.steps[0].text, /cache/i);
  assert.equal(modelCalls, 1);

  let streamed = '';
  await runTurn({ ...request, question: 'Explain gravity', answerStyle: 'short', researchMode: 'research', thoroughness: 50,
    researchPreferences: { products: ['all'], sourceCount: 5, includeIsolated: false, includeOneTimeIssues: false },
    onText: (chunk) => { streamed += chunk; } }, {
    complete: async (input) => {
      assert.equal(input.model, 'ministral-8b-2512', 'ordinary store-supplied defaults still reach Mistral');
      return { ...answer, text: 'Gravity attracts masses.' };
    },
    search: async () => ({ error: '', hits: [] }),
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.equal(streamed, 'Gravity attracts masses.', 'successful fast answers satisfy the streaming callback once');

  await runTurn({ ...request, question: 'Rewrite: Ürünü bugün gönder', language: 'tr' }, {
    complete: async (input) => {
      assert.equal(input.model, 'ministral-8b-2512', 'Turkish rewrites route to the better-performing tier');
      return { ...answer, text: 'Ürün bugün gönderilir.' };
    },
    search: async () => ({ error: '', hits: [] }),
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });

  const isolated = await runTurn({ ...request, keys: { ...keys, mistral: 'different-key' } }, {
    complete: async () => { mercuryCalls++; return { text: 'Mercury fallback.', finish: 'stop', toolCalls: [] }; },
    search: async () => ({ error: '', hits: [] }),
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.equal(mercuryCalls, 1, 'a different credential cannot reuse the cached answer');
  assert.equal(isolated.text, 'Mercury fallback.');
}

async function bypassAndFallback(): Promise<void> {
  clearAnswerCache();
  const base = { keys, history: [], question: 'What is gravity?' };
  let cheapCalls = 0;
  let mercuryCalls = 0;
  const result = await runTurn(base, {
    complete: async (input) => {
      if (input.endpoint) { cheapCalls++; throw new Error('Mistral unavailable'); }
      mercuryCalls++;
      return { text: 'Mercury answer.', finish: 'stop', toolCalls: [] };
    },
    search: async () => ({ error: '', hits: [] }),
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.equal(result.text, 'Mercury answer.');
  assert.equal(cheapCalls, 1);
  assert.equal(mercuryCalls, 1);

  for (const refusal of ['This needs current information and research.', 'Bunun için araştırma gerekiyor.', 'I am not sure.', 'Emin değilim.']) {
    clearAnswerCache();
    let refusedFallbacks = 0;
    const refused = await runTurn(base, {
      complete: async (input) => input.endpoint
        ? { text: refusal, finish: 'stop', toolCalls: [] }
        : (refusedFallbacks++, { text: 'Mercury researched answer.', finish: 'stop', toolCalls: [] }),
      search: async () => ({ error: '', hits: [] }),
      fetch: async () => ({ title: '', pageText: '', error: '' }),
    });
    assert.equal(refusedFallbacks, 1, `small-model uncertainty falls through: ${refusal}`);
    assert.equal(refused.text, 'Mercury researched answer.');
  }

  const cases = [
    { ...base, history: [{ id: 'h', role: 'user' as const, text: 'private history', createdAt: 1 }] },
    { ...base, reading: { brand: '', product: 'Phone', model: '', price: '', condition: '', detail: '', note: '' } },
    { ...base, thoroughness: 75 },
    { ...base, researchPreferences: { products: ['laptops'], sourceCount: 3, includeIsolated: true, includeOneTimeIssues: false } },
  ];
  for (const request of cases) {
    let mistral = 0;
    await runTurn(request, {
      complete: async (input) => { assert.equal(input.endpoint, undefined, 'private or research contexts must use Mercury'); mistral++; return { text: 'Research answer.', finish: 'stop', toolCalls: [] }; },
      search: async () => ({ error: '', hits: [] }),
      fetch: async () => ({ title: '', pageText: '', error: '' }),
    });
    assert.equal(mistral, 1, 'these contexts use the regular Mercury route');
  }
}

async function clearingDuringRequestPreventsCacheRepersist(): Promise<void> {
  clearAnswerCache();
  let resolve!: (value: Completion) => void;
  const pending = runTurn({ keys, history: [], question: 'Define gravity' }, {
    complete: async () => new Promise<Completion>((done) => { resolve = done; }),
    search: async () => ({ error: '', hits: [] }),
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  await Promise.resolve();
  clearAnswerCache();
  resolve({ ...answer, text: 'Gravity answer.' });
  await pending;
  assert.equal(getCachedAnswer(keys.mistral!, 'Define gravity', 'en', 'short', 'ministral-3b-2512'), undefined);
}

function cacheExpiryAndIsolation(): void {
  clearAnswerCache();
  cacheAnswer('key-a', ' q  q ', 'en', 'short', 'ministral-3b-2512', 'answer', 1000);
  assert.equal(getCachedAnswer('key-a', ' q  q ', 'en', 'short', 'ministral-3b-2512', 1001), 'answer');
  assert.equal(getCachedAnswer('key-a', 'q q', 'en', 'short', 'ministral-3b-2512', 1001), undefined, 'question whitespace is significant');
  assert.equal(getCachedAnswer('key-a', ' q  q ', 'en', 'short', 'ministral-8b-2512', 1001), undefined, 'model tier is isolated');
  assert.equal(getCachedAnswer('key-b', ' q  q ', 'en', 'short', 'ministral-3b-2512', 1001), undefined);
  assert.equal(getCachedAnswer('key-a', ' q  q ', 'tr', 'short', 'ministral-3b-2512', 1001), undefined);
  assert.equal(getCachedAnswer('key-a', ' q  q ', 'en', 'short', 'ministral-3b-2512', 601000), undefined);
  clearAnswerCache();
  for (let i = 0; i < 33; i++) cacheAnswer('k', `q${i}`, 'en', 'short', 'ministral-3b-2512', `a${i}`);
  assert.equal(getCachedAnswer('k', 'q0', 'en', 'short', 'ministral-3b-2512'), undefined, 'oldest entry is evicted at 33');
  assert.equal(getCachedAnswer('k', 'q32', 'en', 'short', 'ministral-3b-2512'), 'a32');
  clearAnswerCache();
}

async function main(): Promise<void> {
  await routingAndCache();
  await bypassAndFallback();
  await clearingDuringRequestPreventsCacheRepersist();
  cacheExpiryAndIsolation();
  console.log('cheap routing and cache checks passed');
}
void main();

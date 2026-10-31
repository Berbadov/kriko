import assert from 'node:assert/strict';
import { languageScopedQuery, resolveAnswerLanguage } from '../src/engine/researchLanguage';
import { DEFAULT_RESEARCH_PREFERENCES, normalizeResearchPreferences } from '../src/engine/researchPreferences';
import { runTurn } from '../src/engine/providers';

async function main() {
  const query = languageScopedQuery(`site:example.com ${'a'.repeat(130)} lang:zh,en`, 'tr');
  assert.ok(query.startsWith('site:example.com'));
  assert.ok(query.endsWith(' lang:tr'));
  assert.ok(query.length <= 128);
  assert.equal((query.match(/lang:/g) ?? []).length, 1);
  assert.equal(languageScopedQuery('public product', 'any'), 'public product');
  assert.equal(resolveAnswerLanguage('Which product fits?', 'tr', 'auto', false), 'en');
  assert.equal(resolveAnswerLanguage('Hangi ürün uygun?', 'en', 'auto', false), 'tr');
  assert.equal(resolveAnswerLanguage('generic screen prompt', 'tr', 'auto', true), 'tr');
  assert.equal(resolveAnswerLanguage('Which product?', 'en', 'tr', false), 'tr');
  assert.equal(normalizeResearchPreferences({}).sourceLanguage, 'any');
  assert.equal(normalizeResearchPreferences({ sourceLanguage: 'invalid' }).sourceLanguage, 'any');

  let calls = 0;
  let searched = '';
  const result = await runTurn({
    keys: { mercury: 'test', deepseek: 'test' }, history: [], question: 'Which product fits?', language: 'en',
    researchPreferences: { ...DEFAULT_RESEARCH_PREFERENCES, sourceLanguage: 'en', answerLanguage: 'tr' },
  }, {
    complete: async (input) => {
      const system = String(input.messages[0].content);
      assert.match(system, /Write the complete answer in Turkish/);
      assert.match(system, /Use only English-language sources/);
      if (++calls === 1) return { text: '', finish: 'tool_calls', toolCalls: [{ id: 's', name: 'search', arguments: JSON.stringify({ query: 'public product lang:zh', kind: 'manufacturer' }) }] };
      return { text: 'Türkçe yanıt.', finish: 'stop', toolCalls: [] };
    },
    search: async (query) => { searched = query; return { error: '', hits: [] }; },
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.equal(searched, 'public product lang:en');
  assert.equal(result.text, 'Türkçe yanıt.');
  assert.equal(result.error, '');
  console.log('Independent source and answer language checks passed.');
}
void main();

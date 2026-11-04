/**
 * The language plumbing: one turn can research in any of the 14 languages and
 * answer in a different one, without ever being asked to speak a code the
 * engine does not serve.
 */

import assert from 'node:assert/strict';
import {
  ANSWER_LANGUAGES,
  RESEARCH_LANGUAGE_CODES,
  SOURCE_LANGUAGES,
  answerLanguageInstruction,
  languageScopedQuery,
  resolveAnswerLanguage,
  type AnswerLanguage,
  type SourceLanguage,
} from '../src/engine/researchLanguage';
import { RESEARCH_LANGUAGES, isResearchLanguage } from '../src/engine/languages';
import {
  DEFAULT_RESEARCH_PREFERENCES,
  normalizeAnswerLanguage,
  normalizeResearchPreferences,
  normalizeSourceLanguage,
} from '../src/engine/researchPreferences';
import { agentPrompt, siteReviewsPrompt } from '../src/engine/prompt';
import { runTurn } from '../src/engine/providers';

/** The 14 codes are one closed vocabulary: the data list and the type agree. */
function languageList(): void {
  assert.equal(SOURCE_LANGUAGES.length, RESEARCH_LANGUAGES.length + 1);
  assert.equal(ANSWER_LANGUAGES.length, RESEARCH_LANGUAGES.length + 1);
  for (const language of RESEARCH_LANGUAGES) {
    assert.ok(isResearchLanguage(language.code), `${language.code} is a known code`);
    assert.ok(SOURCE_LANGUAGES.includes(language.code as SourceLanguage), `${language.code} can be a source language`);
    assert.ok(ANSWER_LANGUAGES.includes(language.code as AnswerLanguage), `${language.code} can be an answer language`);
    assert.equal(normalizeSourceLanguage(language.code), language.code);
    assert.equal(normalizeAnswerLanguage(language.code), language.code);
  }
  assert.equal(new Set(RESEARCH_LANGUAGE_CODES).size, RESEARCH_LANGUAGES.length);
}

/** A stored value survives a language being retired, and nothing else does. */
function guards(): void {
  assert.equal(normalizeResearchPreferences({}).sourceLanguage, 'any');
  assert.equal(normalizeResearchPreferences({}).answerLanguage, 'auto');
  for (const code of ['de', 'es', 'ja', 'pt', 'ru', 'ar', 'zh', 'ko']) {
    assert.equal(normalizeResearchPreferences({ sourceLanguage: code, answerLanguage: code }).sourceLanguage, code);
    assert.equal(normalizeResearchPreferences({ sourceLanguage: code, answerLanguage: code }).answerLanguage, code);
  }
  for (const junk of ['invalid', 'EN', '', 'language', 42, null, undefined, {}]) {
    assert.equal(normalizeSourceLanguage(junk), 'any', `${String(junk)} is not a source language`);
    assert.equal(normalizeAnswerLanguage(junk), 'auto', `${String(junk)} is not an answer language`);
  }
  assert.equal(normalizeSourceLanguage('any'), 'any');
  assert.equal(normalizeAnswerLanguage('auto'), 'auto');
  const saved = normalizeResearchPreferences({ sourceLanguage: 'de', answerLanguage: 'xx', sourceCount: '7' });
  assert.equal(saved.sourceLanguage, 'de');
  assert.equal(saved.answerLanguage, 'auto');
  assert.equal(saved.sourceCount, 7);
  assert.deepEqual(normalizeResearchPreferences(null), DEFAULT_RESEARCH_PREFERENCES);
}

/** An explicit choice wins; otherwise the question's own language decides. */
function resolving(): void {
  // Explicit choices, including languages no Latin heuristic could guess.
  assert.equal(resolveAnswerLanguage('Which product?', 'en', 'de', false), 'de');
  assert.equal(resolveAnswerLanguage('Hangi ürün uygun?', 'tr', 'es', false), 'es');
  assert.equal(resolveAnswerLanguage('Any question', 'en', 'ja', false), 'ja');
  assert.equal(resolveAnswerLanguage('', 'en', 'ar', true), 'ar');

  // Auto keeps the Turkish/English heuristics that predate the widening.
  assert.equal(resolveAnswerLanguage('Which product fits?', 'tr', 'auto', false), 'en');
  assert.equal(resolveAnswerLanguage('Hangi ürün uygun?', 'en', 'auto', false), 'tr');
  assert.equal(resolveAnswerLanguage('Ürün fiyatı nedir?', 'en', 'auto', false), 'tr');

  // Scripts that name a language on their own.
  assert.equal(resolveAnswerLanguage('これはどの製品ですか？', 'en', 'auto', false), 'ja');
  assert.equal(resolveAnswerLanguage('この製品の不具合は何ですか？', 'tr', 'auto', false), 'ja');
  assert.equal(resolveAnswerLanguage('这个产品有什么问题？', 'en', 'auto', false), 'zh');
  assert.equal(resolveAnswerLanguage('이 제품의 문제는 무엇인가요?', 'en', 'auto', false), 'ko');
  assert.equal(resolveAnswerLanguage('Какие проблемы у этого товара?', 'en', 'auto', false), 'ru');
  assert.equal(resolveAnswerLanguage('ما المشاكل في هذا المنتج؟', 'en', 'auto', false), 'ar');

  // Kana is checked before Han, so Japanese is not read as Chinese.
  const japanese = resolveAnswerLanguage('製品の不具合は？', 'en', 'auto', false);
  assert.equal(japanese, 'ja');

  // Nothing recognisable: the interface language, never a random guess.
  assert.equal(resolveAnswerLanguage('zzz qqq', 'tr', 'auto', false), 'tr');
  assert.equal(resolveAnswerLanguage('zzz qqq', 'en', 'auto', false), 'en');

  // A screenshot with no words asks in the language the screen is drawn in.
  assert.equal(resolveAnswerLanguage('generic screen prompt', 'tr', 'auto', true), 'tr');

  // A stored code the list no longer has cannot be answered in.
  assert.equal(resolveAnswerLanguage('Which product?', 'tr', 'xx' as AnswerLanguage, false), 'tr');
}

/** The answer instruction names the language; it never hardcodes two. */
function instructions(): void {
  const auto = answerLanguageInstruction('auto', 'ja', false);
  assert.match(auto, /use Japanese/);
  assert.doesNotMatch(auto, /Turkish|English/);
  const fixed = answerLanguageInstruction('de', 'de', false);
  assert.match(fixed, /Write the complete answer in German/);
  const template = answerLanguageInstruction('auto', 'ko', true);
  assert.match(template, /Write the complete answer in Korean/);
  const english = answerLanguageInstruction('en', 'en', false);
  assert.match(english, /Write the complete answer in English/);

  assert.match(agentPrompt('short', 'de'), /Write the complete answer in German/);
  assert.doesNotMatch(agentPrompt('short', 'de'), /Turkish/);
  assert.doesNotMatch(agentPrompt('short', 'en'), /Write the complete answer in/);
  assert.match(siteReviewsPrompt('example.com', 'standard', 'ja'), /Write the complete answer in Japanese/);
  assert.doesNotMatch(siteReviewsPrompt('example.com', 'standard', 'ja'), /Türkçe|Turkish/);
}

/** The provider's language operator stays inside its 128-character query. */
function queryScoping(): void {
  const query = languageScopedQuery(`site:example.com ${'a'.repeat(130)} lang:zh,en`, 'tr');
  assert.ok(query.startsWith('site:example.com'));
  assert.ok(query.endsWith(' lang:tr'));
  assert.ok(query.length <= 128);
  assert.equal((query.match(/lang:/g) ?? []).length, 1);

  const long = languageScopedQuery(`ürün fiyat ${'x'.repeat(200)}`, 'ja');
  assert.ok(long.endsWith(' lang:ja'));
  assert.ok(long.length <= 128);
  assert.equal((long.match(/lang:/g) ?? []).length, 1);

  assert.equal(languageScopedQuery('public product', 'any'), 'public product');
  assert.equal(languageScopedQuery('public product', 'de'), 'public product lang:de');
  assert.equal(languageScopedQuery('public product', 'zh'), 'public product lang:zh');
  // A stored code the list no longer has is dropped, not sent to the provider.
  assert.equal(languageScopedQuery('public product', 'xx' as SourceLanguage), 'public product');
}

/** A whole turn: German sources, a Japanese answer, one search operator. */
async function turnPlumbing(): Promise<void> {
  let searched = '';
  let system = '';
  const result = await runTurn({
    keys: { mercury: 'test', deepseek: 'test' },
    history: [],
    question: 'Which product fits?',
    language: 'en',
    researchPreferences: { ...DEFAULT_RESEARCH_PREFERENCES, sourceLanguage: 'de', answerLanguage: 'ja' },
  }, {
    complete: async (input) => {
      system = String(input.messages[0].content);
      if (!searched) {
        return { text: '', finish: 'tool_calls', toolCalls: [{ id: 's', name: 'search', arguments: JSON.stringify({ query: 'public product', kind: 'manufacturer' }) }] };
      }
      return { text: '製品についての回答です。', finish: 'stop', toolCalls: [] };
    },
    search: async (query) => { searched = query; return { error: '', hits: [] }; },
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.equal(searched, 'public product lang:de');
  assert.match(system, /Write the complete answer in Japanese/);
  assert.match(system, /Use only German-language sources/);
  assert.equal(result.text, '製品についての回答です。');
  assert.equal(result.error, '');
}

/** Auto answer language follows a Japanese question without a preference. */
async function autoDetectionTurn(): Promise<void> {
  let system = '';
  let searched = '';
  let calls = 0;
  await runTurn({
    keys: { mercury: 'test', deepseek: 'test' },
    history: [],
    question: 'この製品の不具合は何ですか？',
    language: 'en',
    researchPreferences: { ...DEFAULT_RESEARCH_PREFERENCES },
  }, {
    complete: async (input) => {
      system = String(input.messages[0].content);
      if (++calls === 1) {
        return { text: '', finish: 'tool_calls', toolCalls: [{ id: 's', name: 'search', arguments: JSON.stringify({ query: '不具合 製品' }) }] };
      }
      return { text: 'この製品の既知の不具合について回答します。', finish: 'stop', toolCalls: [] };
    },
    search: async (query) => { searched = query; return { error: '', hits: [] }; },
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.equal(searched, '不具合 製品');
  assert.match(system, /If it is unclear, use Japanese/);
}

/** The Turkish/English path that shipped before still behaves identically. */
async function turkishPath(): Promise<void> {
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
}

async function main() {
  languageList();
  guards();
  resolving();
  instructions();
  queryScoping();
  await turnPlumbing();
  await autoDetectionTurn();
  await turkishPath();
  console.log('14-language research and answer checks passed.');
}
void main();

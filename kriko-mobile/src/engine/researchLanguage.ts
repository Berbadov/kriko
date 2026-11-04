/**
 * Which languages a turn researches in and answers in.
 *
 * Two reader choices ride along with one turn and neither is the interface
 * language: the source language narrows what search is allowed to return, and
 * the answer language says what the reader wants to read. The interface keeps
 * its own language (`src/i18n.ts`) and the two are deliberately separate: a
 * reader can want German sources and a Turkish answer.
 *
 * The codes and their names live in `languages.ts`; this module is only the
 * compile-time face of that list plus the rules that resolve a question to one
 * of them.
 */

import type { Language } from '../i18n';
import { isResearchLanguage, languageName, RESEARCH_LANGUAGES } from './languages';

/**
 * The code of one language `languages.ts` lists.
 *
 * Kept as a union so a picker, a guard and a prompt cannot invent a code the
 * engine does not serve. `RESEARCH_LANGUAGE_CODES` below is the same closure as
 * a value, derived from the data list rather than written twice.
 */
export type ResearchLanguageCode =
  | 'en'
  | 'tr'
  | 'de'
  | 'es'
  | 'fr'
  | 'it'
  | 'pt'
  | 'nl'
  | 'pl'
  | 'ru'
  | 'ar'
  | 'ja'
  | 'ko'
  | 'zh';

/** Search everywhere, or restrict sources to one language. */
export type SourceLanguage = 'any' | ResearchLanguageCode;

/** Follow the question's own language, or always answer in one language. */
export type AnswerLanguage = 'auto' | ResearchLanguageCode;

/** Every answer language, in the order `languages.ts` lists them. */
export const RESEARCH_LANGUAGE_CODES: readonly ResearchLanguageCode[] =
  RESEARCH_LANGUAGES.map((language) => language.code as ResearchLanguageCode);

/** Picker order for sources: no restriction first, then every language. */
export const SOURCE_LANGUAGES: readonly SourceLanguage[] = ['any', ...RESEARCH_LANGUAGE_CODES];

/** Picker order for answers: follow the question first, then every language. */
export const ANSWER_LANGUAGES: readonly AnswerLanguage[] = ['auto', ...RESEARCH_LANGUAGE_CODES];

/** Keep the provider's language operator inside its 128-character query limit. */
export function languageScopedQuery(query: string, language: SourceLanguage): string {
  // An unknown saved code is ignored rather than sent to the provider.
  if (language === 'any' || !isResearchLanguage(language)) return query;
  const suffix = ` lang:${language}`;
  const words = query.replace(/\blang:\S+/gi, '').replace(/\s+/g, ' ').trim();
  return words.slice(0, 128 - suffix.length).trimEnd() + suffix;
}

/**
 * Scripts that name one language on their own. Latin letters do not: they are
 * shared by a dozen languages, so those keep the English/Turkish word
 * heuristics below.
 *
 * Kana is read before Han because Japanese writes with both; a kana-free
 * Japanese question is indistinguishable from Chinese and is read as Chinese.
 * An explicit answer language overrides any guess.
 */
const SCRIPT_LANGUAGES: readonly (readonly [ResearchLanguageCode, RegExp])[] = [
  ['ja', /[\u3040-\u30ff]/],
  ['ko', /[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]/],
  ['zh', /[\u4e00-\u9fff]/],
  ['ru', /[\u0400-\u04ff]/],
  ['ar', /[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]/],
];

/**
 * The language to answer in: the reader's explicit choice, or a guess from the
 * question, or the interface language when the question says nothing.
 */
export function resolveAnswerLanguage(
  question: string,
  ui: Language,
  preference: AnswerLanguage,
  screenTemplate: boolean,
): ResearchLanguageCode {
  // An explicit choice wins, including for a screenshot sent with no words.
  if (preference !== 'auto') return isResearchLanguage(preference) ? preference : ui;
  // A template question has no language of its own; the screen's language is it.
  if (screenTemplate) return ui;
  for (const [code, pattern] of SCRIPT_LANGUAGES) {
    if (pattern.test(question)) return code;
  }
  if (/[çğıöşüİ]/i.test(question) || /\b(?:hangi|nedir|nasil|urun|fiyat|alinir|almali|satin)\b/i.test(question)) return 'tr';
  if (/\b(?:what|how|why|which|should|please|explain|define|translate|rewrite|is|are|can|does)\b/i.test(question)) return 'en';
  return ui;
}

/** The sentence that makes an answer language unambiguous to the model. */
export function answerLanguageInstruction(
  preference: AnswerLanguage,
  resolved: ResearchLanguageCode,
  screenTemplate: boolean,
): string {
  if (preference === 'auto' && !screenTemplate) {
    return `Answer in the language of the reader's question. If it is unclear, use ${languageName(resolved)}. Source languages do not determine answer language.`;
  }
  return `Write the complete answer in ${languageName(resolved)}, independently of the source languages. Preserve product names, model codes and source citations.`;
}

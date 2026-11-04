/**
 * The turn-scoped research controls the reader saves, and how a stored value is
 * made safe again on the next launch.
 *
 * Everything is validated, not trusted: the store survives an update that
 * retires a language code, and a hand-edited value must fall back to a choice
 * the engine can serve rather than reach a provider.
 */

import { isResearchLanguage } from './languages';
import type { AnswerLanguage, ResearchLanguageCode, SourceLanguage } from './researchLanguage';

export interface ResearchPreferences {
  products: string[];
  sourceCount: number;
  includeIsolated: boolean;
  includeOneTimeIssues: boolean;
  sourceLanguage: SourceLanguage;
  answerLanguage: AnswerLanguage;
}

export const DEFAULT_RESEARCH_PREFERENCES: ResearchPreferences = {
  products: ['all'],
  sourceCount: 5,
  includeIsolated: false,
  includeOneTimeIssues: false,
  sourceLanguage: 'any',
  answerLanguage: 'auto',
};

/** Narrow a stored string to a code `languages.ts` serves. */
function isKnownLanguageCode(value: string): value is ResearchLanguageCode {
  return isResearchLanguage(value);
}

/** A saved source language, or every language when it is no longer known. */
export function normalizeSourceLanguage(value: unknown): SourceLanguage {
  return typeof value === 'string' && (value === 'any' || isKnownLanguageCode(value)) ? value : 'any';
}

/** A saved answer language, or the question's own when it is no longer known. */
export function normalizeAnswerLanguage(value: unknown): AnswerLanguage {
  return typeof value === 'string' && (value === 'auto' || isKnownLanguageCode(value)) ? value : 'auto';
}

export function normalizeResearchPreferences(value: unknown): ResearchPreferences {
  if (!value || typeof value !== 'object') return { ...DEFAULT_RESEARCH_PREFERENCES };
  const saved = value as Partial<ResearchPreferences>;
  const products = Array.isArray(saved.products)
    ? [...new Set(saved.products.filter((item): item is string => typeof item === 'string' && item.trim().length > 0 && item.length <= 120).map((item) => item.trim()))].slice(0, 10)
    : DEFAULT_RESEARCH_PREFERENCES.products;
  const count = Number(saved.sourceCount);
  return {
    products: products.length ? products : [...DEFAULT_RESEARCH_PREFERENCES.products],
    sourceCount: Number.isFinite(count) ? Math.max(1, Math.min(10, Math.round(count))) : DEFAULT_RESEARCH_PREFERENCES.sourceCount,
    includeIsolated: saved.includeIsolated === true,
    includeOneTimeIssues: saved.includeOneTimeIssues === true,
    sourceLanguage: normalizeSourceLanguage(saved.sourceLanguage),
    answerLanguage: normalizeAnswerLanguage(saved.answerLanguage),
  };
}

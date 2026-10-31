export interface ResearchPreferences {
  products: string[];
  sourceCount: number;
  includeIsolated: boolean;
  includeOneTimeIssues: boolean;
  sourceLanguage: 'any' | 'en' | 'tr';
  answerLanguage: 'auto' | 'en' | 'tr';
}

export const DEFAULT_RESEARCH_PREFERENCES: ResearchPreferences = {
  products: ['all'],
  sourceCount: 5,
  includeIsolated: false,
  includeOneTimeIssues: false,
  sourceLanguage: 'any',
  answerLanguage: 'auto',
};

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
    sourceLanguage: saved.sourceLanguage === 'en' || saved.sourceLanguage === 'tr' ? saved.sourceLanguage : 'any',
    answerLanguage: saved.answerLanguage === 'en' || saved.answerLanguage === 'tr' ? saved.answerLanguage : 'auto',
  };
}

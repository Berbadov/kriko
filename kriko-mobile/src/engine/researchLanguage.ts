export type SourceLanguage = 'any' | 'en' | 'tr';
export type AnswerLanguage = 'auto' | 'en' | 'tr';

/** Keep the provider's language operator inside its 128-character query limit. */
export function languageScopedQuery(query: string, language: SourceLanguage): string {
  if (language === 'any') return query;
  const suffix = ` lang:${language}`;
  const words = query.replace(/\blang:\S+/gi, '').replace(/\s+/g, ' ').trim();
  return words.slice(0, 128 - suffix.length).trimEnd() + suffix;
}

export function resolveAnswerLanguage(question: string, ui: 'en' | 'tr', preference: AnswerLanguage, screenTemplate: boolean): 'en' | 'tr' {
  if (preference !== 'auto') return preference;
  if (screenTemplate) return ui;
  if (/[çğıöşüİ]/i.test(question) || /\b(?:hangi|nedir|nasil|urun|fiyat|alinir|almali|satin)\b/i.test(question)) return 'tr';
  if (/\b(?:what|how|why|which|should|please|explain|define|translate|rewrite|is|are|can|does)\b/i.test(question)) return 'en';
  return ui;
}

export function answerLanguageInstruction(preference: AnswerLanguage, resolved: 'en' | 'tr', screenTemplate: boolean): string {
  if (preference === 'auto' && !screenTemplate) return `Answer in the language of the reader's question. If it is unclear, use ${resolved === 'tr' ? 'Turkish' : 'English'}. Source languages do not determine answer language.`;
  return `Write the complete answer in ${resolved === 'tr' ? 'Turkish' : 'English'}, independently of the source languages. Preserve product names, model codes and source citations.`;
}

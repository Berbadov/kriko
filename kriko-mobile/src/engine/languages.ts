/**
 * The languages Kriko can research in and answer in.
 *
 * This is the same list the desktop Settings offers, in one place, so a new
 * language is a data row here rather than a new branch in every screen. The
 * interface language is separate: it is the app's own copy, and it stays
 * English/Türkçe until a full translation exists.
 *
 * `english` is what the prompt asks the model to write in; `native` is what a
 * reader sees in the picker. Neither is translated.
 */

export interface ResearchLanguage {
  /** The code the search provider's `lang:` operator takes. */
  code: string;
  /** The English name, for prompt instructions. */
  english: string;
  /** The name the language calls itself, for the picker. */
  native: string;
}

export const RESEARCH_LANGUAGES: readonly ResearchLanguage[] = [
  { code: 'en', english: 'English', native: 'English' },
  { code: 'tr', english: 'Turkish', native: 'Türkçe' },
  { code: 'de', english: 'German', native: 'Deutsch' },
  { code: 'es', english: 'Spanish', native: 'Español' },
  { code: 'fr', english: 'French', native: 'Français' },
  { code: 'it', english: 'Italian', native: 'Italiano' },
  { code: 'pt', english: 'Portuguese', native: 'Português' },
  { code: 'nl', english: 'Dutch', native: 'Nederlands' },
  { code: 'pl', english: 'Polish', native: 'Polski' },
  { code: 'ru', english: 'Russian', native: 'Русский' },
  { code: 'ar', english: 'Arabic', native: 'العربية' },
  { code: 'ja', english: 'Japanese', native: '日本語' },
  { code: 'ko', english: 'Korean', native: '한국어' },
  { code: 'zh', english: 'Chinese', native: '中文' },
] as const;

const BY_CODE = new Map(RESEARCH_LANGUAGES.map((language) => [language.code, language]));

/** A known research language code, or `undefined`. */
export function researchLanguage(code: string | undefined | null): ResearchLanguage | undefined {
  return code ? BY_CODE.get(code) : undefined;
}

/** The English name the answer instruction uses; the code itself when unknown. */
export function languageName(code: string): string {
  return BY_CODE.get(code)?.english ?? code;
}

/** The name a reader sees in a picker; the code itself when unknown. */
export function nativeLanguageName(code: string): string {
  return BY_CODE.get(code)?.native ?? code;
}

/** Whether `value` is a language this build can research or answer in. */
export function isResearchLanguage(value: string): boolean {
  return BY_CODE.has(value);
}

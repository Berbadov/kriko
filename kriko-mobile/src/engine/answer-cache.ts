const MAX_ENTRIES = 32;
const TTL_MS = 10 * 60 * 1000;

interface Entry { text: string; expiresAt: number; }
const answers = new Map<string, Entry>();
let generation = 0;

function cacheKey(credential: string, question: string, language: string, style: string, model: string): string {
  // Credentials remain confined to this private in-memory map and are never emitted or persisted.
  return JSON.stringify([credential, question, language, style, model]);
}

export function getCachedAnswer(
  credential: string, question: string, language: string, style: string, model: string, now = Date.now(),
): string | undefined {
  const key = cacheKey(credential, question, language, style, model);
  const entry = answers.get(key);
  if (!entry) return undefined;
  if (entry.expiresAt <= now) { answers.delete(key); return undefined; }
  answers.delete(key);
  answers.set(key, entry);
  return entry.text;
}

export function cacheAnswer(
  credential: string, question: string, language: string, style: string, model: string, text: string, now = Date.now(), expectedGeneration = generation,
): void {
  if (!text.trim() || expectedGeneration !== generation) return;
  const key = cacheKey(credential, question, language, style, model);
  answers.delete(key);
  answers.set(key, { text, expiresAt: now + TTL_MS });
  while (answers.size > MAX_ENTRIES) answers.delete(answers.keys().next().value as string);
}

/** Clear every in-memory answer when access or conversation data is forgotten. */
export function clearAnswerCache(): void { answers.clear(); generation += 1; }

export function answerCacheGeneration(): number { return generation; }

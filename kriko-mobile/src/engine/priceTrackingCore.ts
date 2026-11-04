export type SearchHit = { url: string; title: string; snippet: string; pageText: string };
export type PriceWatch = {
  id: string; url: string; name: string; currency: string; intervalHours: number;
  lastPrice: number | null; lastObservedAt: number | null; nextCheckAt: number;
  paused: boolean; lastError?: string;
};
export type PriceSearch = (query: string) => Promise<{ hits: SearchHit[] }>;
export const VALID_INTERVALS = [1, 6, 12, 24, 72, 168] as const;

export function isValidPriceWatch(value: unknown): value is PriceWatch {
  if (!value || typeof value !== 'object') return false;
  const w = value as Partial<PriceWatch>;
  return typeof w.id === 'string' && !!w.id && !!safeProductUrl(w.url || '') && typeof w.name === 'string' && !!w.name.trim() &&
    typeof w.currency === 'string' && /^[A-Z]{3}$/.test(w.currency) && VALID_INTERVALS.includes(w.intervalHours as typeof VALID_INTERVALS[number]) &&
    (w.lastPrice === null || (typeof w.lastPrice === 'number' && Number.isFinite(w.lastPrice) && w.lastPrice > 0)) &&
    (w.lastObservedAt === null || (typeof w.lastObservedAt === 'number' && Number.isFinite(w.lastObservedAt) && w.lastObservedAt >= 0)) &&
    typeof w.nextCheckAt === 'number' && Number.isFinite(w.nextCheckAt) && w.nextCheckAt >= 0 && typeof w.paused === 'boolean' &&
    (w.lastError === undefined || typeof w.lastError === 'string');
}

/** Serialize each storage read/modify/write, while leaving callers' network work outside. */
export function createSerializedWatchMutation(load: () => Promise<PriceWatch[]>, save: (rows: PriceWatch[]) => Promise<void>) {
  let tail: Promise<void> = Promise.resolve();
  return (update: (current: PriceWatch[]) => PriceWatch[]): Promise<PriceWatch[]> => {
    const operation = tail.then(async () => {
      const next = update(await load());
      await save(next);
      return next;
    });
    tail = operation.then(() => undefined, () => undefined);
    return operation;
  };
}

export function safeProductUrl(value: string): string {
  try {
    const url = new URL(value.trim()), host = url.hostname.toLowerCase();
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || !host.includes('.') || /^\d{1,3}(?:\.\d{1,3}){3}$/.test(host) || host.startsWith('[')) return '';
    url.hash = '';
    return url.toString().slice(0, 2048);
  } catch { return ''; }
}

const SYMBOLS: Record<string, string[]> = { USD: ['$', 'US$'], CAD: ['CA$', 'C$'], AUD: ['A$', 'AU$'], EUR: ['€'], GBP: ['£'], JPY: ['¥'], CNY: ['CN¥', '¥'], TRY: ['₺'], INR: ['₹'], KRW: ['₩'], CHF: ['CHF'] };

export function explicitPrice(pageText: string, currency: string): number | null {
  const code = currency.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(code)) return null;
  const escaped = code.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const values: string[] = [];
  const codeMatches = [...pageText.matchAll(new RegExp(`(?:\\b${escaped}\\s*([0-9][0-9.,\\u00a0\\u202f ]{0,18})|([0-9][0-9.,\\u00a0\\u202f ]{0,18})\\s*\\b${escaped}\\b)`, 'gi'))];
  values.push(...codeMatches.map(m => m[1] || m[2]));
  for (const symbol of SYMBOLS[code] || []) {
    const sym = symbol.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const prefix = [...pageText.matchAll(new RegExp(`${sym}\\s*([0-9][0-9.,\\u00a0\\u202f ]{0,18})`, 'g'))];
    const suffix = [...pageText.matchAll(new RegExp(`([0-9][0-9.,\\u00a0\\u202f ]{0,18})\\s*${sym}`, 'g'))];
    values.push(...prefix.map(m => m[1]), ...suffix.map(m => m[1]));
  }
  if (values.length !== 1) return null;
  const raw = values[0].trim().replace(/[\u00a0\u202f ]/g, '');
  let normalized = raw;
  if (raw.includes('.') && raw.includes(',')) {
    const decimal = Math.max(raw.lastIndexOf('.'), raw.lastIndexOf(',')), tail = raw.length - decimal - 1;
    if (tail < 1 || tail > 2) return null;
    normalized = raw.slice(0, decimal).replace(/[.,]/g, '') + '.' + raw.slice(decimal + 1);
  } else if (/[.,]/.test(raw)) {
    const sep = raw.includes(',') ? ',' : '.', parts = raw.split(sep);
    if (parts.length > 2) {
      if (!parts.slice(1).every(part => part.length === 3)) return null;
      normalized = parts.join('');
    } else if (parts[1].length === 3) normalized = parts.join('');
    else if (parts[1].length >= 1 && parts[1].length <= 2) normalized = parts.join('.');
    else return null;
  }
  const value = Number(normalized);
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function matchingListingPrice(hits: SearchHit[], url: string, currency: string): number | null {
  const safe = safeProductUrl(url);
  if (!safe) return null;
  const exact = hits.filter(hit => safeProductUrl(hit.url) === safe && hit.pageText.trim());
  return exact.length === 1 ? explicitPrice(exact[0].pageText, currency) : null;
}

export function createWatchChecker(deps: { load: () => Promise<PriceWatch[]>; save: (watches: PriceWatch[]) => Promise<void>; mutate?: (update: (current: PriceWatch[]) => PriceWatch[]) => Promise<PriceWatch[]>; read: (url: string) => Promise<string>; search: PriceSearch; now?: () => number }) {
  const active = new Set<string>();
  return async (id: string): Promise<PriceWatch[]> => {
    if (active.has(id)) return deps.load();
    active.add(id);
    try {
      const watch = (await deps.load()).find(w => w.id === id);
      if (!watch) return deps.load();
      const now = deps.now ?? Date.now;
      try {
        let body = '';
        try { body = await deps.read(watch.url); } catch { /* Search the exact URL result if direct reading is unavailable. */ }
        let price = explicitPrice(body, watch.currency);
        if (price === null) {
          const result = await deps.search(`site:${new URL(watch.url).hostname} ${watch.name} ${watch.currency} price`);
          price = matchingListingPrice(result.hits, watch.url, watch.currency);
        }
        const update = (latest: PriceWatch[]) => latest.map(w => w.id === id ? { ...w, ...(price !== null ? { lastPrice: price, lastObservedAt: now() } : {}), nextCheckAt: now() + w.intervalHours * 3600000, lastError: price === null ? 'No unambiguous explicit price found in the product page content.' : undefined } : w);
        return deps.mutate ? deps.mutate(update) : (async () => { const latest = update(await deps.load()); await deps.save(latest); return latest; })();
      } catch {
        const update = (latest: PriceWatch[]) => latest.map(w => w.id === id ? { ...w, nextCheckAt: now() + w.intervalHours * 3600000, lastError: 'Check failed. The last valid observation was kept.' } : w);
        return deps.mutate ? deps.mutate(update) : (async () => { const latest = update(await deps.load()); await deps.save(latest); return latest; })();
      }
    } finally { active.delete(id); }
  };
}

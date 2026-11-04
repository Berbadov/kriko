import AsyncStorage from '@react-native-async-storage/async-storage';
import { fetchPage, searchWeb } from './providers';
import { createSerializedWatchMutation, createWatchChecker, isValidPriceWatch, safeProductUrl, type PriceWatch } from './priceTrackingCore';

export { explicitPrice, matchingListingPrice, safeProductUrl, createWatchChecker } from './priceTrackingCore';
export type { PriceWatch } from './priceTrackingCore';
export const PRICE_INTERVALS = [1, 6, 12, 24, 72, 168] as const;
export type PriceInterval = typeof PRICE_INTERVALS[number];
const STORAGE_KEY = '@kriko/price-watches-v1';

export async function loadPriceWatches(): Promise<PriceWatch[]> {
  try {
    const values = JSON.parse(await AsyncStorage.getItem(STORAGE_KEY) || '[]');
    return Array.isArray(values) ? values.filter(isValidPriceWatch) : [];
  } catch { return []; }
}
async function save(watches: PriceWatch[]) { await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(watches)); }
const mutatePriceWatches = createSerializedWatchMutation(loadPriceWatches, save);

export async function addPriceWatch(input: { url: string; name: string; currency: string; intervalHours: PriceInterval }): Promise<PriceWatch[]> {
  const url = safeProductUrl(input.url), name = input.name.trim(), currency = input.currency.trim().toUpperCase();
  if (!url || !name || !/^[A-Z]{3}$/.test(currency) || !PRICE_INTERVALS.includes(input.intervalHours)) throw new Error('Enter a valid product URL, name, ISO currency code, and interval.');
  const now = Date.now();
  const watch: PriceWatch = { id: `${now}-${Math.random().toString(36).slice(2)}`, url, name, currency, intervalHours: input.intervalHours, lastPrice: null, lastObservedAt: null, nextCheckAt: now, paused: false };
  return mutatePriceWatches(watches => {
    if (watches.some(item => item.url === url)) throw new Error('This product is already being tracked.');
    return [watch, ...watches];
  });
}
export function removePriceWatch(id: string) { return mutatePriceWatches(watches => watches.filter(w => w.id !== id)); }
export function updatePriceWatch(id: string, patch: Partial<Pick<PriceWatch, 'paused' | 'intervalHours'>>) { return mutatePriceWatches(watches => watches.map(w => w.id === id ? { ...w, ...patch, ...(patch.intervalHours ? { nextCheckAt: Date.now() + patch.intervalHours * 3600000 } : {}) } : w)); }

const checks = new Map<string, Promise<PriceWatch[]>>();
/** Store calls this only after resolving the current DeepSeek key from secure storage. */
export function checkWatchWithKey(id: string, deepseekKey: string): Promise<PriceWatch[]> {
  const existing = checks.get(id);
  if (existing) return existing;
  const check = createWatchChecker({
    load: loadPriceWatches, save, mutate: mutatePriceWatches,
    read: async url => (await fetchPage(url, deepseekKey)).pageText,
    search: async query => (await searchWeb(query, 5, deepseekKey)),
  });
  const pending = check(id).finally(() => { checks.delete(id); });
  checks.set(id, pending);
  return pending;
}

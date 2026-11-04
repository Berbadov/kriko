/**
 * The shortlist: products the reader is deciding between, and the one ranked
 * pick among them.
 *
 * An item is keyed by the same folded identity the memory catalog uses, so a
 * rescan of one product is still one row. The price-drop chip compares the
 * price a watch observed with the price saved when the product was added; the
 * ranking scores only what the phone actually knows (price, evidence, recency)
 * and says which factor won instead of inventing a verdict.
 */

import type { CatalogEntry } from './memory';
import type { PriceWatch } from './priceTrackingCore';

export interface ShortlistItem {
  id: string;
  /** Folded identity shared with the memory catalog. */
  key: string;
  title: string;
  addedAt: number;
  /** The chat that can be reopened; absent for a product whose chat was deleted. */
  threadId?: string;
  /** Price observed when the item was saved, if one was known. */
  savedPrice?: number | null;
  currency?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function finiteTime(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 0;
}

export function isValidShortlistItem(value: unknown): value is ShortlistItem {
  if (!isRecord(value)) return false;
  return typeof value.id === 'string' && !!value.id &&
    typeof value.key === 'string' && !!value.key &&
    typeof value.title === 'string' && !!value.title.trim() &&
    finiteTime(value.addedAt) > 0 &&
    (value.threadId === undefined || typeof value.threadId === 'string') &&
    (value.savedPrice === undefined || value.savedPrice === null ||
      (typeof value.savedPrice === 'number' && Number.isFinite(value.savedPrice) && value.savedPrice > 0)) &&
    (value.currency === undefined || (typeof value.currency === 'string' && /^[A-Z]{3}$/.test(value.currency)));
}

/** Storage is untrusted: keep valid rows, drop duplicates by id. */
export function normalizeShortlist(value: unknown): ShortlistItem[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const rows: ShortlistItem[] = [];
  for (const raw of value) {
    if (!isValidShortlistItem(raw) || seen.has(raw.id)) continue;
    seen.add(raw.id);
    rows.push(raw);
  }
  return rows;
}

/** Case and spacing folded, never translated: two spellings of one product. */
export function foldText(value: string): string {
  return value.toLocaleLowerCase().replace(/\s+/g, ' ').trim();
}

export interface ShortlistInput {
  key: string;
  title: string;
  threadId?: string;
  savedPrice?: number | null;
  currency?: string;
}

/** One entry per product identity: re-adding refreshes the row, never duplicates it. */
export function upsertShortlistItem(list: readonly ShortlistItem[], input: ShortlistInput, now = Date.now()): ShortlistItem[] {
  const key = foldText(input.key);
  const title = input.title.replace(/\s+/g, ' ').trim().slice(0, 160);
  if (!key || !title) return [...list];
  const price = typeof input.savedPrice === 'number' && Number.isFinite(input.savedPrice) && input.savedPrice > 0 ? input.savedPrice : null;
  const currency = typeof input.currency === 'string' && /^[A-Z]{3}$/.test(input.currency) ? input.currency : undefined;
  const existing = list.find((item) => item.key === key);
  const item: ShortlistItem = {
    id: existing?.id ?? `${now}-${Math.random().toString(36).slice(2)}`,
    key,
    title,
    addedAt: existing?.addedAt ?? now,
    threadId: input.threadId ?? existing?.threadId,
    savedPrice: price,
    currency: currency ?? existing?.currency,
  };
  return [item, ...list.filter((row) => row.key !== key)];
}

export function removeShortlistItem(list: readonly ShortlistItem[], id: string): ShortlistItem[] {
  return list.filter((item) => item.id !== id);
}

/** The watch that belongs to this product, matched by folded name overlap. */
export function matchWatch(item: Pick<ShortlistItem, 'title'>, watches: readonly PriceWatch[]): PriceWatch | null {
  const title = foldText(item.title);
  if (!title) return null;
  let best: PriceWatch | null = null;
  for (const watch of watches) {
    const name = foldText(watch.name);
    if (!name) continue;
    if (name !== title && !title.includes(name) && !name.includes(title)) continue;
    if (!best || (watch.lastObservedAt ?? 0) > (best.lastObservedAt ?? 0)) best = watch;
  }
  return best;
}

/** The price the phone currently knows: the latest watch observation wins. */
export function currentPrice(item: ShortlistItem, watch: PriceWatch | null): { price: number | null; currency: string } {
  if (watch?.lastPrice) return { price: watch.lastPrice, currency: watch.currency };
  return { price: item.savedPrice ?? null, currency: item.currency ?? watch?.currency ?? '' };
}

export type DropStatus = { kind: 'drop'; percent: number } | { kind: 'none' };

/** A drop is only claimed when a watch saw a lower price than the saved one. */
export function priceDropStatus(item: ShortlistItem, watch: PriceWatch | null): DropStatus {
  const saved = item.savedPrice;
  if (!watch?.lastPrice || !saved || saved <= 0 || watch.lastPrice >= saved) return { kind: 'none' };
  const percent = Math.round((1 - watch.lastPrice / saved) * 100);
  return percent > 0 ? { kind: 'drop', percent } : { kind: 'none' };
}

export type WeightLevel = 'low' | 'standard' | 'high';
export const WEIGHT_LEVELS: readonly WeightLevel[] = ['low', 'standard', 'high'];
export const WEIGHT_VALUES: Record<WeightLevel, number> = { low: 0.25, standard: 0.6, high: 1 };

export interface DecisionWeights {
  price: WeightLevel;
  evidence: WeightLevel;
  recency: WeightLevel;
}

export const DEFAULT_WEIGHTS: DecisionWeights = { price: 'standard', evidence: 'standard', recency: 'low' };

export type RankReason = 'price' | 'evidence' | 'recency';

export interface RankedItem {
  item: ShortlistItem;
  /** 0..1, weighted average of the three factor scores. */
  score: number;
  /** The factors this item was best at among the candidates. */
  reasons: RankReason[];
}

function priceScores(items: readonly ShortlistItem[], watches: readonly PriceWatch[]): Map<string, number> {
  const scores = new Map<string, number>();
  const priced = items
    .map((item) => ({ item, price: currentPrice(item, matchWatch(item, watches)).price }))
    .filter((row): row is { item: ShortlistItem; price: number } => row.price !== null);
  if (!priced.length) {
    for (const item of items) scores.set(item.id, 0.5);
    return scores;
  }
  const values = priced.map((row) => row.price);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  for (const item of items) {
    const row = priced.find((entry) => entry.item.id === item.id);
    scores.set(item.id, row ? (span > 0 ? 1 - (row.price - min) / span : 1) : 0);
  }
  return scores;
}

/**
 * Rank the shortlist. Price rewards the cheapest known price, evidence the
 * most sources in the remembered answer, recency decays with age (half at a
 * week). Ties go to the newer item; the order is total and deterministic.
 */
export function rankShortlist(
  items: readonly ShortlistItem[],
  catalog: readonly CatalogEntry[],
  watches: readonly PriceWatch[],
  weights: DecisionWeights,
  now = Date.now(),
): RankedItem[] {
  if (!items.length) return [];
  const byKey = new Map(catalog.map((entry) => [entry.key, entry]));
  const prices = priceScores(items, watches);
  const maxSources = Math.max(1, ...items.map((item) => byKey.get(item.key)?.sources.length ?? 0));
  const weightSum = WEIGHT_VALUES[weights.price] + WEIGHT_VALUES[weights.evidence] + WEIGHT_VALUES[weights.recency];

  const scored = items.map((item) => {
    const priceScore = prices.get(item.id) ?? 0.5;
    const evidenceScore = (byKey.get(item.key)?.sources.length ?? 0) / maxSources;
    const ageDays = Math.max(0, (now - item.addedAt) / 86_400_000);
    const recencyScore = 1 / (1 + ageDays / 7);
    const score = (
      WEIGHT_VALUES[weights.price] * priceScore +
      WEIGHT_VALUES[weights.evidence] * evidenceScore +
      WEIGHT_VALUES[weights.recency] * recencyScore
    ) / weightSum;
    return { item, priceScore, evidenceScore, recencyScore, score };
  });

  const bestPrice = Math.max(...scored.map((row) => row.priceScore));
  const bestEvidence = Math.max(...scored.map((row) => row.evidenceScore));
  const bestRecency = Math.max(...scored.map((row) => row.recencyScore));

  return scored
    .map((row): RankedItem => ({
      item: row.item,
      score: row.score,
      reasons: (['price', 'evidence', 'recency'] as RankReason[]).filter((reason) => {
        if (reason === 'price') return row.priceScore === bestPrice && bestPrice > 0;
        if (reason === 'evidence') return row.evidenceScore === bestEvidence && bestEvidence > 0;
        return row.recencyScore === bestRecency;
      }),
    }))
    .sort((a, b) => b.score - a.score || b.item.addedAt - a.item.addedAt || a.item.title.localeCompare(b.item.title));
}

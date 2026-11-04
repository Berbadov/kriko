import assert from 'node:assert/strict';

import type { CatalogEntry } from '../src/engine/memory';
import type { PriceWatch } from '../src/engine/priceTrackingCore';
import {
  currentPrice,
  isValidShortlistItem,
  matchWatch,
  normalizeShortlist,
  priceDropStatus,
  rankShortlist,
  removeShortlistItem,
  upsertShortlistItem,
  type DecisionWeights,
  type ShortlistItem,
} from '../src/engine/shortlistCore';

function item(over: Partial<ShortlistItem> = {}): ShortlistItem {
  return { id: 'a', key: 'bosch drill', title: 'Bosch Drill', addedAt: 1000, savedPrice: 100, currency: 'EUR', ...over };
}

function watch(over: Partial<PriceWatch> = {}): PriceWatch {
  return { id: 'w1', url: 'https://shop.example/drill', name: 'Bosch Drill', currency: 'EUR', intervalHours: 24, lastPrice: 80, lastObservedAt: 2000, nextCheckAt: 0, paused: false, ...over };
}

function entry(over: Partial<CatalogEntry> = {}): CatalogEntry {
  return { key: 'bosch drill', brand: 'Bosch', product: 'Drill', model: '', title: 'Bosch Drill', question: 'q', gist: 'g', sources: [], updatedAt: 1000, kind: 'chat', ...over };
}

const DAY = 86_400_000;
const NOW = 1_000_000 + 7 * DAY;

function corruptedRowsAreRejected(): void {
  const valid = item();
  assert.equal(isValidShortlistItem(valid), true);
  assert.equal(isValidShortlistItem({ ...valid, id: '' }), false);
  assert.equal(isValidShortlistItem({ ...valid, key: '' }), false);
  assert.equal(isValidShortlistItem({ ...valid, title: '  ' }), false);
  assert.equal(isValidShortlistItem({ ...valid, addedAt: 0 }), false);
  assert.equal(isValidShortlistItem({ ...valid, savedPrice: Number.NaN }), false);
  assert.equal(isValidShortlistItem({ ...valid, savedPrice: -5 }), false);
  assert.equal(isValidShortlistItem({ ...valid, currency: 'eu' }), false);
  assert.equal(isValidShortlistItem('nope'), false);
  assert.deepEqual(normalizeShortlist('nope'), []);
  assert.deepEqual(normalizeShortlist([valid, valid, { ...valid, id: 'b', title: 'x', key: 'x', addedAt: 5 }, { bad: true }]).map(r => r.id), ['a', 'b']);
}

function oneRowPerProductIdentity(): void {
  let list: ShortlistItem[] = [];
  list = upsertShortlistItem(list, { key: 'Bosch  Drill', title: 'Bosch Drill', savedPrice: 100, currency: 'EUR' }, 1000);
  list = upsertShortlistItem(list, { key: 'other', title: 'Other', savedPrice: null }, 1000);
  assert.equal(list.length, 2);
  const before = list.find(r => r.key === 'bosch drill');
  list = upsertShortlistItem(list, { key: 'bosch drill', title: 'Bosch Drill GSB', savedPrice: 90 }, 5000);
  assert.equal(list.length, 2);
  const after = list.find(r => r.key === 'bosch drill');
  assert.equal(after?.id, before?.id);
  assert.equal(after?.title, 'Bosch Drill GSB');
  assert.equal(after?.addedAt, 1000);
  assert.equal(after?.savedPrice, 90);
  list = removeShortlistItem(list, after!.id);
  assert.deepEqual(list.map(r => r.key), ['other']);
}

function watchesMatchByFoldedName(): void {
  const w = watch();
  assert.equal(matchWatch(item({ title: 'BOSCH   Drill' }), [w])?.id, 'w1');
  assert.equal(matchWatch(item({ title: 'Bosch Drill GSB 18V' }), [w])?.id, 'w1');
  assert.equal(matchWatch(item({ title: 'Other Thing' }), [w]), null);
  assert.equal(matchWatch(item(), []), null);
}

function aDropNeedsAWatchBelowTheSavedPrice(): void {
  const saved = item({ savedPrice: 100 });
  assert.deepEqual(priceDropStatus(saved, watch({ lastPrice: 80 })), { kind: 'drop', percent: 20 });
  assert.deepEqual(priceDropStatus(saved, watch({ lastPrice: 100 })), { kind: 'none' });
  assert.deepEqual(priceDropStatus(saved, watch({ lastPrice: 120 })), { kind: 'none' });
  assert.deepEqual(priceDropStatus(saved, watch({ lastPrice: null })), { kind: 'none' });
  assert.deepEqual(priceDropStatus(saved, null), { kind: 'none' });
  assert.deepEqual(priceDropStatus(item({ savedPrice: null }), watch({ lastPrice: 80 })), { kind: 'none' });
  assert.deepEqual(currentPrice(saved, watch({ lastPrice: 80 })), { price: 80, currency: 'EUR' });
  assert.deepEqual(currentPrice(saved, null), { price: 100, currency: 'EUR' });
}

function theCheapestWinsWhenPriceWeighsMost(): void {
  const items = [
    item({ id: 'a', key: 'a', title: 'A', savedPrice: 100, addedAt: NOW - 7 * DAY }),
    item({ id: 'b', key: 'b', title: 'B', savedPrice: 80, addedAt: NOW }),
    item({ id: 'c', key: 'c', title: 'C', savedPrice: 90, addedAt: NOW - 14 * DAY }),
  ];
  const catalog = [
    entry({ key: 'a', sources: [{ title: 's1', host: 'h', url: 'https://h/1' }, { title: 's2', host: 'h', url: 'https://h/2' }, { title: 's3', host: 'h', url: 'https://h/3' }, { title: 's4', host: 'h', url: 'https://h/4' }] }),
    entry({ key: 'b', sources: [{ title: 's1', host: 'h', url: 'https://h/1' }, { title: 's2', host: 'h', url: 'https://h/2' }] }),
    entry({ key: 'c', sources: [] }),
  ];
  const weights: DecisionWeights = { price: 'high', evidence: 'low', recency: 'low' };
  const ranked = rankShortlist(items, catalog, [], weights, NOW);
  assert.deepEqual(ranked.map(r => r.item.id), ['b', 'c', 'a']);
  assert.deepEqual(ranked[0].reasons, ['price', 'recency']);
  for (const row of ranked) assert.ok(row.score >= 0 && row.score <= 1);
}

function theBestEvidenceWinsWhenEvidenceWeighsMost(): void {
  const items = [
    item({ id: 'a', key: 'a', title: 'A', savedPrice: 100, addedAt: NOW - 7 * DAY }),
    item({ id: 'b', key: 'b', title: 'B', savedPrice: 80, addedAt: NOW }),
    item({ id: 'c', key: 'c', title: 'C', savedPrice: 90, addedAt: NOW - 14 * DAY }),
  ];
  const catalog = [
    entry({ key: 'a', sources: [{ title: 's1', host: 'h', url: 'https://h/1' }, { title: 's2', host: 'h', url: 'https://h/2' }, { title: 's3', host: 'h', url: 'https://h/3' }, { title: 's4', host: 'h', url: 'https://h/4' }] }),
    entry({ key: 'b', sources: [{ title: 's1', host: 'h', url: 'https://h/1' }, { title: 's2', host: 'h', url: 'https://h/2' }] }),
    entry({ key: 'c', sources: [] }),
  ];
  const ranked = rankShortlist(items, catalog, [], { price: 'low', evidence: 'high', recency: 'low' }, NOW);
  assert.deepEqual(ranked.map(r => r.item.id), ['a', 'b', 'c']);
  assert.deepEqual(ranked[0].reasons, ['evidence']);
}

function watchesFeedThePriceScore(): void {
  const items = [
    item({ id: 'a', key: 'a', title: 'A', savedPrice: 100, addedAt: NOW }),
    item({ id: 'b', key: 'b', title: 'B', savedPrice: 100, addedAt: NOW }),
  ];
  // A's watch saw a drop to 50, B has no watch: A must win on price.
  const watches = [watch({ name: 'A', lastPrice: 50 })];
  const ranked = rankShortlist(items, [], watches, { price: 'high', evidence: 'low', recency: 'low' }, NOW);
  assert.deepEqual(ranked.map(r => r.item.id), ['a', 'b']);
  assert.ok(ranked[0].reasons.includes('price'));
}

function tiesBreakDeterministically(): void {
  const items = [
    item({ id: 'a', key: 'a', title: 'Same', savedPrice: 50, addedAt: NOW - DAY }),
    item({ id: 'b', key: 'b', title: 'Same', savedPrice: 50, addedAt: NOW }),
  ];
  const ranked = rankShortlist(items, [], [], { price: 'standard', evidence: 'standard', recency: 'standard' }, NOW);
  assert.deepEqual(ranked.map(r => r.item.id), ['b', 'a']);
  assert.equal(rankShortlist([], [], [], { price: 'standard', evidence: 'standard', recency: 'standard' }, NOW).length, 0);
}

function main(): void {
  corruptedRowsAreRejected();
  oneRowPerProductIdentity();
  watchesMatchByFoldedName();
  aDropNeedsAWatchBelowTheSavedPrice();
  theCheapestWinsWhenPriceWeighsMost();
  theBestEvidenceWinsWhenEvidenceWeighsMost();
  watchesFeedThePriceScore();
  tiesBreakDeterministically();
  process.stdout.write('Shortlist checks passed.\n');
}
main();

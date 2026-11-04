import assert from 'node:assert/strict';
import { createSerializedWatchMutation, createWatchChecker, explicitPrice, isValidPriceWatch, matchingListingPrice, safeProductUrl, type PriceWatch } from '../src/engine/priceTrackingCore';

function watch(): PriceWatch { return { id: 'w1', url: 'https://shop.example/item', name: 'Lamp', currency: 'EUR', intervalHours: 24, lastPrice: 19.9, lastObservedAt: 10, nextCheckAt: 0, paused: false }; }

function urlsAreRestricted(): void {
  assert.equal(safeProductUrl('https://shop.example/item#details'), 'https://shop.example/item');
  for (const url of ['javascript:alert(1)', 'file:///etc/passwd', 'https://user:pass@shop.example/item', 'http://localhost/item', 'http://127.0.0.1/item', 'http://192.168.1.2/item', 'http://printer.local/item', 'http://[::1]/item']) assert.equal(safeProductUrl(url), '', url);
}

function pricesNeedOneClearAmount(): void {
  assert.equal(explicitPrice('Price EUR 1.234,56', 'EUR'), 1234.56);
  assert.equal(explicitPrice('1 234,50 €', 'EUR'), 1234.5);
  assert.equal(explicitPrice('$1,299.00', 'USD'), 1299);
  assert.equal(explicitPrice('Now EUR 40, was EUR 60', 'EUR'), null);
  assert.equal(explicitPrice('EUR 10 or EUR 20', 'EUR'), null);
  assert.equal(explicitPrice('Free shipping; price 20', 'EUR'), null);
  assert.equal(explicitPrice('TRY 1.234,00', 'TRY'), 1234);
}

function onlyExactPageBodyCanMatch(): void {
  const exact = { url: watch().url, title: 'Lamp', snippet: 'EUR 99', pageText: 'EUR 49,90' };
  assert.equal(matchingListingPrice([exact], watch().url, 'EUR'), 49.9);
  assert.equal(matchingListingPrice([{ ...exact, url: 'https://shop.example/other' }], watch().url, 'EUR'), null);
  assert.equal(matchingListingPrice([{ ...exact, pageText: '' }], watch().url, 'EUR'), null);
  assert.equal(matchingListingPrice([exact, exact], watch().url, 'EUR'), null);
}

function corruptedSavedRecordsAreRejected(): void {
  const valid = watch();
  assert.equal(isValidPriceWatch(valid), true);
  assert.equal(isValidPriceWatch({ ...valid, intervalHours: 0 }), false);
  assert.equal(isValidPriceWatch({ ...valid, nextCheckAt: Number.NaN }), false);
  assert.equal(isValidPriceWatch({ ...valid, lastObservedAt: Number.POSITIVE_INFINITY }), false);
  assert.equal(isValidPriceWatch({ ...valid, lastPrice: Number.NaN }), false);
  assert.equal(isValidPriceWatch({ ...valid, currency: 'US' }), false);
}

async function distinctConcurrentChecksKeepBothMutations(): Promise<void> {
  const first = watch();
  const second = { ...watch(), id: 'w2', url: 'https://shop.example/item-2' };
  let rows = [first, second];
  const mutate = createSerializedWatchMutation(async () => rows, async next => { await new Promise(resolve => setTimeout(resolve, 5)); rows = next; });
  const checker = createWatchChecker({
    load: async () => rows, save: async next => { rows = next; }, mutate,
    read: async url => url.endsWith('item-2') ? 'EUR 29,00' : 'EUR 14,00',
    search: async () => ({ hits: [] }), now: () => 500,
  });
  await Promise.all([checker('w1'), checker('w2')]);
  assert.equal(rows.find(w => w.id === 'w1')?.lastPrice, 14);
  assert.equal(rows.find(w => w.id === 'w2')?.lastPrice, 29);
}

async function aRemovedWatchCannotReappearAfterItsCheck(): Promise<void> {
  let rows = [watch()], release!: (body: string) => void;
  const readGate = new Promise<string>(resolve => { release = resolve; });
  const mutate = createSerializedWatchMutation(async () => rows, async next => { rows = next; });
  const checker = createWatchChecker({ load: async () => rows, save: async next => { rows = next; }, mutate, read: async () => readGate, search: async () => ({ hits: [] }), now: () => 600 });
  const pending = checker('w1');
  await Promise.resolve();
  await Promise.resolve();
  await mutate(current => current.filter(w => w.id !== 'w1'));
  release('EUR 12,00');
  await pending;
  assert.equal(rows.length, 0);
}

async function checksDoNotOverlapAndFailuresKeepLastObservation(): Promise<void> {
  let rows = [watch()], release!: (value: { hits: [] }) => void, calls = 0;
  const searchGate = new Promise<{ hits: [] }>(resolve => { release = resolve; });
  const checker = createWatchChecker({ load: async () => rows, save: async next => { rows = next; }, read: async () => '', search: async () => { calls += 1; return searchGate; }, now: () => 100 });
  const first = checker('w1');
  await Promise.resolve();
  await checker('w1');
  assert.equal(calls, 1, 'parallel requests share one provider operation');
  release({ hits: [] });
  await first;
  assert.equal(rows[0].lastPrice, 19.9);
  assert.equal(rows[0].lastObservedAt, 10);
  assert.match(rows[0].lastError || '', /unambiguous/);

  const failing = createWatchChecker({ load: async () => rows, save: async next => { rows = next; }, read: async () => { throw new Error('offline'); }, search: async () => { throw new Error('offline'); }, now: () => 200 });
  await failing('w1');
  assert.equal(rows[0].lastPrice, 19.9);
  assert.equal(rows[0].lastObservedAt, 10);
  assert.match(rows[0].lastError || '', /last valid observation was kept/);
}

async function main() {
  urlsAreRestricted(); pricesNeedOneClearAmount(); onlyExactPageBodyCanMatch(); corruptedSavedRecordsAreRejected();
  await checksDoNotOverlapAndFailuresKeepLastObservation();
  await distinctConcurrentChecksKeepBothMutations();
  await aRemovedWatchCannotReappearAfterItsCheck();
  process.stdout.write('Price tracking checks passed.\n');
}
main().catch(error => { console.error(error); process.exit(1); });

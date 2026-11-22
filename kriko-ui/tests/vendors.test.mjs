import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

/**
 * The vendor scorecard's numbers and its sentences.
 *
 * `vendors.ts`, `quotes.ts` and `money.ts` are pure, so they are transpiled and
 * imported here directly. Every test states the estimate it reads, so the
 * counts can be recomputed by hand.
 */

let directory, vendors
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-vendors-'))
  const modules = [
    ['src/engine/money.ts', 'money.mjs'],
    ['src/engine/quotes.ts', 'quotes.mjs'],
    ['src/engine/vendors.ts', 'vendors.mjs'],
  ]
  for (const [source, name] of modules) {
    const code = await readFile(source, 'utf8')
    const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
      .replace(/from '\.\/([a-z]+)'/g, "from './$1.mjs'")
    await writeFile(join(directory, name), built)
  }
  vendors = await import(pathToFileURL(join(directory, 'vendors.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const TODAY = new Date(2026, 10, 20)

/** A quote as the Estimate screen saves it. Prices are net with no VAT unless a test says otherwise. */
const quote = (vendor, unit_price, extra = {}) => ({
  quote_id: `q-${vendor}-${unit_price}-${Math.random().toString(36).slice(2, 8)}`,
  vendor,
  seller: '',
  url: '',
  unit_price,
  currency: 'TRY',
  vat_rate: 0,
  vat_included: false,
  delivery_days: null,
  warranty_months: null,
  quote_date: '2026-11-01',
  valid_until: '',
  note: '',
  selected: false,
  ...extra,
})

const line = (id, quotes, extra = {}) => ({
  line_id: id,
  subject_id: `subject-${id}`,
  pack_id: 'pack',
  label: `Product ${id}`,
  quantity: 1,
  unit_price: null,
  note: '',
  depreciation: 'straight_line',
  life_years: null,
  salvage: null,
  vuk_rate: null,
  quotes: quotes.map((item, index) => ({ ...item, selected: index === 0 })),
  ...extra,
})

const estimate = (id, lines, extra = {}) => ({
  estimate_id: id,
  name: `Estimate ${id}`,
  currency: 'TRY',
  years: 5,
  maintenance_pct: 5,
  discount_pct: 8,
  vat_rate: 20,
  fx: {},
  created_at: '2026-11-01',
  updated_at: '2026-11-01',
  lines,
  ...extra,
})

const find = (stats, name) => stats.find((stat) => stat.vendor === name)

// ── grouping ──

test('spellings that differ only in case, diacritics, punctuation and legal form are one vendor', () => {
  assert.equal(vendors.vendorKey('Ergo Ltd. Şti.'), 'ergo')
  assert.equal(vendors.vendorKey('ERGO ltd sti'), 'ergo')
  assert.equal(vendors.vendorKey('  Ergo  '), 'ergo')
  assert.equal(vendors.vendorKey('Öz Makine A.Ş.'), 'oz makine')
  assert.equal(vendors.vendorKey('OZ MAKINE AS'), 'oz makine')
  assert.equal(vendors.vendorKey('Dotless ılık'), 'dotless ilik')
  assert.equal(vendors.vendorKey('Acme Inc.'), 'acme')
})

test('a vendor is grouped by its normalised key and shown in the most common spelling', () => {
  const est = estimate('e1', [
    line('a', [quote('Ergo Ltd.', 100), quote('Other', 120)]),
    line('b', [quote('ERGO', 90)]),
    line('c', [quote('Ergo Ltd.', 80)]),
  ])
  const stats = vendors.vendorStats([est], TODAY)
  assert.equal(stats.length, 2)
  const ergo = find(stats, 'Ergo Ltd.')
  assert.ok(ergo, 'the most common spelling is the display name')
  assert.equal(ergo.quotes, 3)
  assert.equal(ergo.lines, 3)
  assert.equal(ergo.estimates, 1)
})

test('a quote with no vendor name falls back to its seller, and with neither it is not a vendor', () => {
  const est = estimate('e1', [
    line('a', [quote('', 100, { seller: 'Shop Co' }), quote('', 110)]),
  ])
  const stats = vendors.vendorStats([est], TODAY)
  assert.deepEqual(stats.map((stat) => stat.vendor), ['Shop Co'])
  assert.equal(stats[0].quotes, 1)
})

// ── won ──

test('a quote is won only as the best landed cost among at least two comparable quotes', () => {
  const est = estimate('e1', [
    line('contest', [quote('Cheap', 100), quote('Dear', 150)]),
    line('alone', [quote('Solo', 90)]),
  ])
  const stats = vendors.vendorStats([est], TODAY)
  const cheap = find(stats, 'Cheap')
  assert.equal(cheap.won, 1)
  assert.equal(cheap.contested, 1)
  assert.equal(find(stats, 'Dear').won, 0)
  assert.equal(find(stats, 'Dear').contested, 1)
  const solo = find(stats, 'Solo')
  assert.equal(solo.won, 0, 'a lone quote on a line is not a win')
  assert.equal(solo.contested, 0, 'a lone quote does not count as a comparable line')
})

test('a quote with no rate for its currency is not compared, so it cannot win', () => {
  const est = estimate('e1', [
    line('a', [quote('Usd Shop', 50, { currency: 'USD' }), quote('Local', 120)]),
  ], { fx: {} })
  const stats = vendors.vendorStats([est], TODAY)
  assert.equal(find(stats, 'Usd Shop').contested, 0)
  assert.equal(find(stats, 'Usd Shop').won, 0)
  assert.equal(find(stats, 'Local').won, 0, 'with one comparable quote there is no contest')
})

test('a quote in another currency is compared in the estimate currency once a rate is known', () => {
  const est = estimate('e1', [
    line('a', [quote('Usd Shop', 5, { currency: 'USD' }), quote('Local', 120)]),
  ], { fx: { USD: 20, TRY: 1 } })
  const stats = vendors.vendorStats([est], TODAY)
  assert.equal(find(stats, 'Usd Shop').won, 1, '5 USD at 20 TRY is 100, cheaper than 120 TRY')
  assert.equal(find(stats, 'Local').won, 0)
  assert.equal(find(stats, 'Local').contested, 1)
})

test('an unpriced quote is counted as unpriced and is never compared', () => {
  const est = estimate('e1', [
    line('a', [quote('Blank', null), quote('Priced', 100)]),
  ])
  const stats = vendors.vendorStats([est], TODAY)
  assert.equal(find(stats, 'Blank').unpriced, 1)
  assert.equal(find(stats, 'Blank').contested, 0)
  assert.equal(find(stats, 'Priced').won, 0)
})

// ── averages ──

test('a missing delivery time is not averaged as zero', () => {
  const est = estimate('e1', [
    line('a', [quote('Ergo', 100, { delivery_days: 4 })]),
    line('b', [quote('Ergo', 100, { delivery_days: null })]),
    line('c', [quote('Ergo', 100, { delivery_days: 8 })]),
  ])
  const [ergo] = vendors.vendorStats([est], TODAY)
  assert.equal(ergo.avgDeliveryDays, 6)
  assert.equal(ergo.avgWarrantyMonths, null, 'no warranty stated is no average at all')
})

test('an average with no stated value at all is null, never zero', () => {
  const est = estimate('e1', [line('a', [quote('Ergo', 100)])])
  const [ergo] = vendors.vendorStats([est], TODAY)
  assert.equal(ergo.avgDeliveryDays, null)
  assert.equal(ergo.avgWarrantyMonths, null)
})

// ── expired and risk ──

test('expired quotes and medium or high risk quotes are counted, and a low risk quote is not', () => {
  const est = estimate('e1', [
    line('a', [quote('Ergo', 100, { valid_until: '2026-11-10', risk: { level: 'red', reasons: [] } })]),
    line('b', [quote('Ergo', 100, { valid_until: '2026-12-10', risk: { level: 'amber', reasons: [] } })]),
    line('c', [quote('Ergo', 100, { valid_until: '2026-12-01', risk: { level: 'green', reasons: [] } })]),
    line('d', [quote('Ergo', 100)]),
  ])
  const [ergo] = vendors.vendorStats([est], TODAY)
  assert.equal(ergo.expired, 1)
  assert.equal(ergo.redOrAmber, 2)
  assert.equal(ergo.lastQuoteDate, '2026-11-01')
})

test('the last quote date is the latest one any quote states', () => {
  const est = estimate('e1', [
    line('a', [quote('Ergo', 100, { quote_date: '2026-10-02' })]),
    line('b', [quote('Ergo', 100, { quote_date: '2026-11-15' })]),
    line('c', [quote('Ergo', 100, { quote_date: '' })]),
  ])
  const [ergo] = vendors.vendorStats([est], TODAY)
  assert.equal(ergo.lastQuoteDate, '2026-11-15')
})

test('a vendor counts the currencies its quotes are in, each once', () => {
  const est = estimate('e1', [
    line('a', [quote('Ergo', 100, { currency: 'USD' })]),
    line('b', [quote('Ergo', 100, { currency: 'EUR' })]),
    line('c', [quote('Ergo', 100, { currency: 'usd' })]),
  ], { fx: { USD: 30, EUR: 33 } })
  const [ergo] = vendors.vendorStats([est], TODAY)
  assert.deepEqual(ergo.currencies, ['EUR', 'USD'])
})

// ── sort order ──

test('vendors sort by wins, then by quote count', () => {
  const est = estimate('e1', [
    line('a', [quote('Many', 100), quote('Rival', 200)]),
    line('b', [quote('Many', 100), quote('Rival', 200)]),
    line('c', [quote('Many', 300), quote('Few', 150)]),
    line('d', [quote('Few', 100)]),
  ])
  const names = vendors.vendorStats([est], TODAY).map((stat) => stat.vendor)
  assert.deepEqual(names, ['Many', 'Few', 'Rival'])
})

test('a vendor with fewer wins but more quotes sorts below one with more wins', () => {
  const est = estimate('e1', [
    line('a', [quote('Wins', 100), quote('Filler', 200)]),
    line('b', [quote('Filler', 100)]),
    line('c', [quote('Filler', 100)]),
    line('d', [quote('Filler', 100)]),
  ])
  const names = vendors.vendorStats([est], TODAY).map((stat) => stat.vendor)
  assert.deepEqual(names, ['Wins', 'Filler'])
})

// ── the sentence ──

test('the sentence states the wins, the delivery and the expired count from the numbers alone', () => {
  const stat = {
    vendor: 'Ergo', quotes: 5, estimates: 2, lines: 5, won: 3, contested: 5, selected: 2,
    avgDeliveryDays: 6, avgWarrantyMonths: null, expired: 1, unpriced: 0, redOrAmber: 0,
    lastQuoteDate: '2026-11-01', currencies: ['TRY'],
  }
  assert.equal(
    vendors.vendorSentence(stat),
    'Best landed cost on 3 of 5 comparable lines. Delivery averages 6 days. 1 quote expired.',
  )
})

test('the sentence says a missing delivery is missing, and singular and plural words agree', () => {
  const base = {
    vendor: 'Ergo', quotes: 1, estimates: 1, lines: 1, won: 0, contested: 1, selected: 1,
    avgDeliveryDays: null, avgWarrantyMonths: 1, expired: 2, unpriced: 1, redOrAmber: 1,
    lastQuoteDate: '', currencies: ['TRY'],
  }
  assert.deepEqual(vendors.vendorSentences(base), [
    'Best landed cost on 0 of 1 comparable line.',
    'No delivery time given.',
    'Warranty averages 1 month.',
    '2 quotes expired.',
    '1 quote rated medium or high risk.',
    '1 without a price.',
  ])
})

test('a line that nothing else competes on is said plainly, not as a win rate', () => {
  const stat = {
    vendor: 'Solo', quotes: 2, estimates: 1, lines: 2, won: 0, contested: 0, selected: 2,
    avgDeliveryDays: 3.25, avgWarrantyMonths: null, expired: 0, unpriced: 0, redOrAmber: 0,
    lastQuoteDate: '', currencies: ['TRY'],
  }
  const sentences = vendors.vendorSentences(stat)
  assert.equal(sentences[0], 'No line compares it with another quote yet.')
  assert.equal(sentences[1], 'Delivery averages 3.3 days.')
  assert.ok(!vendors.vendorSentence(stat).includes('0 of 0'))
})

test('the search fold ignores case and diacritics', () => {
  assert.equal(vendors.foldText('Öz Makİne'), 'oz makine')
  assert.ok(vendors.foldText('Ergo Ltd. Şti.').includes(vendors.foldText('şti')))
})

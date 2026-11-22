// What-if arithmetic on saved estimates: a copy keeps every quote and drops the
// ids; a comparison matches lines, subtracts only within one currency, and says
// in words why a difference is not shown.

import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

let directory
let scenario

const MODULES = [
  ['src/engine/scenario.ts', 'scenario.mjs'],
  ['src/engine/forecast.ts', 'forecast.mjs'],
  ['src/engine/quotes.ts', 'quotes.mjs'],
  ['src/engine/money.ts', 'money.mjs'],
]

before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-scenario-'))
  for (const [source, name] of MODULES) {
    const code = await readFile(new URL(`../${source}`, import.meta.url), 'utf8')
    const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
      .replace(/from '\.\/([A-Za-z0-9]+)'/g, "from './$1.mjs'")
    await writeFile(join(directory, name), built)
  }
  scenario = await import(pathToFileURL(join(directory, 'scenario.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const FX = { TRY: 1, EUR: 40, USD: 35, source: 'manual' }

const quote = (patch = {}) => ({
  quote_id: 'qid-1',
  vendor: 'Shop A',
  seller: '',
  url: '',
  unit_price: 100,
  currency: 'TRY',
  vat_rate: 0,
  vat_included: false,
  delivery_days: 7,
  warranty_months: 12,
  quote_date: '',
  valid_until: '',
  note: '',
  selected: true,
  risk: { level: 'green', reasons: [] },
  ...patch,
})

const line = (patch = {}) => ({
  line_id: 'lid-1',
  subject_id: 'laptop',
  pack_id: 'laptops',
  label: 'Office laptop',
  quantity: 2,
  unit_price: null,
  note: '',
  depreciation: 'straight_line',
  life_years: 4,
  salvage: null,
  vuk_rate: null,
  quotes: [quote()],
  ranking: [{ quote_id: 'qid-1', rank: 1, landed: 100, reasons: [] }],
  ...patch,
})

const estimate = (patch = {}) => ({
  estimate_id: 'e-a',
  name: 'Estimate A',
  currency: 'TRY',
  years: 3,
  maintenance_pct: 5,
  discount_pct: 8,
  vat_rate: 20,
  fx: FX,
  created_at: '',
  updated_at: '',
  lines: [],
  ...patch,
})

// ── copy ──

test('a copy is named "(copy)", carries no ids, and keeps every quote', () => {
  const source = estimate({
    lines: [line({
      quotes: [
        quote({ quote_id: 'qid-1', selected: true }),
        quote({ quote_id: 'qid-2', vendor: 'Shop B', selected: false, risk: { level: 'red', reasons: ['x'] } }),
      ],
    })],
  })
  const copy = scenario.copyPayload(source)
  assert.equal(copy.name, 'Estimate A (copy)')
  assert.equal(copy.estimate_id, '')
  assert.equal(copy.lines.length, 1)
  assert.equal(copy.lines[0].line_id, undefined)
  assert.equal(copy.lines[0].ranking, undefined)
  assert.deepEqual(copy.lines[0].quotes.map((q) => q.quote_id), ['', ''])
  assert.deepEqual(copy.lines[0].quotes.map((q) => q.vendor), ['Shop A', 'Shop B'])
  assert.deepEqual(copy.lines[0].quotes.map((q) => q.selected), [true, false])
  assert.equal(copy.lines[0].quotes[1].risk, undefined)
})

test('a copy does not change the estimate it was made from', () => {
  const source = estimate({ lines: [line()] })
  scenario.copyPayload(source)
  assert.equal(source.estimate_id, 'e-a')
  assert.equal(source.name, 'Estimate A')
  assert.equal(source.lines[0].line_id, 'lid-1')
  assert.equal(source.lines[0].quotes[0].quote_id, 'qid-1')
})

test('an untitled estimate copies as "Untitled estimate (copy)"', () => {
  assert.equal(scenario.copyPayload(estimate({ name: '  ' })).name, 'Untitled estimate (copy)')
})

// ── compare: matching ──

test('lines match by subject_id; the rest are listed as only in one estimate', () => {
  const a = estimate({ name: 'Alpha', lines: [line({ subject_id: 'S1', label: 'One' }), line({ subject_id: 'S2', label: 'Two' })] })
  const b = estimate({ estimate_id: 'e-b', name: 'Beta', lines: [line({ subject_id: 'S1', label: 'One' }), line({ subject_id: 'S3', label: 'Three' })] })
  const model = scenario.compareEstimates(a, b)
  assert.deepEqual(model.rows.map((row) => row.status), ['both', 'only_a', 'only_b'])
  assert.equal(model.rows[1].differenceNote, 'Only in Alpha')
  assert.equal(model.rows[2].differenceNote, 'Only in Beta')
  assert.equal(model.rows[1].b, null)
  assert.equal(model.rows[2].a, null)
})

test('a line with a different subject id still matches when its label is equal', () => {
  const a = estimate({ lines: [line({ subject_id: 'x1', label: 'Router' })] })
  const b = estimate({ estimate_id: 'e-b', lines: [line({ subject_id: 'y9', label: 'Router' })] })
  const model = scenario.compareEstimates(a, b)
  assert.equal(model.rows.length, 1)
  assert.equal(model.rows[0].status, 'both')
})

// ── compare: differences ──

test('the difference is B minus A on the line gross, when both are in one currency', () => {
  const a = estimate({ lines: [line({ quantity: 2, quotes: [quote({ unit_price: 100 })] })] })
  const b = estimate({ estimate_id: 'e-b', name: 'Beta', lines: [line({ quantity: 2, quotes: [quote({ unit_price: 120, vendor: 'Shop B' })] })] })
  const row = scenario.compareEstimates(a, b).rows[0]
  assert.equal(row.a.unitGross, 100)
  assert.equal(row.b.unitGross, 120)
  assert.equal(row.a.lineGross, 200)
  assert.equal(row.b.lineGross, 240)
  assert.equal(row.difference, 40)
  assert.equal(row.differenceNote, '')
  assert.equal(row.b.vendor, 'Shop B')
})

test('different currencies are never subtracted', () => {
  const a = estimate({ lines: [line({ quotes: [quote({ unit_price: 100, currency: 'TRY' })] })] })
  const b = estimate({ estimate_id: 'e-b', name: 'Beta', currency: 'EUR', lines: [line({ quotes: [quote({ unit_price: 3, currency: 'EUR' })] })] })
  const model = scenario.compareEstimates(a, b)
  assert.equal(model.sameCurrency, false)
  assert.equal(model.rows[0].difference, null)
  assert.match(model.rows[0].differenceNote, /different currencies/)
  assert.equal(model.totals.difference, null)
})

test('an unpriced line on either side is not comparable and is shown as no price', () => {
  const a = estimate({ lines: [line({ quotes: [quote({ unit_price: 100 })] })] })
  const b = estimate({ estimate_id: 'e-b', lines: [line({ quotes: [quote({ unit_price: null })] })] })
  const row = scenario.compareEstimates(a, b).rows[0]
  assert.equal(row.b.state, 'no_price')
  assert.equal(row.difference, null)
  assert.equal(row.differenceNote, 'Not comparable')
  assert.equal(scenario.compareEstimates(a, b).totals.b.withoutPrice, 1)
})

test('a quote with no rate is not comparable, and is never converted at 1', () => {
  const a = estimate({ lines: [line({ quotes: [quote({ unit_price: 100 })] })] })
  const b = estimate({
    estimate_id: 'e-b',
    fx: { TRY: 1, EUR: 0, USD: 0, source: 'manual' },
    lines: [line({ quotes: [quote({ unit_price: 10, currency: 'USD' })] })],
  })
  const row = scenario.compareEstimates(a, b).rows[0]
  assert.equal(row.b.state, 'no_rate')
  assert.equal(row.b.unitGross, null)
  assert.equal(row.difference, null)
  assert.equal(row.differenceNote, 'Not comparable')
})

test('totals show net, VAT and gross per estimate, and the difference only in one currency', () => {
  const a = estimate({ lines: [line({ quantity: 1, quotes: [quote({ unit_price: 100, vat_rate: 20, vat_included: false })] })] })
  const b = estimate({ estimate_id: 'e-b', name: 'Beta', lines: [line({ quantity: 1, quotes: [quote({ unit_price: 240, vat_rate: 20, vat_included: true })] })] })
  const model = scenario.compareEstimates(a, b)
  assert.ok(Math.abs(model.totals.a.gross - 120) < 1e-9)
  assert.ok(Math.abs(model.totals.a.net - 100) < 1e-9)
  assert.ok(Math.abs(model.totals.b.gross - 240) < 1e-9)
  assert.ok(Math.abs(model.totals.b.net - 200) < 1e-9)
  assert.ok(Math.abs(model.totals.difference.gross - 120) < 1e-9)
  assert.ok(Math.abs(model.totals.difference.net - 100) < 1e-9)
  assert.ok(Math.abs(model.totals.difference.vat - 20) < 1e-9)
})

test('totals of estimates in different currencies have no difference', () => {
  const a = estimate({ lines: [line({ quotes: [quote({ unit_price: 100 })] })] })
  const b = estimate({ estimate_id: 'e-b', currency: 'USD', lines: [line({ quotes: [quote({ unit_price: 10, currency: 'USD' })] })] })
  const model = scenario.compareEstimates(a, b)
  assert.equal(model.totals.difference, null)
  assert.equal(model.a.currency, 'TRY')
  assert.equal(model.b.currency, 'USD')
})

test('an unpriced line is counted in the totals of its estimate, never read as zero', () => {
  const a = estimate({ lines: [line({ quotes: [quote({ unit_price: 100 })] }), line({ subject_id: 'dock', label: 'Dock', quotes: [] , unit_price: null })] })
  const totals = scenario.totalsOf(a)
  assert.equal(totals.withoutPrice, 1)
  assert.equal(totals.gross, 200)
})

test('a line with no quote but a typed price is priced as typed, and says it is a migrated price', () => {
  const a = estimate({ lines: [line({ quotes: [], unit_price: 50, quantity: 2 })] })
  const b = estimate({ estimate_id: 'e-b', lines: [line({ quotes: [quote({ unit_price: 60 })] })] })
  const row = scenario.compareEstimates(a, b).rows[0]
  assert.equal(row.a.vendor, 'Migrated price')
  assert.equal(row.a.unitGross, 50)
  assert.equal(row.difference, 20)
})

test('the forecast of an estimate reads the same capital as its totals', () => {
  const a = estimate({ lines: [line({ quantity: 3, quotes: [quote({ unit_price: 100, vat_rate: 20, vat_included: false })] })] })
  const model = scenario.forecastOf({ ...a, years: a.years, maintenance_pct: a.maintenance_pct, discount_pct: a.discount_pct })
  assert.ok(Math.abs(model.capital - scenario.totalsOf(a).gross) < 1e-9)
  assert.ok(Math.abs(model.capital - 360) < 1e-9)
})

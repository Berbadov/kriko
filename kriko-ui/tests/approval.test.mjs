// The approval sheet's model: totals that equal the sums of the lines, an
// unpriced line listed as "No price" and counted, an uncomparable quote
// labelled "No rate", and no amount converted at 1 across currencies.

import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

let directory
let approval

const MODULES = [
  ['src/engine/approval.ts', 'approval.mjs'],
  ['src/engine/scenario.ts', 'scenario.mjs'],
  ['src/engine/forecast.ts', 'forecast.mjs'],
  ['src/engine/quotes.ts', 'quotes.mjs'],
  ['src/engine/money.ts', 'money.mjs'],
]

before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-approval-'))
  for (const [source, name] of MODULES) {
    const code = await readFile(new URL(`../${source}`, import.meta.url), 'utf8')
    const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
      .replace(/from '\.\/([A-Za-z0-9]+)'/g, "from './$1.mjs'")
    await writeFile(join(directory, name), built)
  }
  approval = await import(pathToFileURL(join(directory, 'approval.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const TODAY = new Date(2026, 10, 20)
const FX = { TRY: 1, EUR: 40, USD: 35, source: 'manual' }

const quote = (patch = {}) => ({
  quote_id: '',
  vendor: 'Shop A',
  seller: '',
  url: '',
  unit_price: 100,
  currency: 'TRY',
  vat_rate: 20,
  vat_included: false,
  delivery_days: 7,
  warranty_months: 12,
  quote_date: '',
  valid_until: '2026-12-31',
  note: '',
  selected: true,
  ...patch,
})

const line = (patch = {}) => ({
  subject_id: 'laptop',
  pack_id: 'laptops',
  label: 'Office laptop',
  quantity: 1,
  unit_price: null,
  note: '',
  depreciation: 'straight_line',
  life_years: 4,
  salvage: null,
  vuk_rate: null,
  quotes: [],
  ...patch,
})

const estimate = (patch = {}) => ({
  estimate_id: 'e1',
  name: 'Office laptops',
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

/** Three lines: two priced in TRY (one net, one gross), one with no price. */
const basic = () => estimate({
  lines: [
    line({ subject_id: 'laptop', label: 'Office laptop', quantity: 2, quotes: [quote({ unit_price: 100, vat_included: false })] }),
    line({ subject_id: 'screen', label: 'Monitor', quantity: 1, quotes: [quote({ unit_price: 240, vat_included: true, vendor: 'Shop B' })] }),
    line({ subject_id: 'dock', label: 'Dock', quantity: 3, quotes: [quote({ unit_price: null, vendor: 'Shop C' })] }),
  ],
})

test('totals are the sums of the priced lines: net, VAT and gross', () => {
  const model = approval.buildApproval(basic(), {}, TODAY)
  // Laptops: 2 x 100 net + 20% = 240 gross. Monitor: 240 gross, 200 net, 40 VAT.
  assert.ok(Math.abs(model.totals.gross - 480) < 1e-9)
  assert.ok(Math.abs(model.totals.net - 400) < 1e-9)
  assert.ok(Math.abs(model.totals.vat - 80) < 1e-9)
  assert.ok(Math.abs(model.totals.net + model.totals.vat - model.totals.gross) < 1e-9)
  // The forecast's capital is the same gross the sheet prints.
  assert.ok(Math.abs(model.forecast.capital - model.totals.gross) < 1e-9)
})

test('an unpriced line is listed as "No price" and counted, not read as free', () => {
  const model = approval.buildApproval(basic(), {}, TODAY)
  const dock = model.lines.find((row) => row.product === 'Dock')
  assert.equal(dock.state, 'no_price')
  assert.equal(dock.unitWord, 'No price')
  assert.equal(dock.lineWord, 'No price')
  assert.equal(model.totals.withoutPrice, 1)
  assert.ok(Math.abs(model.totals.gross - 480) < 1e-9, 'the unpriced line adds nothing')
})

test('a quote in a currency with no rate is "No rate" and is never converted at 1', () => {
  const model = approval.buildApproval(estimate({
    fx: { TRY: 1, EUR: 40, USD: 0, source: 'manual' },
    lines: [line({ quotes: [quote({ unit_price: 10, currency: 'USD', vat_rate: 0 })] })],
  }), {}, TODAY)
  const row = model.lines[0]
  assert.equal(row.state, 'no_rate')
  assert.equal(row.unitWord, 'No rate')
  assert.equal(model.totals.withoutRate, 1)
  assert.equal(model.totals.gross, 0)
  assert.doesNotMatch(approval.approvalText(model), / 10 TRY/)
})

test('with a rate, the USD quote converts at the stated rate, not at 1', () => {
  const model = approval.buildApproval(estimate({
    lines: [line({ quotes: [quote({ unit_price: 10, currency: 'USD', vat_rate: 0 })] })],
  }), {}, TODAY)
  assert.equal(model.lines[0].state, 'priced')
  assert.ok(Math.abs(model.lines[0].unitGross - 350) < 1e-9, '10 USD at 35 TRY is 350 TRY')
  assert.ok(Math.abs(model.totals.gross - 350) < 1e-9)
})

test('the quote that lost is named with its landed difference, from the numbers', () => {
  const model = approval.buildApproval(estimate({
    lines: [line({
      quantity: 1,
      quotes: [
        quote({ quote_id: 'q1', vendor: 'Shop A', unit_price: 100, vat_rate: 20, selected: true }),
        quote({ quote_id: 'q2', vendor: 'Shop B', unit_price: 110, vat_rate: 20, selected: false }),
      ],
      ranking: [
        { quote_id: 'q1', rank: 1, landed: 120, reasons: ['120.00 TRY gross at 1 TRY = 1 TRY'] },
        { quote_id: 'q2', rank: 2, landed: 132, reasons: ['132.00 TRY gross at 1 TRY = 1 TRY'] },
      ],
    })],
  }), {}, TODAY)
  const alt = model.lines[0].alternative
  assert.equal(alt.vendor, 'Shop B')
  assert.equal(alt.rank, 2)
  assert.ok(Math.abs(alt.difference - 12) < 1e-9)
  assert.match(alt.summary, /12 TRY more per unit landed than the selected quote, ranked 2 by landed cost\./)
  assert.deepEqual(alt.reasons, ['132.00 TRY gross at 1 TRY = 1 TRY'])
})

test('an alternative in a currency with no rate is uncomparable; with a rate it is compared', () => {
  const model = approval.buildApproval(estimate({
    lines: [line({
      quotes: [
        quote({ quote_id: 'q1', vendor: 'Shop A', unit_price: 100, vat_rate: 0, selected: true }),
        quote({ quote_id: 'q2', vendor: 'Shop Z', unit_price: 5, currency: 'EUR', vat_rate: 0, selected: false }),
      ],
    })],
  }), {}, TODAY)
  // With a EUR rate in the estimate, the EUR quote is comparable: 5 EUR at 40 is 200 TRY.
  const alt = model.lines[0].alternative
  assert.equal(alt.state, 'priced')
  assert.ok(Math.abs(alt.difference - 100) < 1e-9)
  const noRate = approval.buildApproval(estimate({
    fx: { TRY: 1, EUR: 0, USD: 0, source: 'manual' },
    lines: [line({
      quotes: [
        quote({ quote_id: 'q1', vendor: 'Shop A', unit_price: 100, vat_rate: 0, selected: true }),
        quote({ quote_id: 'q2', vendor: 'Shop Z', unit_price: 5, currency: 'EUR', vat_rate: 0, selected: false }),
      ],
    })],
  }), {}, TODAY).lines[0].alternative
  assert.equal(noRate.state, 'no_rate')
  assert.match(noRate.summary, /No rate from EUR to TRY, so it cannot be compared\./)
})

test('serious known problems are one sentence each, most serious first; the rest are only counted', () => {
  const claims = {
    laptop: [
      { severity: 'low', domain: 'x', title: 'Paint chips' },
      { severity: 'critical', domain: 'fuel', title: 'Fuel line can split' },
      { severity: 'high', domain: 'heat', title: 'Overheats under load' },
    ],
  }
  const model = approval.buildApproval(basic(), claims, TODAY)
  const laptop = model.lines.find((row) => row.product === 'Office laptop')
  assert.deepEqual(laptop.problems, ['Fuel line can split.', 'Overheats under load.'])
  assert.equal(laptop.known, 3)
})

test('a product whose problems were never read says so; one with none says so too', () => {
  const model = approval.buildApproval(basic(), { laptop: [] }, TODAY)
  const laptop = model.lines.find((row) => row.product === 'Office laptop')
  assert.deepEqual(laptop.problems, [])
  assert.equal(laptop.known, 0)
  const monitor = model.lines.find((row) => row.product === 'Monitor')
  assert.equal(monitor.problems, null)
  assert.equal(monitor.known, null)
})

test('quote terms are words: delivery, warranty, validity, and the risk level', () => {
  const model = approval.buildApproval(estimate({
    lines: [line({
      quotes: [quote({
        delivery_days: 1,
        warranty_months: null,
        valid_until: '2026-11-10',
        risk: { level: 'red', reasons: ['no seller named'] },
      })],
    })],
  }), {}, TODAY)
  const row = model.lines[0]
  assert.equal(row.delivery, '1 day')
  assert.equal(row.warranty, 'Not stated')
  assert.match(row.validity, /2026-11-10 \(expired\)/)
  assert.equal(row.validityExpired, true)
  assert.equal(row.risk, 'High')
  assert.deepEqual(row.riskReasons, ['no seller named'])
})

test('a quote with no risk reading is "Not rated", not "Low"', () => {
  const model = approval.buildApproval(basic(), {}, TODAY)
  assert.equal(model.lines[0].risk, 'Not rated')
})

test('the date is the local calendar day, and a TCMB rate says where it came from', () => {
  const model = approval.buildApproval(estimate({ fx: { TRY: 1, EUR: 50, USD: 40, source: 'TCMB', date: '2026-11-19' } }), {}, TODAY)
  assert.equal(model.date, '2026-11-20')
  assert.equal(model.rates, 'Central Bank bulletin of 2026-11-19')
  assert.equal(approval.buildApproval(basic(), {}, TODAY).rates, 'Typed by hand')
})

test('the plain-text summary carries the totals, the words, and the signature lines', () => {
  const model = approval.buildApproval(basic(), { laptop: [{ severity: 'critical', domain: 'x', title: 'Fuel line can split' }] }, TODAY)
  const text = approval.approvalText(model)
  assert.match(text, /^Office laptops/)
  assert.match(text, /Net 400 TRY, VAT 80 TRY, gross 480 TRY\./)
  assert.match(text, /1 line without a price, counted and not in the totals\./)
  assert.match(text, /Serious: Fuel line can split\./)
  assert.match(text, /Unit landed: No price\./)
  assert.match(text, /Prepared by: _+ +Approved by: _+ +Date: _+/)
})

test('an untitled estimate is titled in words, not left blank', () => {
  const model = approval.buildApproval(estimate({ name: '  ' }), {}, TODAY)
  assert.equal(model.title, 'Untitled estimate')
})

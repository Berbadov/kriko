import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

/**
 * The Estimate screen's math and its file export.
 *
 * `forecast.ts` and `sheet.ts` are pure, so they are transpiled and imported
 * here directly: the NPV a capital manager signs has to be a number this test
 * can recompute, and the `.xlsx` has to be a real zip — the test unpacks it
 * with its own reader and checks every entry's CRC — because Excel will not
 * open a file whose checksums lie.
 */

let directory, forecast, sheet, money, quotes, exportsOf
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-estimate-'))
  // Each pure module is transpiled into the scratch directory; its relative
  // imports are rewritten to the scratch names so Node can load them as ESM.
  const modules = [
    ['src/engine/forecast.ts', 'forecast.mjs'],
    ['src/engine/sheet.ts', 'sheet.mjs'],
    ['src/engine/money.ts', 'money.mjs'],
    ['src/engine/quotes.ts', 'quotes.mjs'],
    ['src/engine/estimateExport.ts', 'estimateExport.mjs'],
  ]
  for (const [source, name] of modules) {
    const code = await readFile(source, 'utf8')
    const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
      .replace(/from '\.\/([a-z]+)'/g, "from './$1.mjs'")
    await writeFile(join(directory, name), built)
  }
  forecast = await import(pathToFileURL(join(directory, 'forecast.mjs')))
  sheet = await import(pathToFileURL(join(directory, 'sheet.mjs')))
  money = await import(pathToFileURL(join(directory, 'money.mjs')))
  quotes = await import(pathToFileURL(join(directory, 'quotes.mjs')))
  exportsOf = await import(pathToFileURL(join(directory, 'estimateExport.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')

/** The desk's screen code, wherever a part of it lives. */
const deskSource = async () => {
  const parts = ['src/screens/Estimate.tsx', 'src/ui/QuoteRows.tsx']
  for (const file of ['AddProduct', 'EstimateEditor', 'EstimateList', 'ForecastCard', 'LineCard', 'Overview']) {
    parts.push(`src/screens/procurement/${file}.tsx`)
  }
  return (await Promise.all(parts.map(read))).join('\n')
}

// ── the forecast math ──

test('a line without a price is counted, never read as zero', () => {
  const { priced, unpriced } = forecast.subtotal([
    { quantity: 2, unit_price: 100 },
    { quantity: 3, unit_price: null },
  ])
  assert.equal(priced, 200)
  assert.equal(unpriced, 1)
})

test('year 0 carries the capital, later years carry upkeep, NPV discounts', () => {
  const result = forecast.forecast(
    [{ quantity: 4, unit_price: 250 }],
    { years: 4, maintenance_pct: 10, discount_pct: 0 },
  )
  assert.equal(result.capital, 1000)
  assert.equal(result.rows.length, 5) // year 0 plus one row per year
  assert.deepEqual(result.rows[0], { year: 0, capital: 1000, maintenance: 0, depreciation: 0, cash: 1000, discounted: 1000, cumulative: 1000 })
  // upkeep is 10% of capital each year; with a 0% discount NPV equals cash
  assert.equal(result.maintenance, 400)
  assert.equal(result.cash, 1400)
  assert.equal(result.npv, 1400)
  // straight-line depreciation over 4 years sums back to the capital
  assert.ok(Math.abs(result.depreciation - 1000) < 1e-9)
  assert.ok(Math.abs(result.rows[4].cumulative - 1400) < 1e-9)
})

test('a positive discount rate makes NPV lower than the undiscounted cash', () => {
  const lines = [{ quantity: 1, unit_price: 1000 }]
  const flat = forecast.forecast(lines, { years: 5, maintenance_pct: 20, discount_pct: 0 })
  const discounted = forecast.forecast(lines, { years: 5, maintenance_pct: 20, discount_pct: 10 })
  assert.ok(discounted.npv < flat.npv)
  assert.ok(discounted.npv > 1000, 'the purchase year is not discounted')
  // year 1's discounted upkeep is 200 / 1.1
  assert.ok(Math.abs(discounted.rows[1].discounted - 200 / 1.1) < 1e-9)
})

test('the horizon is clamped to 1..30 years', () => {
  assert.equal(forecast.forecast([], { years: 999, maintenance_pct: 0, discount_pct: 0 }).rows.length, 31)
  assert.equal(forecast.forecast([], { years: 0, maintenance_pct: 0, discount_pct: 0 }).rows.length, 2)
})

// ── CSV ──

test('csv quotes commas, quotes and newlines, and ends every row with CRLF', () => {
  const text = sheet.csvOf([
    ['Equipment', 'Note'],
    ['Drill, "heavy"', 'line\nbreak'],
    ['Plain', null],
  ])
  assert.equal(text, 'Equipment,Note\r\n"Drill, ""heavy""","line\nbreak"\r\nPlain,\r\n')
})

// ── the xlsx writer ──

test('crc32 matches the published check value', () => {
  assert.equal(sheet.crc32(new TextEncoder().encode('123456789')), 0xcbf43926)
})

/** Read a stored (method 0) zip back: EOCD, central directory, entries. */
function unzip(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  assert.equal(bytes[0], 0x50, 'not a zip: no PK signature')
  assert.equal(bytes[1], 0x4b)
  let eocd = -1
  for (let i = bytes.length - 22; i >= 0; i -= 1) {
    if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break }
  }
  assert.ok(eocd >= 0, 'no end of central directory record')
  const count = view.getUint16(eocd + 10, true)
  let at = view.getUint32(eocd + 16, true)
  const entries = {}
  for (let n = 0; n < count; n += 1) {
    assert.equal(view.getUint32(at, true), 0x02014b50, 'bad central header')
    const method = view.getUint16(at + 10, true)
    const crc = view.getUint32(at + 16, true)
    const size = view.getUint32(at + 20, true)
    const nameLength = view.getUint16(at + 28, true)
    const extraLength = view.getUint16(at + 30, true)
    const commentLength = view.getUint16(at + 32, true)
    const localAt = view.getUint32(at + 42, true)
    const name = new TextDecoder().decode(bytes.subarray(at + 46, at + 46 + nameLength))
    assert.equal(method, 0, 'entries must be stored, not compressed')
    assert.equal(view.getUint32(localAt, true), 0x04034b50, 'bad local header')
    const localName = view.getUint16(localAt + 26, true)
    const localExtra = view.getUint16(localAt + 28, true)
    const dataAt = localAt + 30 + localName + localExtra
    const data = bytes.subarray(dataAt, dataAt + size)
    entries[name] = { crc, data }
    at += 46 + nameLength + extraLength + commentLength
  }
  return entries
}

test('the workbook is a valid zip whose every entry checksum matches', () => {
  const bytes = sheet.xlsxOf([
    { name: 'Estimate', rows: [['Equipment', 'Qty'], ['Drill "Pro", 2"', 2], ['Saw', null]] },
    { name: 'Forecast', rows: [[0, 1000], [1, 100]] },
  ])
  const entries = unzip(bytes)
  for (const [name, entry] of Object.entries(entries)) {
    assert.equal(sheet.crc32(entry.data), entry.crc, `crc mismatch for ${name}`)
  }
  for (const required of ['[Content_Types].xml', '_rels/.rels', 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels', 'xl/styles.xml', 'xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml']) {
    assert.ok(entries[required], `missing part ${required}`)
  }
  const xml = new TextDecoder().decode(entries['xl/worksheets/sheet1.xml'].data)
  assert.ok(xml.includes('xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'))
  assert.ok(xml.includes('Drill &quot;Pro&quot;, 2&quot;'), 'string cells are xml-escaped and inline')
  assert.ok(xml.includes('<v>2</v>'), 'numbers are numeric cells')
  const workbook = new TextDecoder().decode(entries['xl/workbook.xml'].data)
  assert.ok(workbook.includes('name="Estimate"') && workbook.includes('name="Forecast"'))
})

test('sheet names are sanitised and de-duplicated', () => {
  const bytes = sheet.xlsxOf([
    { name: 'a/b:c', rows: [] },
    { name: 'a/b:c', rows: [] },
    { name: 'x'.repeat(60), rows: [] },
  ])
  const workbook = new TextDecoder().decode(unzip(bytes)['xl/workbook.xml'].data)
  assert.ok(workbook.includes('name="a b c"'))
  assert.ok(workbook.includes('name="a b c (2)"'))
  assert.ok(!workbook.includes('x'.repeat(32)), 'names are capped at 31 chars')
})

// ── the screen names its doors and both export formats ──

test('the Estimate screen reads the catalogs, researches, saves and exports both formats', async () => {
  const screen = await deskSource()
  for (const needle of [
    '/api/search?q=',
    '/api/subjects?limit=',
    '/api/subjects/${seg(',
    "('/api/research'",
    "'/api/costs'",
    'csvOf(',
    'xlsxOf(',
    '.csv`',
    '.xlsx`',
  ]) {
    assert.ok(screen.includes(needle), `Estimate.tsx does not carry ${needle}`)
  }
  const api = await read('src/engine/estimates.ts')
  for (const needle of ["'/api/estimates?limit=100'", '/api/estimates/${seg(']) {
    assert.ok(api.includes(needle), `estimates.ts does not carry ${needle}`)
  }
  const rail = await read('src/ui/Rail.tsx')
  assert.ok(rail.includes("'estimate'"), 'the rail does not offer the Estimate screen')
  const app = await read('src/App.tsx')
  assert.ok(app.includes("screen === 'estimate' && <EstimateScreen />"), 'App does not render the Estimate screen')
})


// ── VAT, currencies and depreciation ──

test('a net price and a gross price of the same rate read to the same gross', () => {
  const net = forecast.lineVat({ quantity: 1, unit_price: 100, vat_rate: 20, vat_included: false })
  const gross = forecast.lineVat({ quantity: 1, unit_price: 120, vat_rate: 20, vat_included: true })
  assert.ok(Math.abs(net.net - 100) < 1e-9)
  assert.ok(Math.abs(net.vat - 20) < 1e-9)
  assert.ok(Math.abs(net.gross - 120) < 1e-9)
  assert.ok(Math.abs(gross.net - 100) < 1e-9)
  assert.ok(Math.abs(gross.vat - 20) < 1e-9)
  assert.ok(Math.abs(gross.gross - 120) < 1e-9)
})

test('a line with no VAT stated is not charged a rate by the forecast', () => {
  const total = forecast.vatTotals([{ quantity: 2, unit_price: 50 }])
  assert.deepEqual(total, { net: 100, vat: 0, gross: 100 })
})

test('an unpriced line contributes no VAT and is still counted', () => {
  const result = forecast.forecast(
    [{ quantity: 1, unit_price: 100, vat_rate: 20 }, { quantity: 2, unit_price: null }],
    { years: 2, maintenance_pct: 0, discount_pct: 0 })
  assert.equal(result.capital, 120)
  assert.equal(result.unpriced, 1)
  assert.ok(Math.abs(result.vat.vat - 20) < 1e-9)
})

test('VAT totals add the net and the tax of every line', () => {
  const total = forecast.vatTotals([
    { quantity: 1, unit_price: 100, vat_rate: 20 },
    { quantity: 1, unit_price: 240, vat_rate: 20, vat_included: true },
  ])
  assert.ok(Math.abs(total.net - 300) < 1e-9)
  assert.ok(Math.abs(total.vat - 60) < 1e-9)
  assert.ok(Math.abs(total.gross - 360) < 1e-9)
})

test('straight line spreads cost less salvage over the life and stops there', () => {
  const asset = forecast.depreciationOf(
    { quantity: 1, unit_price: 1000, depreciation: 'straight_line', life_years: 4, salvage: 200 }, 6)
  assert.deepEqual(asset.yearly, [200, 200, 200, 200, 0, 0])
  assert.equal(asset.total, 800)
})

test('the last straight-line year absorbs the rounding, so the column sums to the depreciable', () => {
  const asset = forecast.depreciationOf(
    { quantity: 1, unit_price: 100, depreciation: 'straight_line', life_years: 3 }, 3)
  assert.ok(Math.abs(asset.total - 100) < 1e-9)
})

test('declining balance charges twice the straight-line rate and never falls through salvage', () => {
  const asset = forecast.depreciationOf(
    { quantity: 1, unit_price: 1000, depreciation: 'declining_balance', life_years: 4, salvage: 100 }, 6)
  assert.ok(Math.abs(asset.yearly[0] - 500) < 1e-9)
  assert.ok(Math.abs(asset.yearly[1] - 250) < 1e-9)
  assert.ok(asset.total <= 900 + 1e-9)
  const book = 1000 - asset.total
  assert.ok(book >= 100 - 1e-9, 'book value fell below salvage')
})

test('the VUK method uses the rate the reader entered, not a shipped table', () => {
  const asset = forecast.depreciationOf(
    { quantity: 1, unit_price: 1000, depreciation: 'vuk', vuk_rate: 20, life_years: 5 }, 3)
  assert.ok(Math.abs(asset.yearly[0] - 200) < 1e-9)
  assert.ok(Math.abs(asset.yearly[1] - 160) < 1e-9)
})

test('a horizon shorter than the life shows the years it has, and no more', () => {
  const asset = forecast.depreciationOf(
    { quantity: 1, unit_price: 1000, depreciation: 'straight_line', life_years: 10 }, 3)
  assert.equal(asset.yearly.length, 3)
  assert.equal(asset.yearly[2], 100)
})

test('rates are TRY per one unit, and a missing rate is null rather than one', () => {
  const rates = { TRY: 1, EUR: 50, USD: 40 }
  assert.equal(money.convert(100, 'EUR', 'TRY', rates), 5000)
  assert.equal(money.convert(5000, 'TRY', 'EUR', rates), 100)
  assert.equal(money.convert(100, 'GBP', 'TRY', rates), null)
})

test('a quote reads net, VAT and gross and lands in the estimate currency', () => {
  const read = money.quoteMoney(
    { unit_price: 100, currency: 'EUR', vat_rate: 20, vat_included: false },
    'TRY', { TRY: 1, EUR: 50 })
  assert.equal(read.net, 100)
  assert.equal(read.vat, 20)
  assert.equal(read.gross, 120)
  assert.equal(read.landed, 6000)
})

test('the desk fetches the Central Bank rates on the reader\'s press and never sends a quote without its fields', async () => {
  const screen = await deskSource()
  assert.ok(screen.includes('fetchTcmbRates'), 'the desk does not fetch the rates')
  const api = await read('src/engine/estimates.ts')
  assert.ok(api.includes('quotes: (line.quotes ?? [])'), 'a quote is never sent on save')
})

test('the accounting sheet header is the contract, in order, and the workbook carries it', () => {
  const [header] = exportsOf.accountingSheet({ ...estimateInput(), lines: [] }).rows
  assert.deepEqual(header, [
    'Item', 'Catalog', 'Asset category', 'Acquisition year', 'Useful life (years)',
    'Depreciation method', 'Cost (net)', 'VAT', 'Cost (gross)', 'Salvage',
    'Currency', 'Vendor', 'Seller', 'Quote date', 'Document',
  ])
  assert.deepEqual(exportsOf.ACCOUNTING_COLUMNS, header)
  assert.deepEqual(exportsOf.workbookSheets(estimateInput()).map((item) => item.name), ['Estimate', 'Forecast', 'Accounting', 'Research', 'Costs'])
})

// ── a quote in the estimate's own currency needs no rate ──

test('a quote in the estimate currency lands at its own gross with no rate stored for that currency', () => {
  // The screen shows the estimate currency's rate as 1 but never stores it, so the
  // table holds no entry for it. The amount is already in the target currency.
  const read = money.quoteMoney(
    { unit_price: 100, currency: 'EUR', vat_rate: 20, vat_included: false },
    'EUR', { TRY: 1, USD: 40 })
  assert.equal(read.gross, 120)
  assert.equal(read.landed, 120, 'an own-currency quote is not dropped as unpriced')
})

test('an own-currency amount converts at 1 by definition, with or without a rate table', () => {
  assert.equal(money.convert(250, 'USD', 'USD', {}), 250)
  assert.equal(money.convert(250, 'USD', 'usd', { TRY: 1 }), 250)
})

test('a different currency with no rate stays null even when the estimate currency has none either', () => {
  assert.equal(money.convert(10, 'EUR', 'USD', { TRY: 1 }), null)
  const read = money.quoteMoney({ unit_price: 10, currency: 'EUR', vat_rate: 0 }, 'USD', { TRY: 1 })
  assert.equal(read.landed, null, 'a missing rate is uncomparable, never converted at 1')
})

test('the forecast keeps an own-currency line priced when the estimate has no stored rate', () => {
  const lines = [{ quantity: 2, unit_price: money.quoteMoney({ unit_price: 50, currency: 'EUR', vat_rate: 0 }, 'EUR', {}).landed }]
  const result = forecast.forecast(lines, { years: 1, maintenance_pct: 0, discount_pct: 0 })
  assert.equal(result.unpriced, 0)
  assert.equal(result.capital, 100)
})

// ── the quote comparison: ranking, verdict, rate gaps and expiry ──

const TODAY = new Date(2026, 10, 20)
const isoAfter = (days) => {
  const date = new Date(2026, 10, 20 + days)
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
const offer = (over = {}) => ({
  vendor: 'Vendor', seller: '', url: '', unit_price: 100, currency: 'TRY', vat_rate: 0, vat_included: false,
  delivery_days: null, warranty_months: null, quote_date: '', valid_until: '', note: '', selected: false,
  ...over,
})
const lineWith = (quotes, over = {}) => ({
  subject_id: 'pump', pack_id: 'pumps', label: 'Pump', quantity: 1, unit_price: null, note: '',
  depreciation: 'straight_line', life_years: null, salvage: null, vuk_rate: null, quotes, ...over,
})
const estimateInput = (over = {}) => ({
  name: 'Shop', currency: 'TRY', vatRate: 20, years: 5, maintenancePct: 5, discountPct: 8,
  fx: { TRY: 1, USD: 40, EUR: 50 }, lines: [], model: forecast.forecast([], { years: 5, maintenance_pct: 5, discount_pct: 8 }),
  usage: null, problems: {}, costs: null, ...over,
})
const RATES = { TRY: 1, USD: 40, EUR: 50 }

test('the cheapest landed quote ranks first, and the verdict names the saving over the next', () => {
  const line = lineWith([
    offer({ vendor: 'Dear', unit_price: 1200 }),
    offer({ vendor: 'Cheap', unit_price: 1000, selected: true }),
    offer({ vendor: 'Middle', unit_price: 10, currency: 'USD', vat_rate: 20, vat_included: true }),
  ])
  const views = quotes.quoteViews(line, 'TRY', RATES, TODAY)
  const rank = Object.fromEntries(views.map((view) => [view.quote.vendor, view.rank]))
  // Middle: 10 USD gross at 40 TRY is 400 TRY, the cheapest of the three.
  assert.deepEqual(rank, { Dear: 3, Cheap: 2, Middle: 1 })
  const verdict = quotes.verdictOf(views)
  assert.equal(verdict.best.quote.vendor, 'Middle')
  assert.equal(verdict.saving, 600)
  assert.equal(quotes.verdictText(verdict, 'TRY'), 'Best landed cost: Middle, saves 600 TRY against the next quote')
})

test('a quote with no rate is listed as No rate, is unranked, and is left out of the verdict', () => {
  const line = lineWith([
    offer({ vendor: 'Known', unit_price: 900 }),
    offer({ vendor: 'Euro', unit_price: 5, currency: 'GBP' }),
  ])
  const views = quotes.quoteViews(line, 'TRY', RATES, TODAY)
  const euro = views.find((view) => view.quote.vendor === 'Euro')
  assert.equal(euro.noRate, true)
  assert.equal(euro.landed, null)
  assert.equal(euro.rank, null)
  const verdict = quotes.verdictOf(views)
  assert.equal(verdict.comparable, 1)
  assert.equal(verdict.withoutRate, 1)
  assert.equal(quotes.verdictText(verdict, 'TRY'), 'Best landed cost: Known, 900 TRY. No second comparable quote')
})

test('an expired best quote is still named, and the verdict says its validity has lapsed', () => {
  const line = lineWith([
    offer({ vendor: 'Gone', unit_price: 100, valid_until: isoAfter(-2) }),
    offer({ vendor: 'Open', unit_price: 150, valid_until: isoAfter(9) }),
  ])
  const verdict = quotes.verdictOf(quotes.quoteViews(line, 'TRY', RATES, TODAY))
  assert.equal(quotes.verdictText(verdict, 'TRY'), 'Best landed cost: Gone, saves 50 TRY against the next quote. Its validity has expired')
})

test('with no comparable quote the verdict says so, and counts the ones without a rate', () => {
  const line = lineWith([offer({ unit_price: 5, currency: 'GBP' })])
  const verdict = quotes.verdictOf(quotes.quoteViews(line, 'TRY', RATES, TODAY))
  assert.equal(quotes.verdictText(verdict, 'TRY'), 'No comparable quotes, 1 without a rate')
  const bare = quotes.verdictOf(quotes.quoteViews(lineWith([]), 'TRY', RATES, TODAY))
  assert.equal(quotes.verdictText(bare, 'TRY'), 'No comparable quotes')
})

test('an unpriced quote is counted as unpriced, never as free', () => {
  const [view] = quotes.quoteViews(lineWith([offer({ unit_price: null })]), 'TRY', RATES, TODAY)
  assert.equal(view.unpriced, true)
  assert.equal(view.landed, null)
  assert.equal(view.noRate, false)
  assert.equal(view.rank, null)
})

test('the engine ranking decides the order when it ranks every comparable quote', () => {
  const line = lineWith([
    offer({ vendor: 'A', unit_price: 100, quote_id: 'a' }),
    offer({ vendor: 'B', unit_price: 200, quote_id: 'b' }),
  ], { ranking: [
    { quote_id: 'b', rank: 1, landed: 200, reasons: [] },
    { quote_id: 'a', rank: 2, landed: 100, reasons: [] },
  ] })
  const ranked = quotes.quoteViews(line, 'TRY', RATES, TODAY).sort((x, y) => x.rank - y.rank)
  assert.deepEqual(ranked.map((view) => view.quote.vendor), ['B', 'A'])
})

test('a tie in landed cost breaks on the shorter delivery', () => {
  const line = lineWith([
    offer({ vendor: 'Slow', unit_price: 100, delivery_days: 30 }),
    offer({ vendor: 'Fast', unit_price: 100, delivery_days: 3 }),
  ])
  const ranked = quotes.quoteViews(line, 'TRY', RATES, TODAY).sort((x, y) => x.rank - y.rank)
  assert.equal(ranked[0].quote.vendor, 'Fast')
})

test('validity reads as words: expires in N days, today, expired, or no date', () => {
  const dated = (days) => quotes.quoteViews(lineWith([offer({ valid_until: isoAfter(days) })]), 'TRY', RATES, TODAY)[0]
  assert.equal(quotes.expiryWord(dated(0).expiresInDays), 'Expires today')
  assert.equal(quotes.expiryWord(dated(1).expiresInDays), 'Expires in 1 day')
  assert.equal(quotes.expiryWord(dated(9).expiresInDays), 'Expires in 9 days')
  assert.equal(quotes.expiryWord(dated(-3).expiresInDays), 'Expired')
  assert.equal(quotes.expiryWord(quotes.quoteViews(lineWith([offer()]), 'TRY', RATES, TODAY)[0].expiresInDays), 'No date')
})

test('a line costs its selected quote gross in the estimate currency, with that quote\'s VAT', () => {
  const line = lineWith([
    offer({ unit_price: 100, currency: 'USD', vat_rate: 20, vat_included: false, selected: false }),
    offer({ unit_price: 120, currency: 'EUR', vat_rate: 20, vat_included: true, selected: true }),
  ])
  // Selected: 120 EUR gross at 50 TRY per EUR is 6000 TRY.
  assert.equal(quotes.lineUnitGross(line, 'TRY', RATES), 6000)
  assert.equal(quotes.chosenQuote(line).currency, 'EUR')
  assert.equal(quotes.lineUnitGross(lineWith([]), 'TRY', RATES), null)
  assert.equal(quotes.lineUnitGross(lineWith([], { unit_price: 75 }), 'TRY', RATES), 75)
  const unrated = lineWith([offer({ unit_price: 10, currency: 'GBP', selected: true })])
  assert.equal(quotes.lineUnitGross(unrated, 'TRY', RATES), null, 'no rate, so no number')
})

// ── the accounting sheet keeps each amount in the estimate currency ──

test('an accounting cell is converted at the stated rate, and blank where the quote has no rate', () => {
  const sheet = exportsOf.accountingSheet(estimateInput({
    currency: 'TRY',
    lines: [
      lineWith([offer({ unit_price: 100, currency: 'USD', vat_rate: 20, vat_included: false, selected: true, vendor: 'Us' })], { quantity: 2 }),
      lineWith([offer({ unit_price: 10, currency: 'GBP', vat_rate: 20, vat_included: false, selected: true, vendor: 'Uk' })], { subject_id: 'valve', label: 'Valve' }),
    ],
  }))
  const [, us, uk] = sheet.rows
  // 100 USD net at 40 TRY: 4000 TRY per unit, two units.
  assert.equal(us[6], 8000, 'net is converted, not written as USD')
  assert.equal(us[7], 1600, 'VAT is converted at the same rate')
  assert.equal(us[8], 9600, 'gross is converted and multiplied by quantity')
  assert.equal(us[10], 'TRY')
  assert.deepEqual([uk[6], uk[7], uk[8]], ['', '', ''], 'a quote with no rate leaves its money blank')
})

test('the research sheet lists known problems in severity order and counts a product with none', () => {
  const sheet = exportsOf.researchSheet(estimateInput({
    lines: [lineWith([], { subject_id: 'pump' }), lineWith([], { subject_id: 'valve', label: 'Valve' })],
    problems: {
      pump: [{ severity: 'low', domain: 'Noise', title: 'Hums' }, { severity: 'critical', domain: 'Safety', title: 'Overheats' }],
      valve: [],
    },
  }))
  assert.deepEqual(sheet.rows[1], ['Pump', 'pumps', 'critical', 'Safety', 'Overheats'])
  assert.deepEqual(sheet.rows[2], ['Pump', 'pumps', 'low', 'Noise', 'Hums'])
  assert.equal(sheet.rows[3][4], 'No known issues in the catalog yet. Research it.')
})

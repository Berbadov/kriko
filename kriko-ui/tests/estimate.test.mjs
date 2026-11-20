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

let directory, forecast, sheet, money
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-estimate-'))
  for (const [source, name] of [['src/engine/forecast.ts', 'forecast.mjs'], ['src/engine/sheet.ts', 'sheet.mjs'], ['src/engine/money.ts', 'money.mjs']]) {
    const code = await readFile(source, 'utf8')
    const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
    await writeFile(join(directory, name), built)
  }
  forecast = await import(pathToFileURL(join(directory, 'forecast.mjs')))
  sheet = await import(pathToFileURL(join(directory, 'sheet.mjs')))
  money = await import(pathToFileURL(join(directory, 'money.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')

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
  const screen = await read('src/screens/Estimate.tsx')
  for (const needle of [
    '/api/subjects/search?q=',
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
  const topbar = await read('src/ui/TopBar.tsx')
  assert.ok(topbar.includes("'estimate'"), 'the top bar does not offer the Estimate screen')
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

test('the screen knows the quotes, the rates and the accounting columns', async () => {
  const screen = await read('src/screens/Estimate.tsx')
  for (const needle of ['ACCOUNTING_COLUMNS', 'QuoteRows', 'fetchTcmbRates', 'quoteMoney']) {
    assert.ok(screen.includes(needle), `Estimate.tsx does not carry ${needle}`)
  }
  // The accounting sheet's headers are a contract a bookkeeper maps once.
  const block = screen.slice(screen.indexOf('const ACCOUNTING_COLUMNS'), screen.indexOf(']', screen.indexOf('const ACCOUNTING_COLUMNS')))
  for (const column of ['Item', 'Cost (net)', 'VAT', 'Cost (gross)', 'Salvage', 'Useful life (years)', 'Document']) {
    assert.ok(block.includes(`'${column}'`), `the accounting sheet lost ${column}`)
  }
  const api = await read('src/engine/estimates.ts')
  assert.ok(api.includes('quotes: (line.quotes ?? [])'), 'a quote is never sent on save')
})

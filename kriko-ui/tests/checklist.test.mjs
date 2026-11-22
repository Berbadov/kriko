import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

/**
 * Check a list: the pure part of the screen and of the chat attachment.
 *
 * `checklist.ts`, `attachment.ts` and the spreadsheet reader are transpiled and
 * imported directly; the one request the screen makes goes through a stub of
 * `api.ts`, so the rows sent, the answers joined back, the results file and the
 * lines an estimate would get are all things this test can compute.
 */

let directory, list, reader, writer, attach
let sent = []
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-checklist-'))
  const modules = [
    ['src/engine/sheet.ts', 'sheet.mjs'],
    ['src/engine/spreadsheet.ts', 'spreadsheet.mjs'],
    ['src/engine/checklist.ts', 'checklist.mjs'],
    ['src/engine/attachment.ts', 'attachment.mjs'],
  ]
  for (const [source, name] of modules) {
    const code = await readFile(source, 'utf8')
    const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
      .replace(/from '\.\/(api|sheet|spreadsheet|estimates)'/g, "from './$1.mjs'")
    await writeFile(join(directory, name), built)
  }
  await writeFile(join(directory, 'api.mjs'), `export const post = (path, body) => globalThis.__post(path, body)\n`)
  await writeFile(join(directory, 'estimates.mjs'), 'export {}\n')
  writer = await import(pathToFileURL(join(directory, 'sheet.mjs')))
  reader = await import(pathToFileURL(join(directory, 'spreadsheet.mjs')))
  list = await import(pathToFileURL(join(directory, 'checklist.mjs')))
  attach = await import(pathToFileURL(join(directory, 'attachment.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const counts = (serious = 0, known = 0, minor = 0) => ({ total: serious + known + minor, serious, known, minor })
const match = (label, confidence = 'exact') => ({ subject_id: `s-${label}`, pack_id: 'p', label, confidence })
const tr = reader => reader.parseCsv('Ürün Adı;Adet;Birim Fiyat;Para Birimi;Satıcı\r\nXPS 13;2;32.500,00;TL;Hepsiburada\r\nEnvy;1;;;\r\nXPS 13;3;1.299,00;EUR;\r\nGizli;1;5,50;;\r\n;;;;\r\n', 'liste.csv')

// ── the rows to send ──

test('rows with a name are sent, rows without one are counted, and the cut is counted', () => {
  const table = { name: 't', header: ['Name'], rows: [['  Chair   one '], [''], ['Desk']] }
  const prepared = list.prepareRows(table, 0)
  assert.deepEqual(prepared.rows, [{ row: 0, name: 'Chair one' }, { row: 2, name: 'Desk' }])
  assert.equal(prepared.blank, 1)

  const long = { name: 't', header: ['Name'], rows: Array.from({ length: 305 }, (_, i) => [`Item ${i}`]), truncated: 4 }
  const cut = list.prepareRows(long, 0)
  assert.equal(cut.rows.length, 300)
  assert.equal(cut.cut, 5 + 4)

  assert.equal(list.prepareRows(table, undefined).rows.length, 0)
  const wide = list.prepareRows({ name: 't', header: ['n'], rows: [['x'.repeat(500)]] }, 0)
  assert.equal(wide.rows[0].name.length, 200)
})

test('the engine answer is joined by index, so a missing answer is a row with no match', () => {
  const prepared = { rows: [{ row: 0, name: 'a' }, { row: 3, name: 'b' }], blank: 0, cut: 0 }
  const items = [{ index: 1, query: 'b', match: match('B'), claims: counts(1), leading: { title: 'T', severity: 'high' }, others: [] }]
  const [first, second] = list.resolveRows(prepared, items)
  assert.equal(first.match, null)
  assert.equal(list.levelOf(first), 'nomatch')
  assert.equal(second.row, 3)
  assert.equal(second.match.label, 'B')
})

// ── a row, worded ──

test('a row comes to the worst thing known about it, in the engine\'s words', () => {
  const level = (matched, claims) => list.levelOf({ match: matched ? match('X') : null, claims })
  assert.equal(level(true, counts(1, 2)), 'serious')
  assert.equal(level(true, counts(0, 2, 1)), 'known')
  assert.equal(level(true, counts(0, 0, 1)), 'minor')
  assert.equal(level(true, { total: 2, serious: 0, known: 0, minor: 0 }), 'check')
  assert.equal(level(true, counts()), 'none')
  assert.equal(level(false, counts()), 'nomatch')
  assert.equal(list.LEVEL_WORD.serious, 'Serious')
  assert.equal(list.LEVEL_WORD.none, 'No reports')
})

test('choosing one of the offered products matches the row with that product\'s own counts', () => {
  const row = {
    row: 4, name: 'Galaxy A15', match: null, claims: counts(), leading: null,
    others: [
      { subject_id: 'a', pack_id: 'p', label: 'A15 4G', claims: counts(0, 1), leading: { title: 'x', severity: 'medium' } },
      { subject_id: 'b', pack_id: 'p', label: 'A15 5G', claims: counts(2), leading: { title: 'y', severity: 'high' } },
    ],
  }
  const chosen = list.chooseCandidate(row, 'b')
  assert.equal(chosen.match.label, 'A15 5G')
  assert.equal(chosen.match.confidence, 'chosen')
  assert.equal(list.levelOf(chosen), 'serious')
  assert.equal(list.chooseCandidate(row, 'nope'), row)
})

test('the summary, the filter and the severity order', () => {
  const row = (n, matched, claims) => ({ row: n, name: `n${n}`, match: matched ? match(`P${n}`) : null, claims, leading: null, others: [] })
  const items = [row(0, true, counts(0, 1)), row(1, false, counts()), row(2, true, counts(2)), row(3, true, counts()), row(4, true, counts(1))]
  const summary = list.summarize(items)
  assert.deepEqual([summary.rows, summary.matched, summary.serious, summary.known, summary.nomatch], [5, 4, 2, 1, 1])
  assert.deepEqual(list.visibleRows(items, 'serious', 'file').map((r) => r.row), [2, 4])
  assert.deepEqual(list.visibleRows(items, 'all', 'worst').map((r) => r.row), [2, 4, 0, 3, 1])
  assert.deepEqual(list.visibleRows(items, 'all', 'best').map((r) => r.row), [1, 3, 0, 4, 2])
  assert.deepEqual(list.visibleRows(items, 'all', 'file').map((r) => r.row), [0, 1, 2, 3, 4])
})

// ── the results file ──

test('the results file keeps the original columns and adds the answer to their right', () => {
  const table = tr(reader)
  const items = [
    { row: 0, name: 'XPS 13', match: match('XPS 13'), claims: counts(2, 1, 1), leading: { title: 'Blue screens', severity: 'high' }, others: [] },
    { row: 1, name: 'Envy', match: null, claims: counts(), leading: null, others: [{ subject_id: 'e1', pack_id: 'p', label: 'Envy 13' }, { subject_id: 'e2', pack_id: 'p', label: 'Envy 15' }] },
    { row: 3, name: 'Gizli', match: null, claims: counts(), leading: null, others: [] },
  ]
  const rows = list.resultRows(table, items, { nameColumn: 0 })
  assert.deepEqual(rows[0], [...table.header, ...list.RESULT_COLUMNS])
  assert.deepEqual(rows[1].slice(0, 5), table.rows[0])
  assert.deepEqual(rows[1].slice(5), ['XPS 13', 'Exact', 2, 1, 1, 'Blue screens'])
  assert.equal(rows[2][6], 'Several fit: Envy 13; Envy 15')
  assert.equal(rows[4][6], 'No match')
  assert.equal(rows.length, table.rows.length + 1)
  // The xlsx the app writes can be read back by the app's own reader.
  assert.ok(writer.xlsxOf([{ name: 'Checked list', rows }]).length > 100)
})

test('numbers an xlsx stored as numbers go back as numbers', () => {
  const table = { name: 't', header: ['Name', 'Price'], rows: [['A', '1.234'], ['B', '1.234']], numeric: [[false, true], [false, false]] }
  const rows = list.resultRows(table, [], { nameColumn: 0 })
  assert.equal(rows[1][1], 1.234)
  assert.equal(rows[2][1], '1.234')
})

test('a row that was cut says so, and a row with no name says that', () => {
  const table = { name: 't', header: ['Name'], rows: [['Chair'], ['']] }
  const rows = list.resultRows(table, [], { nameColumn: 0 })
  assert.match(rows[1][2], /Not checked/)
  assert.equal(rows[2][2], 'No name')
})

test('a CSV never carries a formula: text that a spreadsheet would run is written as text', () => {
  assert.equal(list.safeCsvCell('=SUM(A1:A9)'), "'=SUM(A1:A9)")
  assert.equal(list.safeCsvCell('@cmd'), "'@cmd")
  assert.equal(list.safeCsvCell('-2+3'), "'-2+3")
  assert.equal(list.safeCsvCell('-5,50'), '-5,50')
  assert.equal(list.safeCsvCell('Chair'), 'Chair')
  assert.equal(list.safeCsvCell(7), 7)
  const rows = list.resultRows({ name: 't', header: ['Name'], rows: [['=1+1']] }, [], { csv: true, nameColumn: 0 })
  assert.equal(rows[1][0], "'=1+1")
})

// ── to an estimate ──

const resolvedAll = (table) => table.rows.map((cells, row) => ({
  row, name: cells[0], match: cells[0] === 'Gizli' || !cells[0] ? null : match(cells[0] === 'Envy' ? 'Envy 13' : cells[0]),
  claims: counts(), leading: null, others: [],
})).filter((r) => r.name)

test('a Turkish list (semicolons, decimal commas) becomes rows with quantities and prices as written', () => {
  const table = tr(reader)
  const mapping = { name: 0, quantity: 1, price: 2, currency: 3, vendor: 4 }
  const rows = list.addRowsOf(table, mapping, resolvedAll(table), 'liste.csv')
  assert.equal(rows.length, 3)
  assert.deepEqual(rows[0].quote, { vendor: 'Hepsiburada', unit_price: 32500, currency: 'TRY', note: 'liste.csv, item 1' })
  assert.equal(rows[0].quantity, 2)
  assert.equal(rows[1].quote, null)
  assert.equal(rows[2].quote.currency, 'EUR')
  assert.equal(rows[2].quote.vendor, 'From a list')
  assert.equal(rows[2].quote.unit_price, 1299)
  assert.equal(list.dominantCurrency(rows), 'TRY')
  assert.equal(list.dominantCurrency([{ quote: null }, { quote: { currency: '' } }]), '')
})

test('a currency is a symbol, a name the reader knows, or a three-letter code; the price\'s own wins', () => {
  assert.equal(list.currencyCode('TL'), 'TRY')
  assert.equal(list.currencyCode('₺'), 'TRY')
  assert.equal(list.currencyCode('eur'), 'EUR')
  assert.equal(list.currencyCode('chf'), 'CHF')
  assert.equal(list.currencyCode('lots'), '')
  const table = { name: 't', header: ['n', 'p', 'c'], rows: [['A', '$10', 'EUR'], ['B', '10', 'EUR'], ['C', '10', '']] }
  const resolved = table.rows.map((c, row) => ({ row, name: c[0], match: match(c[0]), claims: counts(), leading: null, others: [] }))
  const rows = list.addRowsOf(table, { name: 0, price: 1, currency: 2 }, resolved)
  assert.deepEqual(rows.map((r) => r.quote.currency), ['USD', 'EUR', ''])
})

test('a quantity that is not a positive number is 1, and a price is never invented', () => {
  const table = { name: 't', header: ['n', 'q', 'p'], rows: [['A', 'many', 'ask'], ['B', '0', '-3'], ['C', '4,0', '12']] }
  const resolved = table.rows.map((c, row) => ({ row, name: c[0], match: match(c[0]), claims: counts(), leading: null, others: [] }))
  const rows = list.addRowsOf(table, { name: 0, quantity: 1, price: 2 }, resolved)
  assert.deepEqual(rows.map((r) => r.quantity), [1, 1, 4])
  assert.deepEqual(rows.map((r) => r.quote === null), [true, true, false])
})

const row = (id, quantity, quote) => ({ row: 0, subject: { subject_id: id, pack_id: 'p', label: id }, quantity, quote })
const quote = (price, currency = 'TRY', vendor = 'V') => ({ vendor, unit_price: price, currency, note: 'n' })

test('two rows of one product make one line: quantities add, both quotes stay, one is selected', () => {
  const built = list.buildEstimateLines([row('a', 2, quote(10)), row('b', 1, null), row('a', 3, quote(12, 'EUR'))], [], 'USD')
  assert.equal(built.lines.length, 2)
  const a = built.lines[0]
  assert.equal(a.quantity, 5)
  assert.deepEqual(a.quotes.map((q) => [q.unit_price, q.currency, q.selected]), [[10, 'TRY', true], [12, 'EUR', false]])
  assert.deepEqual(a.quotes.map((q) => [q.vat_rate, q.vat_included]), [[20, true], [20, true]])
  assert.deepEqual(built.lines[1].quotes, [])
  assert.equal(built.lines[1].unit_price, null)
  assert.deepEqual([built.created, built.joined, built.quotes, built.unpriced], [2, 0, 2, 1])
})

test('a price with no currency takes the estimate\'s and is counted', () => {
  const built = list.buildEstimateLines([row('a', 1, quote(10, ''))], [], 'gbp')
  assert.equal(built.lines[0].quotes[0].currency, 'GBP')
  assert.equal(built.defaulted, 1)
})

test('a product already on the estimate keeps its quantity and gains the quotes', () => {
  const existing = [{
    subject_id: 'a', pack_id: 'p', label: 'a', quantity: 7, unit_price: null, note: '', depreciation: 'straight_line',
    life_years: null, salvage: null, vuk_rate: null,
    quotes: [{ ...list.buildEstimateLines([row('z', 1, quote(1))], [], 'TRY').lines[0].quotes[0], selected: false }],
  }]
  const built = list.buildEstimateLines([row('a', 2, quote(10))], existing, 'TRY')
  assert.equal(built.lines.length, 1)
  assert.equal(built.lines[0].quantity, 7)
  assert.equal(built.lines[0].quotes.length, 2)
  assert.equal(built.lines[0].quotes.filter((q) => q.selected).length, 1)
  assert.deepEqual([built.created, built.joined], [0, 1])
  assert.equal(existing[0].quotes.length, 1, 'the estimate that was read is not changed')
})

test('the limits of a line and of an estimate drop what does not fit, and say so', () => {
  const many = Array.from({ length: 22 }, (_, i) => row('a', 1, quote(i + 1)))
  const built = list.buildEstimateLines(many, [], 'TRY')
  assert.equal(built.lines[0].quotes.length, 20)
  assert.equal(built.droppedQuotes, 2)
  const lines = Array.from({ length: 203 }, (_, i) => row(`s${i}`, 1, null))
  const wide = list.buildEstimateLines(lines, [], 'TRY')
  assert.equal(wide.lines.length, 200)
  assert.equal(wide.droppedLines, 3)
})

// ── the request ──

test('every name goes in one request, and cancelling stops the wait', async () => {
  sent = []
  globalThis.__post = (path, body) => { sent.push([path, body]); return new Promise(() => {}) }
  const controller = new AbortController()
  const pending = list.checkNames(['a', 'b'], controller.signal)
  controller.abort()
  await assert.rejects(pending, (error) => error.name === 'AbortError')
  assert.equal(sent.length, 1)
  assert.deepEqual(sent[0], ['/api/check-list', { names: ['a', 'b'] }])
  await assert.rejects(list.checkNames(['a'], controller.signal), (error) => error.name === 'AbortError')

  globalThis.__post = async () => ({ items: [{ index: 0, query: 'a', match: null, claims: counts(), leading: null, others: [] }] })
  assert.equal((await list.checkNames(['a'])).length, 1)
})

// ── the chat attachment ──

const workbook = (n, extraSheets = 0) => {
  const rows = [['Item', 'Qty'], ...Array.from({ length: n }, (_, i) => [`Thing ${i}`, i + 1])]
  const sheets = [{ name: 'Orders', rows }]
  for (let i = 0; i < extraSheets; i += 1) sheets.push({ name: `Extra ${i}`, rows: [['x'], ['y']] })
  return writer.xlsxOf(sheets)
}
const bytesFile = (name, bytes) => ({ name, size: bytes.length, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) })

test('a workbook attaches as its first sheet, cut to 60 rows, saying what was left out', async () => {
  const sheet = await reader.readSpreadsheet(bytesFile('orders.xlsx', workbook(100, 2)))
  const text = attach.spreadsheetAttachment(sheet)
  assert.match(text, /^Attached document \(orders\.xlsx, sheet "Orders" \(first 60 of 100 rows\); source data\):/)
  assert.match(text, /Item \| Qty/)
  assert.match(text, /Thing 59 \| 60/)
  assert.ok(!text.includes('Thing 60 |'))
  assert.match(text, /… 40 more rows/)
  assert.match(text, /2 more sheets, not attached: Extra 0, Extra 1\./)
})

test('a short workbook says nothing about a cut', async () => {
  const sheet = await reader.readSpreadsheet(bytesFile('small.xlsx', workbook(3)))
  const text = attach.spreadsheetAttachment(sheet)
  assert.ok(!text.includes('first 60'))
  assert.ok(!text.includes('more sheet'))
})

test('a CSV of two or more columns attaches as a table; one column of text goes in as it was', async () => {
  const table = await reader.readSpreadsheet(bytesFile('a.csv', new TextEncoder().encode('Ürün;Adet\nSandalye;2\n')))
  assert.match(attach.spreadsheetAttachment(table), /Ürün \| Adet\nSandalye \| 2/)
  const prose = await reader.readSpreadsheet(bytesFile('notes.csv', new TextEncoder().encode('just some words\nand more\n')))
  assert.equal(attach.spreadsheetAttachment(prose), null)
})

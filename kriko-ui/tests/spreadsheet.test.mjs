import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { deflateRawSync } from 'node:zlib'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'

/**
 * The spreadsheet reader: CSV and `.xlsx` read with no dependency.
 *
 * `spreadsheet.ts` and `sheet.ts` are pure, so they are transpiled and imported
 * directly. Every workbook here is built in the test, by `xlsxOf` (the writer
 * the app ships) or by hand, so no binary fixture is committed. The workbook
 * tests run twice, once with no `DOMParser` (what Node has: the reader's own
 * scanner) and once with jsdom's, so both paths are exercised.
 */

let directory, reader, writer
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-spreadsheet-'))
  for (const [source, name] of [['src/engine/sheet.ts', 'sheet.mjs'], ['src/engine/spreadsheet.ts', 'spreadsheet.mjs']]) {
    const code = await readFile(source, 'utf8')
    const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
    await writeFile(join(directory, name), built)
  }
  writer = await import(pathToFileURL(join(directory, 'sheet.mjs')))
  reader = await import(pathToFileURL(join(directory, 'spreadsheet.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const bytesOf = (text) => new TextEncoder().encode(text)

// ── CSV ──

test('a plain CSV is a header and rows', () => {
  const table = reader.parseCsv('Item,Qty,Price\nChair,2,100\nDesk,1,250\n', 'orders.csv')
  assert.equal(table.name, 'orders')
  assert.deepEqual(table.header, ['Item', 'Qty', 'Price'])
  assert.deepEqual(table.rows, [['Chair', '2', '100'], ['Desk', '1', '250']])
  assert.equal(table.truncated, undefined)
})

test('a byte order mark is not part of the first header', () => {
  const table = reader.parseCsv('﻿Item,Qty\nChair,2')
  assert.deepEqual(table.header, ['Item', 'Qty'])
  assert.equal(table.name, 'Sheet1')
})

test('a semicolon file with decimal commas keeps its commas inside the cells', () => {
  const table = reader.parseCsv('Ürün;Birim Fiyat;Adet\nMasa, büyük;1.234,56;2\nSandalye;99,90;4\n')
  assert.deepEqual(table.header, ['Ürün', 'Birim Fiyat', 'Adet'])
  assert.deepEqual(table.rows, [['Masa, büyük', '1.234,56', '2'], ['Sandalye', '99,90', '4']])
})

test('tab and pipe delimiters are found too', () => {
  assert.deepEqual(reader.parseCsv('a\tb\tc\n1\t2\t3').rows, [['1', '2', '3']])
  assert.deepEqual(reader.parseCsv('a|b|c\n1|2|3').header, ['a', 'b', 'c'])
})

test('delimiters inside quotes are not counted when the delimiter is chosen', () => {
  const table = reader.parseCsv('"a;b;c;d",x\n"1;2;3;4",y\n')
  assert.deepEqual(table.header, ['a;b;c;d', 'x'])
  assert.deepEqual(table.rows, [['1;2;3;4', 'y']])
})

test('a one-column file falls back to the comma', () => {
  const table = reader.parseCsv('Item\nChair\nDesk')
  assert.deepEqual(table.header, ['Item'])
  assert.equal(table.rows.length, 2)
})

test('quotes: doubled quotes, an embedded newline, an embedded delimiter', () => {
  const table = reader.parseCsv('Item,Note\n"Chair, tall","He said ""no""\nand left"\nDesk,ok\n')
  assert.deepEqual(table.rows, [['Chair, tall', 'He said "no"\nand left'], ['Desk', 'ok']])
})

test('a quote in the middle of an unquoted field is just a quote', () => {
  const table = reader.parseCsv('a,b\n5" screen,ok')
  assert.deepEqual(table.rows, [['5" screen', 'ok']])
})

test('an unterminated quote reads to the end instead of failing', () => {
  const table = reader.parseCsv('a,b\n1,"never closed\nstill going')
  assert.deepEqual(table.rows, [['1', 'never closed\nstill going']])
})

test('CRLF, LF and a lone CR all end rows', () => {
  for (const eol of ['\r\n', '\n', '\r']) {
    const table = reader.parseCsv(['a,b', '1,2', '3,4'].join(eol) + eol)
    assert.deepEqual(table.rows, [['1', '2'], ['3', '4']], JSON.stringify(eol))
  }
})

test('ragged rows are padded, blank rows are dropped, the header is trimmed', () => {
  const table = reader.parseCsv('  Item , ,Qty\n\n1\n,,\n2,x,3\n   \n')
  assert.deepEqual(table.header, ['Item', 'Column 2', 'Qty'])
  assert.deepEqual(table.rows, [['1', '', ''], ['2', 'x', '3']])
})

test('leading blank rows come before the header, which is the first row with anything in it', () => {
  const table = reader.parseCsv('\n\n,,\nItem,Qty\nChair,2')
  assert.deepEqual(table.header, ['Item', 'Qty'])
})

test('a row wider than the header widens it, a trailing delimiter does not', () => {
  const wide = reader.parseCsv('a,b\n1,2,3\n')
  assert.deepEqual(wide.header, ['a', 'b', 'Column 3'])
  assert.deepEqual(wide.rows, [['1', '2', '3']])
  const trailing = reader.parseCsv('a,b,\n1,2,\n')
  assert.deepEqual(trailing.header, ['a', 'b'])
  assert.deepEqual(trailing.rows, [['1', '2']])
})

test('an empty file is an empty table', () => {
  const table = reader.parseCsv('')
  assert.deepEqual(table, { name: 'Sheet1', header: [], rows: [] })
})

test('5001 data rows keep 5000 and count the one cut', () => {
  assert.equal(reader.MAX_ROWS, 5000)
  const lines = ['n,v']
  for (let i = 1; i <= 5001; i += 1) lines.push(`${i},x`)
  const table = reader.parseCsv(lines.join('\n'))
  assert.equal(table.rows.length, 5000)
  assert.equal(table.rows[4999][0], '5000')
  assert.equal(table.truncated, 1)
  const exact = reader.parseCsv(lines.slice(0, 5001).join('\n'))
  assert.equal(exact.rows.length, 5000)
  assert.equal(exact.truncated, undefined)
})

test('a cell that starts with = + - or @ is returned as typed', () => {
  const table = reader.parseCsv('a,b\n=SUM(A1:A9),+1\n-2,@cmd\n"=HYPERLINK(""http://x"")",ok')
  assert.deepEqual(table.rows, [['=SUM(A1:A9)', '+1'], ['-2', '@cmd'], ['=HYPERLINK("http://x")', 'ok']])
})

// ── the file ──

test('readSpreadsheet reads a CSV file by its bytes', async () => {
  const sheet = await reader.readSpreadsheet(new File(['Item,Qty\nChair,2\n'], 'list.csv'))
  assert.equal(sheet.fileName, 'list.csv')
  assert.equal(sheet.format, 'csv')
  assert.equal(sheet.tables.length, 1)
  assert.deepEqual(sheet.tables[0].rows, [['Chair', '2']])
})

test('a CSV Excel saved in the Turkish Windows code page is read as Turkish', async () => {
  // Ürün;Fiyat\nŞişe;1,5 in windows-1254: Ü DC, ü FC, Ş DE, ş FE, ı FD
  const bytes = Uint8Array.from([0xdc, 0x72, 0xfc, 0x6e, 0x3b, 0x46, 0x69, 0x79, 0x61, 0x74, 0x0a, 0xde, 0x69, 0xfe, 0x65, 0x3b, 0x31, 0x2c, 0x35])
  const sheet = await reader.readSpreadsheet({ name: 'tr.csv', arrayBuffer: async () => bytes.buffer })
  assert.deepEqual(sheet.tables[0].header, ['Ürün', 'Fiyat'])
  assert.deepEqual(sheet.tables[0].rows, [['Şişe', '1,5']])
})

test('a UTF-16 file with a byte order mark is read', async () => {
  const text = 'Item;Qty\nChair;2'
  const bytes = new Uint8Array(2 + text.length * 2)
  bytes[0] = 0xff; bytes[1] = 0xfe
  for (let i = 0; i < text.length; i += 1) { bytes[2 + i * 2] = text.charCodeAt(i) }
  const sheet = await reader.readSpreadsheet({ name: 'u16.csv', arrayBuffer: async () => bytes.buffer })
  assert.deepEqual(sheet.tables[0].rows, [['Chair', '2']])
  const be = new Uint8Array(2 + text.length * 2)
  be[0] = 0xfe; be[1] = 0xff
  for (let i = 0; i < text.length; i += 1) { be[3 + i * 2] = text.charCodeAt(i) }
  const flipped = await reader.readSpreadsheet({ name: 'u16be.csv', arrayBuffer: async () => be.buffer })
  assert.deepEqual(flipped.tables[0].rows, [['Chair', '2']])
})

test('old .xls and .ods files are refused with the way out', async () => {
  for (const name of ['old.xls', 'OLD.XLS', 'calc.ods']) {
    await assert.rejects(
      () => reader.readSpreadsheet({ name, arrayBuffer: async () => new ArrayBuffer(8) }),
      (error) => error instanceof Error && /\.xlsx or \.csv/.test(error.message) && error.message.includes(name),
    )
  }
  // an old binary workbook renamed to .csv is still recognised by its first bytes
  const ole = Uint8Array.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1, 0, 0])
  await assert.rejects(
    () => reader.readSpreadsheet({ name: 'sneaky.csv', arrayBuffer: async () => ole.buffer }),
    /old Excel file.*\.xlsx or \.csv/,
  )
})

test('a file over 10 MB is refused, by its size and by what it really holds', async () => {
  await assert.rejects(
    () => reader.readSpreadsheet({ name: 'big.csv', size: 11 * 1024 * 1024, arrayBuffer: async () => assert.fail('must not be read') }),
    /larger than 10 MB/,
  )
  await assert.rejects(
    () => reader.readSpreadsheet({ name: 'liar.csv', arrayBuffer: async () => new ArrayBuffer(10 * 1024 * 1024 + 1) }),
    /larger than 10 MB/,
  )
})

test('binary junk and a fake .xlsx are refused with plain words', async () => {
  const junk = Uint8Array.from([1, 2, 0, 3, 4, 5])
  await assert.rejects(() => reader.readSpreadsheet({ name: 'a.bin', arrayBuffer: async () => junk.buffer }), /does not look like a spreadsheet/)
  await assert.rejects(() => reader.readSpreadsheet({ name: 'a.xlsx', arrayBuffer: async () => bytesOf('just text').buffer }), /not a readable Excel workbook/)
})

test('a workbook is recognised by its first bytes whatever it is named', async () => {
  const bytes = writer.xlsxOf([{ name: 'S', rows: [['a', 'b'], ['1', '2']] }])
  const sheet = await reader.readSpreadsheet({ name: 'export.csv', arrayBuffer: async () => bytes.buffer })
  assert.equal(sheet.format, 'xlsx')
  assert.equal(sheet.fileName, 'export.csv')
  assert.deepEqual(sheet.tables[0].rows, [['1', '2']])
})

// ── building workbooks ──

const u16 = (n) => [n & 0xff, (n >>> 8) & 0xff]
const u32 = (n) => [n & 0xff, (n >>> 8) & 0xff, (n >>> 16) & 0xff, (n >>> 24) & 0xff]

/** A zip with a choice per entry: stored or deflated, and fields that lie. */
function zipOf(entries) {
  const out = []
  const central = []
  let size = 0
  const push = (...parts) => { for (const part of parts) { out.push(Uint8Array.from(part)); size += part.length } }
  for (const entry of entries) {
    const name = [...bytesOf(entry.name)]
    const raw = entry.data
    const method = entry.method ?? 0
    const stored = entry.compressed ?? (method === 8 ? deflateRawSync(raw) : raw)
    const crc = writer.crc32(raw)
    const declared = entry.declaredSize ?? raw.length
    central.push({ name, method, crc, csize: stored.length, usize: declared, offset: size, flags: entry.flags ?? 0 })
    push(u32(0x04034b50), u16(20), u16(0x0800), u16(method), u16(0), u16(0), u32(crc), u32(stored.length), u32(declared), u16(name.length), u16(0), name, stored)
  }
  const start = size
  for (const c of central) {
    push(u32(0x02014b50), u16(20), u16(20), u16(0x0800 | c.flags), u16(c.method), u16(0), u16(0), u32(c.crc), u32(c.csize), u32(c.usize), u16(c.name.length), u16(0), u16(0), u16(0), u16(0), u32(0), u32(c.offset), c.name)
  }
  const total = size - start
  push(u32(0x06054b50), u16(0), u16(0), u16(central.length), u16(central.length), u32(total), u32(start), u16(0))
  const bytes = new Uint8Array(size)
  let at = 0
  for (const chunk of out) { bytes.set(chunk, at); at += chunk.length }
  return bytes
}

const XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
const MAIN = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
const part = (name, body, method = 0) => ({ name, data: bytesOf(XML + body), method })
const REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

/** Run `body` once per XML path: the reader's own scanner, then jsdom's DOMParser. */
function eachParser(label, body) {
  test(`${label} (own scanner)`, async () => {
    assert.equal(typeof globalThis.DOMParser, 'undefined', 'node has no DOMParser')
    await body()
  })
  test(`${label} (DOMParser)`, async () => {
    const { window } = new JSDOM('')
    let used = 0
    globalThis.DOMParser = class extends window.DOMParser { constructor() { super(); used += 1 } }
    try {
      await body()
      assert.ok(used > 0, 'the DOMParser was used')
    } finally {
      delete globalThis.DOMParser
    }
  })
}

const rectangular = (rows) => rows.map((row) => row.map((cell) => (cell == null ? '' : String(cell))))

// ── round trip with the writer the app ships ──

eachParser('a workbook written by xlsxOf is read back equal to its input', async () => {
  const first = [
    ['Item', 'Qty', 'Price', 'Note'],
    ['Chair', 2, 1234.5, 'plain'],
    ['Ürün <b> & "q" \'s\'', 0, -3.25, '  padded  '],
    ['=SUM(A1:A9)', 12000, 0.1, '+1'],
    ['-1', 7, null, '@cmd'],
    ['line\nbreak', 1, 5, 'tab\there'],
  ]
  const second = [['Vendor', 'Url'], ['Acme', 'https://acme.example/x?a=1&b=2']]
  const bytes = writer.xlsxOf([
    { name: 'Orders', rows: first },
    { name: 'Empty', rows: [] },
    { name: 'Blanks', rows: [[null, ''], [null]] },
    { name: 'Vendors', rows: second },
  ])
  const sheet = await reader.parseXlsx(bytes, 'orders.xlsx')
  assert.equal(sheet.fileName, 'orders.xlsx')
  assert.equal(sheet.format, 'xlsx')
  assert.deepEqual(sheet.tables.map((t) => t.name), ['Orders', 'Vendors'])
  const [orders, vendors] = sheet.tables
  const expected = rectangular(first)
  assert.deepEqual(orders.header, expected[0])
  assert.deepEqual(orders.rows, expected.slice(1))
  assert.deepEqual(vendors.header, second[0])
  assert.deepEqual(vendors.rows, rectangular(second.slice(1)))
})

eachParser('a workbook with more than 5000 rows keeps 5000 and counts the rest', async () => {
  const rows = [['n', 'v']]
  for (let i = 1; i <= 5002; i += 1) rows.push([i, 'x'])
  const [table] = (await reader.parseXlsx(writer.xlsxOf([{ name: 'Big', rows }]))).tables
  assert.equal(table.rows.length, 5000)
  assert.equal(table.rows[4999][0], '5000')
  assert.equal(table.truncated, 2)
})

// ── a workbook built by hand ──

const handStyles = `<styleSheet ${MAIN}>` +
  `<numFmts count="3"><numFmt numFmtId="164" formatCode="dd/mm/yyyy"/><numFmt numFmtId="165" formatCode="h:mm"/>` +
  `<numFmt numFmtId="166" formatCode="#,##0.00 &quot;TL&quot;"/></numFmts>` +
  `<cellStyleXfs count="1"><xf numFmtId="14"/></cellStyleXfs>` +
  `<cellXfs count="6"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/><xf numFmtId="165"/><xf numFmtId="166"/><xf numFmtId="20"/></cellXfs>` +
  `</styleSheet>`

const handShared = `<sst ${MAIN} count="8" uniqueCount="8">` +
  '<si><t>Item</t></si><si><t>Qty</t></si><si><t>Price</t></si><si><t>Bought</t></si>' +
  '<si><r><t>Mac</t></r><r><rPr><b/></rPr><t xml:space="preserve">Book </t></r><r><t>Pro</t></r></si>' +
  '<si><t>Ürün</t><rPh sb="0" eb="1"><t>ignored</t></rPh></si>' +
  '<si><t>a_x000D_b</t></si>' +
  '<si><t>T&amp;C &lt;ok&gt; &#65;&#x42;</t></si>' +
  '</sst>'

const handOrders = `<worksheet ${MAIN}><sheetData>` +
  '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c></row>' +
  '<row r="2"><c r="A2" t="s"><v>4</v></c><c r="B2"><v>2</v></c><c r="C2" s="4"><v>1234.5</v></c><c r="D2" s="1"><v>45292</v></c></row>' +
  '<row r="3"><c r="A3" t="inlineStr"><is><t>Inline</t></is></c><c r="C3"><v>0.30000000000000004</v></c>' +
  '<c r="E3" t="inlineStr"><is><r><t>x</t></r><r><t>y</t></r><rPh><t>no</t></rPh></is></c></row>' +
  '<row r="4"/>' +
  '<row r="6"><c r="A6" t="str"><f>A2&amp;"x"</f><v>=cached</v></c><c r="B6" t="b"><v>1</v></c><c r="C6" t="e"><v>#DIV/0!</v></c><c r="D6" s="2"><v>45658</v></c></row>' +
  '<row r="7"><c r="A7" t="inlineStr"><is><t>=HYPERLINK("http://x")</t></is></c><c r="B7"><f>SUM(B2:B3)</f><v>2</v></c><c r="C7"><f>1+1</f></c><c r="D7" t="b"><v>0</v></c></row>' +
  '<row r="8"><c r="A8" t="s"><v>5</v></c><c r="B8" s="3"><v>0.5</v></c><c r="C8" s="5"><v>0.75</v></c><c r="D8" s="99"><v>45292</v></c></row>' +
  '<row r="9"><c r="A9" t="s"><v>6</v></c><c r="B9" s="1"><v>61</v></c><c r="C9" s="1"><v>59</v></c><c r="D9" t="s"><v>7</v></c></row>' +
  '<row r="10"><c r="A10" t="inlineStr"><is><t>+1</t></is></c><c r="C10" s="1"><v>0</v></c><c r="D10" s="1"><v>3000000</v></c></row>' +
  '</sheetData></worksheet>'

const handSecond = `<worksheet ${MAIN}><sheetData>` +
  '<row r="1"><c r="B1" t="inlineStr"><is><t>Vendor</t></is></c><c r="D1" t="inlineStr"><is><t>Url</t></is></c></row>' +
  '<row r="3"><c r="B3" t="inlineStr"><is><t>Acme</t></is></c><c r="D3" t="inlineStr"><is><t>https://a.example</t></is></c></row>' +
  '</sheetData></worksheet>'

const handWorkbook = (method, { workbookPr = '' } = {}) => zipOf([
  part('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>', method),
  part('xl/workbook.xml', `<workbook ${MAIN}>${workbookPr}<sheets>` +
    '<sheet name="Orders" sheetId="1" r:id="rId2"/><sheet name="Nothing" sheetId="2" r:id="rId3"/><sheet name="Second" sheetId="3" r:id="rId1"/>' +
    '</sheets></workbook>', method),
  part('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    `<Relationship Id="rId1" Type="${REL}/worksheet" Target="/xl/worksheets/data.xml"/>` +
    `<Relationship Id="rId2" Type="${REL}/worksheet" Target="worksheets/sheet9.xml"/>` +
    `<Relationship Id="rId3" Type="${REL}/worksheet" Target="../xl/worksheets/empty.xml"/>` +
    `<Relationship Id="rId4" Type="${REL}/sharedStrings" Target="sharedStrings.xml"/>` +
    '</Relationships>', method),
  part('xl/sharedStrings.xml', handShared.slice(0), method),
  part('xl/styles.xml', handStyles, method),
  part('xl/worksheets/sheet9.xml', handOrders, method),
  part('xl/worksheets/empty.xml', `<worksheet ${MAIN}><sheetData/></worksheet>`, method),
  part('xl/worksheets/data.xml', handSecond, method),
])

const checkHandWorkbook = (sheet) => {
  assert.deepEqual(sheet.tables.map((t) => t.name), ['Orders', 'Second'], 'workbook order, empty sheet dropped')
  const [orders, second] = sheet.tables
  assert.deepEqual(orders.header, ['Item', 'Qty', 'Price', 'Bought', 'Column 5'])
  assert.deepEqual(orders.rows, [
    ['MacBook Pro', '2', '1234.5', '2024-01-01', ''],                       // rich text runs; date style 14; money format stays a number
    ['Inline', '', '0.3', '', 'xy'],                                        // inline string, sparse cells, float noise, phonetic hint left out
    ['=cached', 'TRUE', '#DIV/0!', '2025-01-01', ''],                       // formula's stored text kept as typed; b; e; custom date format
    ['=HYPERLINK("http://x")', '2', '', 'FALSE', ''],                       // never evaluated; cached value; no cached value is empty
    ['Ürün', '12:00', '18:00', '45292', ''],                                // phonetic left out; time styles; unknown style is a number
    ['a\rb', '1900-03-01', '1900-02-28', 'T&C <ok> AB', ''],                // _x000D_; the 1900 leap year bug; entities
    ['+1', '', '0', '3000000', ''],                                         // text starting with +; serial 0 and past year 9999 stay numbers
  ])
  assert.deepEqual(second.header, ['Column 1', 'Vendor', 'Column 3', 'Url'])
  assert.deepEqual(second.rows, [['', 'Acme', '', 'https://a.example']])
}

for (const [label, method] of [['stored', 0], ['deflated', 8]]) {
  eachParser(`a hand-built workbook with shared strings, inline strings, dates and sparse cells (${label})`, async () => {
    checkHandWorkbook(await reader.parseXlsx(handWorkbook(method), 'hand.xlsx'))
  })
}

eachParser('the 1904 date system counts from 1904', async () => {
  const bytes = zipOf([
    part('xl/workbook.xml', `<workbook ${MAIN}><workbookPr date1904="1"/><sheets><sheet name="D" sheetId="1" r:id="rId1"/></sheets></workbook>`),
    part('xl/styles.xml', `<styleSheet ${MAIN}><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>`),
    part('xl/worksheets/sheet1.xml', `<worksheet ${MAIN}><sheetData><row><c t="inlineStr"><is><t>When</t></is></c></row><row><c s="1"><v>43830</v></c></row></sheetData></worksheet>`),
  ])
  const [table] = (await reader.parseXlsx(bytes)).tables
  assert.deepEqual(table.rows, [['2024-01-01']])
})

eachParser('a workbook with no relationships part falls back to the numbered sheet files', async () => {
  const bytes = zipOf([
    part('xl/workbook.xml', `<workbook ${MAIN}><sheets><sheet name="One" sheetId="1" r:id="rId1"/><sheet name="Gone" sheetId="2" r:id="rId2"/></sheets></workbook>`),
    part('xl/worksheets/sheet1.xml', `<worksheet ${MAIN}><sheetData><row><c r="A1" t="inlineStr"><is><t>h</t></is></c></row><row><c r="A2"><v>5</v></c></row></sheetData></worksheet>`),
  ])
  const sheet = await reader.parseXlsx(bytes, 'x.xlsx')
  assert.deepEqual(sheet.tables.map((t) => [t.name, t.header, t.rows]), [['One', ['h'], [['5']]]])
})

eachParser('prefixed elements, single quotes, CDATA, comments and a stray ampersand are tolerated', async () => {
  const bytes = zipOf([
    part('xl/workbook.xml', '<x:workbook xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
      "<!-- a comment --><x:sheets><x:sheet name='A &amp; B' sheetId='1' r:id='rId1'/></x:sheets></x:workbook>"),
    part('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id=\'rId1\' Target=\'worksheets/s.xml\'/></Relationships>'),
    part('xl/worksheets/s.xml', '<x:worksheet xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><x:sheetData>' +
      '<x:row r="1"><x:c r="A1" t="inlineStr"><x:is><x:t><![CDATA[Item <raw>]]></x:t></x:is></x:c><x:c r="B1" t="inlineStr"><x:is><x:t>Note</x:t></x:is></x:c></x:row>' +
      '<x:row r="2"><x:c r="A2" t="inlineStr"><x:is><x:t>a & b</x:t></x:is></x:c><x:c r="B2" t="str"><x:v>x</x:v></x:c></x:row>' +
      '</x:sheetData></x:worksheet>'),
  ])
  const [table] = (await reader.parseXlsx(bytes)).tables
  assert.equal(table.name, 'A & B')
  assert.deepEqual(table.header, ['Item <raw>', 'Note'])
  assert.deepEqual(table.rows, [['a & b', 'x']])
})

eachParser('a workbook with no sheets with cells has no tables, and a header alone is still a table', async () => {
  const none = await reader.parseXlsx(writer.xlsxOf([{ name: 'E', rows: [] }]))
  assert.deepEqual(none.tables, [])
  const [only] = (await reader.parseXlsx(writer.xlsxOf([{ name: 'H', rows: [['a', 'b']] }]))).tables
  assert.deepEqual(only, { name: 'H', header: ['a', 'b'], rows: [], numeric: [] })
})

// ── hostile input ──

/** A valid one-sheet workbook whose sheet entry is deflated, for tampering. */
const tinyWorkbook = (sheetEntry) => zipOf([
  part('xl/workbook.xml', `<workbook ${MAIN}><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>`),
  sheetEntry,
])

test('an entry that declares more than 50 MB unpacked is refused before anything is inflated', async () => {
  const bytes = tinyWorkbook({ name: 'xl/worksheets/sheet1.xml', data: bytesOf('<worksheet/>'), method: 8, declaredSize: 60 * 1024 * 1024 })
  await assert.rejects(() => reader.parseXlsx(bytes), (e) => e instanceof Error && /more than 50 MB/.test(e.message))
})

test('an entry that unpacks to more than it declared is stopped, not inflated to the end', { timeout: 20000 }, async () => {
  const bomb = new Uint8Array(30 * 1024 * 1024) // zeros: tiny when deflated
  const compressed = deflateRawSync(bomb)
  assert.ok(compressed.length < 100 * 1024)
  const bytes = tinyWorkbook({ name: 'xl/worksheets/sheet1.xml', data: bomb, method: 8, compressed, declaredSize: 1000 })
  await assert.rejects(() => reader.parseXlsx(bytes), (e) => e instanceof Error && /more than it says/.test(e.message))
})

test('a truncated zip is a plain error, never a hang', { timeout: 10000 }, async () => {
  const whole = writer.xlsxOf([{ name: 'S', rows: [['a', 'b'], ['1', '2']] }])
  for (const cut of [0, 10, 21, whole.length >> 1, whole.length - 30, whole.length - 1]) {
    await assert.rejects(
      () => reader.parseXlsx(whole.slice(0, cut), 'cut.xlsx'),
      (e) => e instanceof Error && e.constructor === Error && /damaged/.test(e.message),
      `cut at ${cut}`,
    )
  }
})

test('a deflated entry cut short is a plain error, never a hang', { timeout: 10000 }, async () => {
  const rows = []
  for (let i = 0; i < 2000; i += 1) rows.push(`<row><c t="inlineStr"><is><t>row ${i}</t></is></c></row>`)
  const raw = bytesOf(`<worksheet ${MAIN}><sheetData>${rows.join('')}</sheetData></worksheet>`)
  const full = deflateRawSync(raw)
  const bytes = tinyWorkbook({ name: 'xl/worksheets/sheet1.xml', data: raw, method: 8, compressed: full.subarray(0, full.length >> 1) })
  await assert.rejects(() => reader.parseXlsx(bytes), (e) => e instanceof Error && /damaged/.test(e.message))
})

test('a directory that points outside the file is a plain error', async () => {
  const bytes = writer.xlsxOf([{ name: 'S', rows: [['a'], ['b']] }])
  const view = new DataView(bytes.buffer)
  view.setUint32(bytes.length - 22 + 16, bytes.length + 1000, true) // central directory offset
  await assert.rejects(() => reader.parseXlsx(bytes), /damaged/)
})

test('an encrypted entry, an unknown compression, a lying stored size and a zip64 file are refused', async () => {
  const sheet = (extra) => tinyWorkbook({ name: 'xl/worksheets/sheet1.xml', data: bytesOf('<worksheet/>'), ...extra })
  await assert.rejects(() => reader.parseXlsx(sheet({ flags: 1 })), /password protected/)
  await assert.rejects(() => reader.parseXlsx(sheet({ method: 12 })), /compression/)
  await assert.rejects(() => reader.parseXlsx(sheet({ method: 0, declaredSize: 3 })), /damaged/)
  const big = writer.xlsxOf([{ name: 'S', rows: [['a'], ['b']] }])
  new DataView(big.buffer).setUint16(big.length - 22 + 10, 0xffff, true)
  await assert.rejects(() => reader.parseXlsx(big), /too large/)
})

test('a zip that is not a workbook says so', async () => {
  const bytes = zipOf([part('word/document.xml', '<w:document/>')])
  await assert.rejects(() => reader.parseXlsx(bytes, 'letter.docx'), /not an Excel workbook/)
})

test('without DecompressionStream a deflated workbook says what to do instead', async () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'DecompressionStream')
  Object.defineProperty(globalThis, 'DecompressionStream', { value: undefined, configurable: true, writable: true })
  try {
    await assert.rejects(() => reader.parseXlsx(handWorkbook(8)), /cannot unpack Excel files.*\.csv/)
    // stored workbooks need no inflater
    assert.equal((await reader.parseXlsx(handWorkbook(0))).tables.length, 2)
  } finally {
    Object.defineProperty(globalThis, 'DecompressionStream', original)
  }
})

test('a formula is never run: the cell is the text that is stored', async () => {
  const bytes = writer.xlsxOf([{ name: 'F', rows: [['a', 'b'], ['=1+1', '@SUM(1)'], ['+cmd|\' /C calc\'!A0', '-2+3']] }])
  const [table] = (await reader.parseXlsx(bytes)).tables
  assert.deepEqual(table.rows, [['=1+1', '@SUM(1)'], ['+cmd|\' /C calc\'!A0', '-2+3']])
})

test('deeply nested XML does not overflow the stack on either path', async () => {
  const depth = 20000
  const xml = `<worksheet>${'<a>'.repeat(depth)}${'</a>'.repeat(depth)}<sheetData><row><c t="inlineStr"><is><t>ok</t></is></c></row></sheetData></worksheet>`
  const bytes = tinyWorkbook({ name: 'xl/worksheets/sheet1.xml', data: bytesOf(xml) })
  const [table] = (await reader.parseXlsx(bytes)).tables
  assert.deepEqual(table.header, ['ok'])
  const { window } = new JSDOM('')
  globalThis.DOMParser = window.DOMParser
  try {
    // either the document parses and is walked iteratively, or the parser refuses
    // and the scanner takes over: the answer is the same
    assert.deepEqual((await reader.parseXlsx(bytes)).tables[0].header, ['ok'])
  } finally {
    delete globalThis.DOMParser
  }
})

// ── amounts ──

test('parseAmount reads prices in every form a list is written in', () => {
  const cases = [
    ['1.234,56', 1234.56, ''],
    ['1,234.56', 1234.56, ''],
    ['1 234,56', 1234.56, ''],
    ['1 234,56', 1234.56, ''],
    ['12000', 12000, ''],
    ['12.000,00', 12000, ''],
    ['₺12.000,00', 12000, 'TRY'],
    ['$1,200', 1200, 'USD'],
    ['US$ 99.5', 99.5, 'USD'],
    ['1.200 TL', 1200, 'TRY'],
    ['1200TL', 1200, 'TRY'],
    ['TRY 85,5', 85.5, 'TRY'],
    ['EUR 260', 260, 'EUR'],
    ['260 eur', 260, 'EUR'],
    ['€260', 260, 'EUR'],
    ['£3,50', 3.5, 'GBP'],
    ['GBP 1,000,000', 1000000, 'GBP'],
    ['(1,200)', -1200, ''],
    ['($1,200.50)', -1200.5, 'USD'],
    ['-1.200,50 €', -1200.5, 'EUR'],
    ['−5', -5, ''],
    ['+7,5', 7.5, ''],
    ['1,234', 1234, ''],   // a 3-digit group is thousands
    ['1.234', 1234, ''],
    ['1,23', 1.23, ''],    // anything else is a decimal
    ['12.5', 12.5, ''],
    ['0,123', 0.123, ''],
    ['0.123', 0.123, ''],
    ['1234,567', 1234.567, ''],
    ['1,2345', 1.2345, ''],
    ['.5', 0.5, ''],
    [',5', 0.5, ''],
    ['12,', 12, ''],
    ['1,234,567', 1234567, ''],
    ['1.234.567', 1234567, ''],
    ['1.234.567,89', 1234567.89, ''],
    ["1'234'567", 1234567, ''],
    ['1 234 567', 1234567, ''],
    ['  42  ', 42, ''],
    ['0', 0, ''],
  ]
  for (const [text, value, currency] of cases) {
    const got = reader.parseAmount(text)
    assert.ok(got, `"${text}" is an amount`)
    assert.equal(got.value, value, text)
    assert.equal(got.currency, currency, text)
  }
})

test('parseAmount says null for what is not only a number', () => {
  for (const text of ['', '   ', 'abc', '12 adet', 'Chair 2', '₺', 'TL', '1.2.3', '1,2,3', '12,34.5', '1.2,3.4', '1 23', '1 2345', '12-', '1e5', '5%', 'N/A', '--5', '()']) {
    assert.equal(reader.parseAmount(text), null, JSON.stringify(text))
  }
  assert.equal(reader.parseAmount(12), null, 'only text is read')
  assert.equal(Object.is(reader.parseAmount('(0)').value, 0), true, 'a negative zero is a zero')
})

test('plain parseAmount reads machine-formatted numbers: the dot is always the decimal point', () => {
  const plain = (text) => reader.parseAmount(text, { plain: true })
  assert.deepEqual(plain('1.234'), { value: 1.234, currency: '' })
  assert.deepEqual(plain('1234.5'), { value: 1234.5, currency: '' })
  assert.deepEqual(plain('12000'), { value: 12000, currency: '' })
  assert.deepEqual(plain('-0.5'), { value: -0.5, currency: '' })
  assert.deepEqual(plain('1.5e-7'), { value: 1.5e-7, currency: '' })
  assert.deepEqual(plain('₺1.234'), { value: 1.234, currency: 'TRY' })
  assert.deepEqual(plain('EUR 260'), { value: 260, currency: 'EUR' })
  assert.deepEqual(plain('(2.5)'), { value: -2.5, currency: '' })
  for (const text of ['1,234', '1.234,5', '1 234', '1.2.3', 'abc', '']) assert.equal(plain(text), null, text)
  assert.equal(reader.parseAmount('1.234').value, 1234, 'the default reading is unchanged')
})

eachParser('a price stored as the number 1.234 is 1.234, the text "1.234" is 1234, and a CSV cell uses the heuristic', async () => {
  const bytes = zipOf([
    part('xl/workbook.xml', `<workbook ${MAIN}><sheets><sheet name="P" sheetId="1" r:id="rId1"/></sheets></workbook>`),
    part('xl/styles.xml', `<styleSheet ${MAIN}><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>`),
    part('xl/worksheets/sheet1.xml', `<worksheet ${MAIN}><sheetData>` +
      '<row r="1"><c r="A1" t="inlineStr"><is><t>Price</t></is></c><c r="B1" t="inlineStr"><is><t>Other</t></is></c></row>' +
      '<row r="2"><c r="A2"><v>1.234</v></c><c r="B2" t="inlineStr"><is><t>1.234</t></is></c></row>' +
      '<row r="3"><c r="A3" s="1"><v>45292</v></c><c r="B3" t="str"><v>5</v></c></row>' +
      '<row r="4"><c r="B4"><v>2</v></c></row>' +
      '</sheetData></worksheet>'),
  ])
  const [table] = (await reader.parseXlsx(bytes)).tables
  assert.deepEqual(table.numeric, [[true, false], [true, false], [false, true]])
  assert.deepEqual(reader.cellAmount(table, 0, 0), { value: 1.234, currency: '' })
  assert.deepEqual(reader.cellAmount(table, 0, 1), { value: 1234, currency: '' })
  assert.equal(reader.cellAmount(table, 1, 0), null, 'a date is not an amount')
  assert.deepEqual(reader.cellAmount(table, 1, 1), { value: 5, currency: '' })
  assert.deepEqual(reader.cellAmount(table, 2, 1), { value: 2, currency: '' })
  assert.equal(reader.cellAmount(table, 2, 0), null, 'an empty cell is not an amount')
  assert.equal(reader.cellAmount(table, 9, 0), null, 'a missing row is not an amount')
  const csv = reader.parseCsv('Price\n1.234\n"₺1.200,50"\n')
  assert.equal(csv.numeric, undefined)
  assert.deepEqual(reader.cellAmount(csv, 0, 0), { value: 1234, currency: '' })
  assert.deepEqual(reader.cellAmount(csv, 1, 0), { value: 1200.5, currency: 'TRY' })
})

// ── columns ──

const tableOf = (header, rows = []) => ({ name: 't', header, rows })

test('guessColumns reads English headers', () => {
  const got = reader.guessColumns(tableOf(['Product', 'Qty', 'Unit price', 'Currency', 'Supplier', 'Link', 'VAT', 'Notes', 'SKU']))
  assert.deepEqual(got, { name: 0, quantity: 1, price: 2, currency: 3, vendor: 4, url: 5, vat: 6, note: 7, sku: 8 })
})

test('guessColumns reads Turkish headers, diacritics folded, case ignored', () => {
  const got = reader.guessColumns(tableOf(['ÜRÜN ADI', 'ADET', 'Birim Fiyat (TL)', 'Para Birimi', 'Tedarikçi', 'Bağlantı url', 'KDV %', 'Not', 'Stok Kodu']))
  assert.deepEqual(got, { name: 0, quantity: 1, price: 2, currency: 3, vendor: 4, url: 5, vat: 6, note: 7, sku: 8 })
  assert.deepEqual(reader.guessColumns(tableOf(['Açıklama', 'Miktar', 'Tutar', 'Döviz', 'Satıcı', 'Firma', 'İlişkili kod'])),
    { name: 0, quantity: 1, price: 2, currency: 3, vendor: 4, sku: 6 })
  assert.deepEqual(reader.guessColumns(tableOf(['Adı', 'Fiyat'])), { name: 0, price: 1 })
})

test('the more specific header wins, and a column serves one role', () => {
  // "Vendor name" is a vendor, so the name role goes to the next column that fits
  const got = reader.guessColumns(tableOf(['Vendor name', 'Item', 'Product code', 'Item price']))
  assert.deepEqual(got, { vendor: 0, name: 1, sku: 2, price: 3 })
  // two columns that could both be the price: the unit price, not the total
  assert.equal(reader.guessColumns(tableOf(['Item', 'Total', 'Unit price'])).price, 2)
  // a column is never given two roles
  const one = reader.guessColumns(tableOf(['Price']))
  assert.deepEqual(one, { price: 0 })
  assert.deepEqual(reader.guessColumns(tableOf(['Grand total of order'])), {}, 'a weak word inside a longer header is not enough')
  assert.deepEqual(reader.guessColumns(tableOf(['Total'])), { price: 0 }, 'but a header that is only that word is')
})

test('with no name header the first mostly-text column is the name', () => {
  const rows = [['120', 'Standing desk', '2'], ['80', 'Chair', '4'], ['9', 'Lamp', '1']]
  const got = reader.guessColumns(tableOf(['A', 'B', 'Qty'], rows))
  assert.deepEqual(got, { quantity: 2, name: 1 })
  // numbers only: no guess
  assert.deepEqual(reader.guessColumns(tableOf(['A', 'B'], [['1', '2'], ['3', '4']])), {})
  // a column already given a role is not taken for the name, and empty columns are skipped
  const taken = reader.guessColumns(tableOf(['Supplier', 'X', 'Y'], [['Acme', '', 'Desk'], ['Beta', '', 'Lamp']]))
  assert.deepEqual(taken, { vendor: 0, name: 2 })
  assert.deepEqual(reader.guessColumns(tableOf([])), {})
})

// ── for a prompt ──

test('tableToText is a compact pipe-separated rendering', () => {
  const table = tableOf(['Item', 'Note'], [['Chair', 'a | b\nline'], ['Desk', 'x'.repeat(100)]])
  const text = reader.tableToText(table)
  const lines = text.split('\n')
  assert.equal(lines[0], 'Item | Note')
  assert.equal(lines[1], 'Chair | a / b line')
  assert.equal(lines[2], `Desk | ${'x'.repeat(79)}…`)
  assert.equal(lines.length, 3)
})

test('tableToText cuts at the limit and says how many rows are left', () => {
  const rows = Array.from({ length: 100 }, (_, i) => [`r${i}`])
  const table = tableOf(['n'], rows)
  const text = reader.tableToText(table)
  const lines = text.split('\n')
  assert.equal(lines.length, 1 + 60 + 1)
  assert.equal(lines.at(-1), '… 40 more rows')
  assert.equal(reader.tableToText(table, 3).split('\n').at(-1), '… 97 more rows')
  assert.equal(reader.tableToText(table, 0), 'n\n… 100 more rows')
  assert.equal(reader.tableToText(tableOf(['n'], rows.slice(0, 60))).includes('more rows'), false)
  // rows the reader counted but did not keep are rows too
  assert.equal(reader.tableToText({ ...tableOf(['n'], rows.slice(0, 2)), truncated: 5000 }).split('\n').at(-1), '… 5000 more rows')
})

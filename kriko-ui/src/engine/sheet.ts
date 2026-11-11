/** Spreadsheet export, with no dependency: CSV and a real `.xlsx` written by
 *  hand. An accountant opens the file in Excel, Numbers or LibreOffice, so the
 *  bytes have to be a valid Office Open XML package — a zip of stored (not
 *  compressed) entries, each with a correct CRC-32, which this module builds
 *  directly. Cells use inline strings, so no shared-strings part is needed.
 *
 *  The zip writer is deliberately tiny and only supports what a workbook needs:
 *  stored entries, one after another, then the central directory. Anything more
 *  (compression, streaming) is a library's job, and adding one here would put a
 *  dependency between the reader and their accountant's file.
 */

export type Cell = string | number | null | undefined

export interface Sheet {
  name: string
  rows: Cell[][]
}

// ── CSV ──────────────────────────────────────────────────────────────────────

const csvCell = (value: Cell): string => {
  if (value == null) return ''
  const text = String(value)
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** RFC 4180: comma separated, CRLF between rows, quoted when needed. */
export function csvOf(rows: Cell[][]): string {
  return rows.map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n'
}

// ── CRC-32 (the zip checksum) ───────────────────────────────────────────────

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let n = 0; n < 256; n += 1) {
    let c = n
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[n] = c >>> 0
  }
  return table
})()

export function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff
  for (let i = 0; i < bytes.length; i += 1) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

// ── little-endian writers ────────────────────────────────────────────────────

class Writer {
  private chunks: Uint8Array[] = []
  size = 0
  push(...bytes: number[]) {
    this.chunks.push(Uint8Array.from(bytes))
    this.size += bytes.length
  }
  u16(value: number) { this.push(value & 0xff, (value >>> 8) & 0xff) }
  u32(value: number) { this.push(value & 0xff, (value >>> 8) & 0xff, (value >>> 16) & 0xff, (value >>> 24) & 0xff) }
  bytes(data: Uint8Array) { this.chunks.push(data); this.size += data.length }
  text(value: string) { this.bytes(new TextEncoder().encode(value)) }
  out(): Uint8Array<ArrayBuffer> {
    const out = new Uint8Array(this.size)
    let at = 0
    for (const chunk of this.chunks) { out.set(chunk, at); at += chunk.length }
    return out
  }
}

interface ZipEntry {
  name: string
  data: Uint8Array
  crc: number
  offset: number
}

/** A zip archive with every entry stored (method 0): local header, data,
 *  central directory, end record. */
export function zipStored(entries: { name: string; data: Uint8Array }[]): Uint8Array<ArrayBuffer> {
  const writer = new Writer()
  const central: ZipEntry[] = []
  for (const entry of entries) {
    const name = new TextEncoder().encode(entry.name)
    const crc = crc32(entry.data)
    central.push({ name: entry.name, data: entry.data, crc, offset: writer.size })
    writer.u32(0x04034b50) // local file header
    writer.u16(20) // version needed
    writer.u16(0x0800) // UTF-8 names
    writer.u16(0) // stored
    writer.u16(0); writer.u16(0) // time, date
    writer.u32(crc)
    writer.u32(entry.data.length)
    writer.u32(entry.data.length)
    writer.u16(name.length)
    writer.u16(0) // no extra field
    writer.bytes(name)
    writer.bytes(entry.data)
  }
  const centralStart = writer.size
  for (const entry of central) {
    const name = new TextEncoder().encode(entry.name)
    writer.u32(0x02014b50) // central directory header
    writer.u16(20) // version made by
    writer.u16(20) // version needed
    writer.u16(0x0800)
    writer.u16(0)
    writer.u16(0); writer.u16(0)
    writer.u32(entry.crc)
    writer.u32(entry.data.length)
    writer.u32(entry.data.length)
    writer.u16(name.length)
    writer.u16(0); writer.u16(0); writer.u16(0); writer.u16(0)
    writer.u32(0) // external attributes
    writer.u32(entry.offset)
    writer.bytes(name)
  }
  const centralSize = writer.size - centralStart
  writer.u32(0x06054b50) // end of central directory
  writer.u16(0); writer.u16(0)
  writer.u16(central.length)
  writer.u16(central.length)
  writer.u32(centralSize)
  writer.u32(centralStart)
  writer.u16(0)
  return writer.out()
}

// ── the workbook parts ───────────────────────────────────────────────────────

const xmlEscape = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&apos;')

const columnName = (index: number): string => {
  let name = ''
  let n = index + 1
  while (n > 0) {
    const rem = (n - 1) % 26
    name = String.fromCharCode(65 + rem) + name
    n = Math.floor((n - 1) / 26)
  }
  return name
}

const sheetName = (name: string, taken: Set<string>): string => {
  const clean = (name || 'Sheet').replace(/[\\/*?:[\]]/g, ' ').trim().slice(0, 31) || 'Sheet'
  let candidate = clean
  let n = 2
  while (taken.has(candidate)) {
    const suffix = ` (${n})`
    candidate = clean.slice(0, 31 - suffix.length) + suffix
    n += 1
  }
  taken.add(candidate)
  return candidate
}

function worksheetXml(rows: Cell[][]): string {
  const body = rows.map((row, r) => {
    const cells = row.map((cell, c) => {
      const ref = `${columnName(c)}${r + 1}`
      if (cell == null || cell === '') return `<c r="${ref}"/>`
      if (typeof cell === 'number' && Number.isFinite(cell)) return `<c r="${ref}"><v>${cell}</v></c>`
      return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xmlEscape(String(cell))}</t></is></c>`
    }).join('')
    return `<row r="${r + 1}">${cells}</row>`
  }).join('')
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${body}</sheetData></worksheet>`
}

/** A workbook as the bytes of a real `.xlsx` file. */
export function xlsxOf(sheets: Sheet[]): Uint8Array<ArrayBuffer> {
  const taken = new Set<string>()
  const named = sheets.map((sheet) => ({ ...sheet, name: sheetName(sheet.name, taken) }))
  const workbookSheets = named.map((sheet, i) =>
    `<sheet name="${xmlEscape(sheet.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')
  const rels = named.map((_, i) =>
    `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('')

  const entries = [
    {
      name: '[Content_Types].xml',
      data: new TextEncoder().encode(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
        `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">` +
        `<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>` +
        `<Default Extension="xml" ContentType="application/xml"/>` +
        `<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>` +
        named.map((_, i) =>
          `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('') +
        `<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>` +
        `</Types>`),
    },
    {
      name: '_rels/.rels',
      data: new TextEncoder().encode(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
        `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
        `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>` +
        `</Relationships>`),
    },
    {
      name: 'xl/workbook.xml',
      data: new TextEncoder().encode(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
        `<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ` +
        `xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">` +
        `<sheets>${workbookSheets}</sheets></workbook>`),
    },
    {
      name: 'xl/_rels/workbook.xml.rels',
      data: new TextEncoder().encode(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
        `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${rels}` +
        `<Relationship Id="rId${named.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>` +
        `</Relationships>`),
    },
    {
      name: 'xl/styles.xml',
      data: new TextEncoder().encode(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
        `<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">` +
        `<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>` +
        `<fills count="1"><fill><patternFill patternType="none"/></fill></fills>` +
        `<borders count="1"><border/></borders>` +
        `<cellStyleXfs count="1"><xf/></cellStyleXfs>` +
        `<cellXfs count="1"><xf/></cellXfs></styleSheet>`),
    },
    ...named.map((sheet, i) => ({
      name: `xl/worksheets/sheet${i + 1}.xml`,
      data: new TextEncoder().encode(worksheetXml(sheet.rows)),
    })),
  ]
  return zipStored(entries)
}

// ── the download ─────────────────────────────────────────────────────────────

/** Hand the reader a file, the same way the report panel does. */
export function downloadFile(name: string, bytes: BlobPart, mime: string): void {
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 5000)
}

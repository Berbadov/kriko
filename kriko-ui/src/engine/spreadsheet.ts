/** Spreadsheet reader, with no dependency: CSV and a real `.xlsx` read by hand.
 *
 *  `sheet.ts` writes both formats; this module reads them, so a list the reader
 *  keeps in Excel, Numbers, LibreOffice or a supplier's export can be checked
 *  against the installed catalogs, attached to a chat or imported into an
 *  estimate. Nothing here runs a formula or opens a link: a cell is text, and a
 *  cell that starts with = + - @ comes back exactly as it was typed.
 *
 *  An `.xlsx` is a zip of XML parts. The zip directory is parsed here, entries
 *  are stored or deflated (inflated with the platform's `DecompressionStream`),
 *  and the XML is read as a stream of events, from `DOMParser` where the
 *  runtime has one and from a small tolerant scanner where it does not (Node,
 *  a worker). One handler per part serves both, so the two paths cannot drift.
 *
 *  The input is a stranger's file, so every limit is a refusal with a plain
 *  sentence, never a hang: a file over 10 MB, an entry that claims to unpack
 *  past 50 MB (or really does), a zip whose directory is cut off.
 */

export interface Table {
  name: string
  header: string[]
  rows: string[][]
  /** Same shape as `rows`: true where an xlsx cell was a number (or a date
   *  serial), false for text. Absent for CSV, where every cell is text. */
  numeric?: boolean[][]
  /** Rows past `MAX_ROWS`, counted and not kept. Absent when nothing was cut. */
  truncated?: number
}

export interface Spreadsheet {
  fileName: string
  format: 'csv' | 'xlsx'
  tables: Table[]
}

/** Rows kept per table; extra rows are counted, not kept. */
export const MAX_ROWS = 5000

const MAX_FILE_BYTES = 10 * 1024 * 1024
const MAX_ENTRY_BYTES = 50 * 1024 * 1024
const MAX_COLUMNS = 16384
const SAVE_AS = 'Save it as .xlsx or .csv and add that instead.'

// ── tables ───────────────────────────────────────────────────────────────────

const isBlank = (cells: string[]): boolean => !cells.some((cell) => cell.trim() !== '')

/** Collects rows for one table: blank rows are dropped, the first row left is
 *  the header, `MAX_ROWS` rows are kept and the rest are counted. */
class RowSink {
  private head: string[] | null = null
  private kept: string[][] = []
  private flags: boolean[][] = []
  private extra = 0
  private width = 0
  private readonly track: boolean

  constructor(track = false) { this.track = track }

  get empty(): boolean { return this.head === null }

  push(row: string[], numeric: boolean[] = []): void {
    const cells = row.length > MAX_COLUMNS ? row.slice(0, MAX_COLUMNS) : row
    if (isBlank(cells)) return
    if (!this.head) { this.head = cells; return }
    if (this.kept.length >= MAX_ROWS) { this.extra += 1; return }
    let last = cells.length
    while (last > 0 && cells[last - 1].trim() === '') last -= 1
    if (last > this.width) this.width = last
    this.kept.push(cells)
    if (this.track) this.flags.push(numeric)
  }

  table(name: string): Table {
    const head = this.head ?? []
    let headLength = head.length
    while (headLength > 0 && head[headLength - 1].trim() === '') headLength -= 1
    const width = Math.max(headLength, this.width)
    const header: string[] = []
    for (let i = 0; i < width; i += 1) header.push((head[i] ?? '').trim() || `Column ${i + 1}`)
    const rows = this.kept.map((cells) => {
      const out: string[] = new Array(width)
      for (let i = 0; i < width; i += 1) out[i] = cells[i] ?? ''
      return out
    })
    const table: Table = { name, header, rows }
    if (this.track) {
      table.numeric = this.flags.map((flags) => {
        const out: boolean[] = new Array(width)
        for (let i = 0; i < width; i += 1) out[i] = flags[i] === true
        return out
      })
    }
    if (this.extra > 0) table.truncated = this.extra
    return table
  }
}

const baseName = (fileName: string): string =>
  fileName.replace(/^.*[\\/]/, '').replace(/\.[^.]*$/, '') || 'Sheet1'

// ── CSV ──────────────────────────────────────────────────────────────────────

const DELIMITERS = [',', ';', '\t', '|']

/** The delimiter that splits the first lines the same way every time, counting
 *  outside quotes. The header line decides how many; the later lines vote. */
function detectDelimiter(text: string): string {
  const cut = text.length > 16384
  const sample = cut ? text.slice(0, 16384) : text
  const lines: number[][] = []
  let counts = DELIMITERS.map(() => 0)
  let seen = false
  let quoted = false
  const endLine = () => {
    if (seen) lines.push(counts)
    counts = DELIMITERS.map(() => 0)
    seen = false
  }
  for (let i = 0; i < sample.length && lines.length < 20; i += 1) {
    const ch = sample[i]
    if (ch === '"') { quoted = !quoted; seen = true; continue }
    if (!quoted && (ch === '\n' || ch === '\r')) { endLine(); continue }
    if (ch !== ' ') seen = true
    if (!quoted) {
      const at = DELIMITERS.indexOf(ch)
      if (at >= 0) counts[at] += 1
    }
  }
  if (!cut) endLine() // a cut sample ends mid-line, which would vote wrongly
  if (lines.length === 0) return ','
  let best = ','
  let bestScore = 0
  DELIMITERS.forEach((delimiter, at) => {
    const first = lines[0][at]
    if (first === 0) return
    const agree = lines.filter((line) => line[at] === first).length
    const score = agree * 1000 + first
    if (score > bestScore) { best = delimiter; bestScore = score }
  })
  return best
}

function csvRows(text: string, delimiter: string, sink: RowSink): void {
  const n = text.length
  let row: string[] = []
  let field = ''
  let atStart = true
  let i = 0
  const endRow = () => { row.push(field); field = ''; sink.push(row); row = [] }
  while (i < n) {
    const ch = text[i]
    if (ch === '"' && atStart) {
      // A quoted field: read to the closing quote; "" is a literal quote.
      i += 1
      for (;;) {
        const close = text.indexOf('"', i)
        if (close < 0) { field += text.slice(i); i = n; break }
        field += text.slice(i, close)
        if (text[close + 1] === '"') { field += '"'; i = close + 2; continue }
        i = close + 1
        break
      }
      atStart = false
    } else if (ch === delimiter) {
      row.push(field); field = ''
      atStart = true
      i += 1
    } else if (ch === '\n' || ch === '\r') {
      endRow()
      atStart = true
      i += ch === '\r' && text[i + 1] === '\n' ? 2 : 1
    } else {
      field += ch
      atStart = false
      i += 1
    }
  }
  if (row.length > 0 || field !== '') endRow()
}

/** RFC 4180 with the habits of real exports: a BOM, any line ending, quotes,
 *  and a delimiter (, ; tab |) found from the first lines. The first row with
 *  anything in it is the header; short rows are padded to its width. */
export function parseCsv(text: string, fileName = ''): Table {
  const body = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
  const sink = new RowSink()
  csvRows(body, detectDelimiter(body), sink)
  return sink.table(baseName(fileName))
}

// ── XML events ───────────────────────────────────────────────────────────────

const damaged = (): Error => new Error('The Excel file is damaged and could not be read. Open it in Excel, save it again as .xlsx or .csv, and add that instead.')

type Attributes = Record<string, string>

interface XmlHandler {
  open(name: string, attributes: Attributes): void
  close(name: string): void
  text(text: string): void
}

const ENTITY = /&(#x[0-9a-fA-F]+|#[0-9]+|amp|lt|gt|quot|apos);/g
const NAMED: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" }

function decodeEntities(text: string): string {
  if (!text.includes('&')) return text
  return text.replace(ENTITY, (whole, body: string) => {
    if (body[0] !== '#') return NAMED[body]
    const code = body[1] === 'x' ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10)
    try { return String.fromCodePoint(code) } catch { return whole }
  })
}

const localName = (name: string): string => name.slice(name.indexOf(':') + 1)

const ATTRIBUTE = /([^\s=]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g

function tagEvents(body: string, handler: XmlHandler): void {
  if (body[0] === '/') { handler.close(localName(body.slice(1).trim())); return }
  const selfClosing = body.endsWith('/')
  const inner = selfClosing ? body.slice(0, -1) : body
  const nameEnd = inner.search(/\s/)
  const name = localName(nameEnd < 0 ? inner : inner.slice(0, nameEnd))
  const attributes: Attributes = Object.create(null)
  if (nameEnd >= 0) {
    for (const found of inner.slice(nameEnd).matchAll(ATTRIBUTE)) {
      const key = found[1]
      if (key === 'xmlns' || key.startsWith('xmlns:')) continue
      attributes[localName(key)] = decodeEntities(found[2] ?? found[3] ?? '')
    }
  }
  handler.open(name, attributes)
  if (selfClosing) handler.close(name)
}

/** A small tolerant scanner for runtimes without `DOMParser`. Linear: it never
 *  backtracks, and a tag that never ends ends the scan. */
function scanXml(xml: string, handler: XmlHandler): void {
  const n = xml.length
  let i = 0
  while (i < n) {
    const lt = xml.indexOf('<', i)
    if (lt < 0) { handler.text(decodeEntities(xml.slice(i))); return }
    if (lt > i) handler.text(decodeEntities(xml.slice(i, lt)))
    if (xml.startsWith('<!--', lt)) {
      const end = xml.indexOf('-->', lt + 4)
      i = end < 0 ? n : end + 3
    } else if (xml.startsWith('<![CDATA[', lt)) {
      const end = xml.indexOf(']]>', lt + 9)
      handler.text(xml.slice(lt + 9, end < 0 ? n : end))
      i = end < 0 ? n : end + 3
    } else if (xml.startsWith('<?', lt)) {
      const end = xml.indexOf('?>', lt + 2)
      i = end < 0 ? n : end + 2
    } else if (xml.startsWith('<!', lt)) {
      const end = xml.indexOf('>', lt + 2)
      i = end < 0 ? n : end + 1
    } else {
      // Find the closing ">" outside quoted attribute values.
      let j = lt + 1
      let quote = ''
      while (j < n) {
        const ch = xml[j]
        if (quote) { if (ch === quote) quote = '' } else if (ch === '"' || ch === "'") quote = ch
        else if (ch === '>') break
        j += 1
      }
      if (j >= n) return
      const body = xml.slice(lt + 1, j).trim()
      if (body) tagEvents(body, handler)
      i = j + 1
    }
  }
}

/** The same events from a parsed document, walked without recursion so a
 *  hostile nesting depth cannot blow the stack. */
function walkDocument(root: Element, handler: XmlHandler): void {
  let node: Node | null = root
  while (node) {
    if (node.nodeType === 1) {
      const element = node as Element
      const attributes: Attributes = Object.create(null)
      for (const attribute of Array.from(element.attributes)) {
        if (attribute.name === 'xmlns' || attribute.name.startsWith('xmlns:')) continue
        attributes[attribute.localName || attribute.name] = attribute.value
      }
      handler.open(element.localName, attributes)
      if (element.firstChild) { node = element.firstChild; continue }
    } else if (node.nodeType === 3 || node.nodeType === 4) {
      handler.text(node.nodeValue ?? '')
    }
    while (node) {
      if (node.nodeType === 1) handler.close((node as Element).localName)
      if (node === root) { node = null; break }
      if (node.nextSibling) { node = node.nextSibling; break }
      node = node.parentNode
    }
  }
}

function readXml(xml: string, handler: XmlHandler): void {
  try {
    if (typeof DOMParser !== 'undefined') {
      let parsed: Document | null = null
      try { parsed = new DOMParser().parseFromString(xml, 'application/xml') } catch { parsed = null }
      if (parsed && parsed.documentElement && parsed.getElementsByTagName('parsererror').length === 0) {
        walkDocument(parsed.documentElement, handler)
        return
      }
    }
    scanXml(xml, handler)
  } catch {
    throw damaged()
  }
}

// ── zip ──────────────────────────────────────────────────────────────────────

interface ZipEntry {
  method: number
  compressed: number
  size: number
  offset: number
}

/** The central directory, found from the end record. Nothing is unpacked. */
function readDirectory(bytes: Uint8Array): Map<string, ZipEntry> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  if (bytes.length < 22) throw damaged()
  let end = -1
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 22 - 65535); i -= 1) {
    if (view.getUint32(i, true) === 0x06054b50) { end = i; break }
  }
  if (end < 0) throw damaged()
  const count = view.getUint16(end + 10, true)
  const directorySize = view.getUint32(end + 12, true)
  const directoryAt = view.getUint32(end + 16, true)
  if (count === 0xffff || directoryAt === 0xffffffff) throw new Error(`This Excel file is too large to read here. ${SAVE_AS}`)
  if (directoryAt + directorySize > bytes.length) throw damaged()
  const entries = new Map<string, ZipEntry>()
  const decoder = new TextDecoder()
  let at = directoryAt
  for (let k = 0; k < count; k += 1) {
    if (at + 46 > bytes.length || view.getUint32(at, true) !== 0x02014b50) throw damaged()
    const flags = view.getUint16(at + 8, true)
    const method = view.getUint16(at + 10, true)
    const compressed = view.getUint32(at + 20, true)
    const size = view.getUint32(at + 24, true)
    const nameLength = view.getUint16(at + 28, true)
    const extraLength = view.getUint16(at + 30, true)
    const commentLength = view.getUint16(at + 32, true)
    const offset = view.getUint32(at + 42, true)
    if (at + 46 + nameLength > bytes.length) throw damaged()
    if (flags & 1) throw new Error('This Excel file is password protected. Remove the password, save it as .xlsx or .csv, and add that instead.')
    if (size > MAX_ENTRY_BYTES) throw new Error(`This Excel file unpacks to more than 50 MB, which is more than Kriko reads. ${SAVE_AS}`)
    const name = decoder.decode(bytes.subarray(at + 46, at + 46 + nameLength)).replace(/\\/g, '/').replace(/^\/+/, '')
    entries.set(name, { method, compressed, size, offset })
    at += 46 + nameLength + extraLength + commentLength
  }
  return entries
}

async function inflate(data: Uint8Array, limit: number): Promise<Uint8Array> {
  if (typeof DecompressionStream === 'undefined') {
    throw new Error(`This browser cannot unpack Excel files. ${SAVE_AS}`)
  }
  const stream = new DecompressionStream('deflate-raw')
  const writer = stream.writable.getWriter()
  // The write settles when the reader does; a failure surfaces through read().
  writer.write(data as unknown as BufferSource).then(() => writer.close()).catch(() => undefined)
  const reader = stream.readable.getReader()
  const chunks: Uint8Array[] = []
  let total = 0
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      total += value.length
      if (total > limit) {
        reader.cancel().catch(() => undefined)
        writer.abort().catch(() => undefined)
        throw new Error('KrikoSheetError:size')
      }
      chunks.push(value)
    }
  } catch (error) {
    if (error instanceof Error && error.message === 'KrikoSheetError:size') {
      throw new Error(`This Excel file unpacks to more than it says it does, so it was not read. ${SAVE_AS}`)
    }
    throw damaged()
  }
  const out = new Uint8Array(total)
  let at = 0
  for (const chunk of chunks) { out.set(chunk, at); at += chunk.length }
  return out
}

async function extract(bytes: Uint8Array, entry: ZipEntry): Promise<Uint8Array> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const at = entry.offset
  if (at + 30 > bytes.length || view.getUint32(at, true) !== 0x04034b50) throw damaged()
  const start = at + 30 + view.getUint16(at + 26, true) + view.getUint16(at + 28, true)
  const end = start + entry.compressed
  if (end > bytes.length) throw damaged()
  const data = bytes.subarray(start, end)
  if (entry.method === 0) {
    if (entry.compressed !== entry.size) throw damaged()
    return data
  }
  if (entry.method === 8) return inflate(data, entry.size)
  throw new Error(`This Excel file uses a compression Kriko does not read. ${SAVE_AS}`)
}

/** An XML part as text: UTF-8 unless the byte order mark says UTF-16. */
function xmlText(bytes: Uint8Array): string {
  if (bytes[0] === 0xff && bytes[1] === 0xfe) return new TextDecoder('utf-16le').decode(bytes)
  if (bytes[0] === 0xfe && bytes[1] === 0xff) return new TextDecoder('utf-16be').decode(bytes)
  return new TextDecoder().decode(bytes)
}

// ── the workbook's parts ─────────────────────────────────────────────────────

/** Office escapes control characters in text as _x000D_. */
const unescapeOffice = (text: string): string =>
  text.includes('_x') ? text.replace(/_x([0-9A-Fa-f]{4})_/g, (_, hex: string) => String.fromCharCode(parseInt(hex, 16))) : text

function workbookParts(xml: string): { sheets: { name: string; rid: string }[]; date1904: boolean } {
  const sheets: { name: string; rid: string }[] = []
  let date1904 = false
  readXml(xml, {
    open(name, attributes) {
      if (name === 'sheet') sheets.push({ name: attributes.name ?? '', rid: attributes.id ?? '' })
      if (name === 'workbookPr') date1904 = attributes.date1904 === '1' || attributes.date1904 === 'true'
    },
    close() {},
    text() {},
  })
  return { sheets, date1904 }
}

function relationshipTargets(xml: string): Map<string, string> {
  const targets = new Map<string, string>()
  readXml(xml, {
    open(name, attributes) {
      if (name === 'Relationship' && attributes.Id) targets.set(attributes.Id, attributes.Target ?? '')
    },
    close() {},
    text() {},
  })
  return targets
}

/** A relationship target as a path inside the zip. */
function partPath(target: string): string {
  if (target.startsWith('/')) return target.replace(/^\/+/, '')
  const parts = `xl/${target}`.split('/')
  const out: string[] = []
  for (const part of parts) {
    if (part === '..') out.pop()
    else if (part !== '.' && part !== '') out.push(part)
  }
  return out.join('/')
}

/** Shared strings, rich text runs joined, phonetic hints left out. */
function sharedStringList(xml: string): string[] {
  const strings: string[] = []
  let current = ''
  let inItem = false
  let inText = false
  let phonetic = 0
  readXml(xml, {
    open(name) {
      if (name === 'si') { inItem = true; current = '' }
      else if (name === 'rPh') phonetic += 1
      else if (name === 't') inText = inItem && phonetic === 0
    },
    close(name) {
      if (name === 't') inText = false
      else if (name === 'rPh') phonetic -= 1
      else if (name === 'si') { strings.push(unescapeOffice(current)); inItem = false }
    },
    text(text) { if (inText) current += text },
  })
  return strings
}

type Kind = 'date' | 'time' | ''

/** Whether a custom number format shows a date or a time, from its code. */
function customKind(code: string): Kind {
  if (/\[(?:h+|m+|s+)\]/i.test(code)) return 'time' // elapsed time
  const bare = code
    .replace(/"[^"]*"/g, '')
    .replace(/\\./g, '')
    .replace(/\[[^\]]*\]/g, '')
    .replace(/[_*]./g, '')
    .replace(/general|standard|genel/gi, '')
    .toLowerCase()
  if (/[yd]/.test(bare)) return 'date'
  if (/[hs]/.test(bare)) return 'time'
  if (/m/.test(bare)) return 'date'
  return ''
}

function builtinKind(id: number): Kind | null {
  if ((id >= 14 && id <= 17) || id === 22) return 'date'
  if ((id >= 18 && id <= 21) || (id >= 45 && id <= 47)) return 'time'
  return id < 164 ? '' : null
}

/** The kind of every cell style, by index: `numFmts` and `cellXfs` of styles.xml. */
function styleKinds(xml: string): Kind[] {
  const codes = new Map<number, string>()
  const ids: number[] = []
  let inXfs = false
  readXml(xml, {
    open(name, attributes) {
      if (name === 'numFmt') codes.set(Number(attributes.numFmtId), attributes.formatCode ?? '')
      else if (name === 'cellXfs') inXfs = true
      else if (name === 'xf' && inXfs) ids.push(Number(attributes.numFmtId ?? 0))
    },
    close(name) { if (name === 'cellXfs') inXfs = false },
    text() {},
  })
  return ids.map((id) => builtinKind(id) ?? customKind(codes.get(id) ?? ''))
}

const two = (n: number): string => String(n).padStart(2, '0')

/** A date serial as YYYY-MM-DD, or a time-of-day as HH:MM; null when the number
 *  is not one (negative, past year 9999, or a plain 0). */
function serialText(serial: number, kind: Kind, date1904: boolean): string | null {
  if (!Number.isFinite(serial) || serial < 0 || serial > 2958465) return null
  const whole = Math.floor(serial)
  if (kind === 'time' || (kind === 'date' && whole === 0 && serial > 0)) {
    const seconds = Math.round((serial - whole) * 86400) % 86400
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = seconds % 60
    return s ? `${two(h)}:${two(m)}:${two(s)}` : `${two(h)}:${two(m)}`
  }
  if (whole === 0) return null
  // The 1900 system counts a 29 February 1900 that never happened: serials
  // before 61 sit one day further on.
  const epoch = date1904 ? Date.UTC(1904, 0, 1) : Date.UTC(1899, 11, whole < 61 ? 31 : 30)
  return new Date(epoch + whole * 86400000).toISOString().slice(0, 10)
}

/** A stored number as the text the reader sees: float noise (0.30000000000000004)
 *  is the file's, not theirs. */
function numberText(raw: string): string {
  const value = Number(raw)
  if (raw.trim() === '' || !Number.isFinite(value)) return raw.trim()
  return String(Number(value.toPrecision(15)))
}

const columnIndex = (ref: string): number => {
  let n = 0
  let i = 0
  for (; i < ref.length; i += 1) {
    const code = ref.charCodeAt(i) & 0xdf
    if (code < 65 || code > 90) break
    n = n * 26 + (code - 64)
  }
  return i === 0 || n > MAX_COLUMNS ? -1 : n - 1
}

/** One worksheet into a sink. A cell is placed by its A1 reference, so sparse
 *  rows keep their columns; a formula cell gives its stored result and is never
 *  evaluated. */
function readSheet(xml: string, shared: string[], kinds: Kind[], date1904: boolean, sink: RowSink): void {
  let row: string[] | null = null
  let numeric: boolean[] = []
  let column = -1
  let cell: { at: number; type: string; kind: Kind } | null = null
  let value = ''
  let inline = ''
  let inValue = false
  let inInline = false
  let inText = false
  let phonetic = 0

  const cellText = (type: string, kind: Kind): string => {
    switch (type) {
      case 's': return shared[Number(value)] ?? ''
      case 'inlineStr': return unescapeOffice(inline)
      case 'str':
      case 'e':
      case 'd': return unescapeOffice(value)
      case 'b': return value.trim() === '1' || value.trim().toLowerCase() === 'true' ? 'TRUE' : 'FALSE'
      default: {
        if (value.trim() === '') return ''
        if (kind) {
          const shown = serialText(Number(value), kind, date1904)
          if (shown !== null) return shown
        }
        return numberText(value)
      }
    }
  }

  readXml(xml, {
    open(name, attributes) {
      switch (name) {
        case 'row': row = []; numeric = []; column = -1; break
        case 'c': {
          column = attributes.r ? columnIndex(attributes.r) : column + 1
          if (!row) row = []
          cell = { at: column, type: attributes.t ?? 'n', kind: kinds[Number(attributes.s ?? 0)] ?? '' }
          value = ''
          inline = ''
          break
        }
        case 'v': inValue = cell !== null; break
        case 'is': inInline = cell !== null; break
        case 'rPh': phonetic += 1; break
        case 't': inText = inInline && phonetic === 0; break
      }
    },
    close(name) {
      switch (name) {
        case 'v': inValue = false; break
        case 'is': inInline = false; break
        case 't': inText = false; break
        case 'rPh': phonetic -= 1; break
        case 'c': {
          if (cell && row && cell.at >= 0) {
            while (row.length < cell.at) row.push('')
            const text = cellText(cell.type, cell.kind)
            row[cell.at] = text
            while (numeric.length <= cell.at) numeric.push(false)
            numeric[cell.at] = cell.type === 'n' && text !== ''
          }
          cell = null
          break
        }
        case 'row': sink.push(row ?? [], numeric); row = null; break
      }
    },
    text(text) {
      if (inValue) value += text
      else if (inText) inline += text
    },
  })
}

/** An `.xlsx` workbook as tables: one per worksheet in workbook order, empty
 *  sheets dropped. Rejects with a plain `Error` for anything it will not read. */
export async function parseXlsx(bytes: Uint8Array, fileName = ''): Promise<Spreadsheet> {
  const directory = readDirectory(bytes)
  const part = async (path: string): Promise<string | null> => {
    const entry = directory.get(path)
    return entry ? xmlText(await extract(bytes, entry)) : null
  }
  const workbook = await part('xl/workbook.xml')
  if (workbook === null) {
    throw new Error(`"${baseName(fileName) || 'This file'}" is not an Excel workbook. ${SAVE_AS}`)
  }
  const { sheets, date1904 } = workbookParts(workbook)
  const relationships = await part('xl/_rels/workbook.xml.rels')
  const targets = relationships === null ? new Map<string, string>() : relationshipTargets(relationships)
  const sharedXml = await part('xl/sharedStrings.xml')
  const shared = sharedXml === null ? [] : sharedStringList(sharedXml)
  const stylesXml = await part('xl/styles.xml')
  const kinds = stylesXml === null ? [] : styleKinds(stylesXml)

  const tables: Table[] = []
  for (let i = 0; i < sheets.length; i += 1) {
    const target = targets.get(sheets[i].rid)
    let path = target ? partPath(target) : ''
    if (!directory.has(path)) path = `xl/worksheets/sheet${i + 1}.xml`
    const xml = await part(path)
    if (xml === null) continue
    const sink = new RowSink(true)
    readSheet(xml, shared, kinds, date1904, sink)
    if (!sink.empty) tables.push(sink.table(sheets[i].name || `Sheet${i + 1}`))
  }
  return { fileName, format: 'xlsx', tables }
}

// ── the file ─────────────────────────────────────────────────────────────────

const startsWith = (bytes: Uint8Array, magic: number[]): boolean =>
  magic.every((byte, i) => bytes[i] === byte)

/** Text from the bytes of a CSV: UTF-8, UTF-16 with a byte order mark, or the
 *  Turkish Windows code page that Excel still writes. */
function decodeText(bytes: Uint8Array): string {
  if (bytes[0] === 0xff && bytes[1] === 0xfe) return new TextDecoder('utf-16le').decode(bytes)
  if (bytes[0] === 0xfe && bytes[1] === 0xff) return new TextDecoder('utf-16be').decode(bytes)
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    try { return new TextDecoder('windows-1254').decode(bytes) } catch { return new TextDecoder('latin1').decode(bytes) }
  }
}

/** Read a file the reader chose. Decided by its first bytes as well as its
 *  name: `PK` is a zip, so a workbook; old `.xls` and `.ods` files are refused
 *  with the way out. */
export async function readSpreadsheet(
  file: File | { name: string; arrayBuffer(): Promise<ArrayBuffer> },
): Promise<Spreadsheet> {
  const name = file.name
  const extension = /\.([^.\\/]+)$/.exec(name)?.[1]?.toLowerCase() ?? ''
  const tooBig = `"${name}" is larger than 10 MB. Save a smaller part of it as .csv or .xlsx.`
  if ('size' in file && typeof file.size === 'number' && file.size > MAX_FILE_BYTES) throw new Error(tooBig)
  if (extension === 'xls') {
    throw new Error(`"${name}" is an old Excel file (.xls). Open it in Excel and ${SAVE_AS.charAt(0).toLowerCase()}${SAVE_AS.slice(1)}`)
  }
  if (extension === 'ods') {
    throw new Error(`"${name}" is an OpenDocument file (.ods). Open it and ${SAVE_AS.charAt(0).toLowerCase()}${SAVE_AS.slice(1)}`)
  }
  const bytes = new Uint8Array(await file.arrayBuffer())
  if (bytes.length > MAX_FILE_BYTES) throw new Error(tooBig)
  if (startsWith(bytes, [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1])) {
    throw new Error(`"${name}" is an old Excel file (.xls). Open it in Excel and ${SAVE_AS.charAt(0).toLowerCase()}${SAVE_AS.slice(1)}`)
  }
  if (startsWith(bytes, [0x50, 0x4b, 0x03, 0x04])) return parseXlsx(bytes, name)
  if (extension === 'xlsx' || extension === 'xlsm') {
    throw new Error(`"${name}" is not a readable Excel workbook. ${SAVE_AS}`)
  }
  const utf16 = (bytes[0] === 0xff && bytes[1] === 0xfe) || (bytes[0] === 0xfe && bytes[1] === 0xff)
  if (!utf16 && bytes.subarray(0, 4096).includes(0)) {
    throw new Error(`"${name}" does not look like a spreadsheet. ${SAVE_AS}`)
  }
  return { fileName: name, format: 'csv', tables: [parseCsv(decodeText(bytes), name)] }
}

// ── amounts ──────────────────────────────────────────────────────────────────

const CURRENCY = /₺|€|£|(?:(?<![\p{L}])US)?\$|(?<![\p{L}])(?:TL|TRY|EUR|USD|GBP)(?![\p{L}])/giu

function currencyCode(token: string): string {
  const t = token.toUpperCase()
  if (t === '₺' || t === 'TL' || t === 'TRY') return 'TRY'
  if (t === '€' || t === 'EUR') return 'EUR'
  if (t === '£' || t === 'GBP') return 'GBP'
  return 'USD'
}

const countOf = (text: string, char: string): number => text.split(char).length - 1

/** A price as written: `1.234,56`, `1,234.56`, `1 234,56`, `12000`, `₺12.000,00`,
 *  `$1,200`, `1.200 TL`, `EUR 260`, `(1,200)`. The currency is an ISO code when
 *  a symbol or code is present, else ''. A single separator with exactly three
 *  digits after it, behind one to three digits, groups thousands (`1,234`,
 *  `1.200`); anything else is a decimal (`1,23`, `12.5`). Text that is not
 *  only a number gives null. */
export function parseAmount(
  text: string,
  options: { plain?: boolean } = {},
): { value: number; currency: string } | null {
  if (typeof text !== 'string') return null
  const found = text.match(CURRENCY)
  const currency = found ? currencyCode(found[0]) : ''
  let rest = text.replace(CURRENCY, ' ').replace(/[  ]/g, ' ').trim()
  let negative = false
  if (/^\(.*\)$/.test(rest)) { negative = true; rest = rest.slice(1, -1).trim() }
  if (/^[-−–]/.test(rest)) { negative = true; rest = rest.slice(1).trim() }
  else if (rest.startsWith('+')) rest = rest.slice(1).trim()
  if (options.plain) {
    // Machine-formatted: a dot is the decimal point, nothing groups thousands.
    if (!/^(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(rest)) return null
    const plain = Number(rest)
    return Number.isFinite(plain) ? { value: negative ? 0 - plain : plain, currency } : null
  }
  if (!/^[.,]?\d[\d.,' ’]*$/.test(rest)) return null

  let digits = rest
  if (/[ '’]/.test(rest)) {
    // Spaces and apostrophes only group thousands: 1 234 567 or 1 234,56.
    if (!/^\d{1,3}(?:[ '’]\d{3})+(?:[.,]\d+)?$/.test(rest)) return null
    digits = rest.replace(/[ '’]/g, '')
  }

  const dots = countOf(digits, '.')
  const commas = countOf(digits, ',')
  let whole = digits
  let fraction = ''
  if (dots > 0 && commas > 0) {
    const decimal = digits.lastIndexOf('.') > digits.lastIndexOf(',') ? '.' : ','
    const group = decimal === '.' ? ',' : '.'
    const at = digits.lastIndexOf(decimal)
    const head = digits.slice(0, at)
    fraction = digits.slice(at + 1)
    if (head.includes(decimal)) return null
    const grouped = new RegExp(`^\\d{1,3}(?:\\${group}\\d{3})+$`)
    if (!grouped.test(head)) return null
    whole = head.split(group).join('')
  } else if (dots > 0 || commas > 0) {
    const separator = dots > 0 ? '.' : ','
    const parts = digits.split(separator)
    if (parts.length > 2) {
      if (!new RegExp(`^\\d{1,3}(?:\\${separator}\\d{3})+$`).test(digits)) return null
      whole = parts.join('')
    } else if (parts[1].length === 3 && parts[0].length >= 1 && parts[0].length <= 3 && !parts[0].startsWith('0')) {
      whole = parts[0] + parts[1]
    } else {
      whole = parts[0] || '0'
      fraction = parts[1]
    }
  }
  const value = Number(fraction ? `${whole}.${fraction}` : whole)
  if (!Number.isFinite(value)) return null
  return { value: negative ? 0 - value : value, currency }
}

/** The amount in one cell of a table. A cell the workbook stored as a number is
 *  machine-formatted (1.234 is 1.234); any other text gets the usual reading
 *  (1.234 is 1234), and so does every CSV cell. */
export function cellAmount(table: Table, row: number, col: number): { value: number; currency: string } | null {
  const text = table.rows[row]?.[col]
  if (text === undefined) return null
  return parseAmount(text, { plain: table.numeric?.[row]?.[col] === true })
}

// ── columns ──────────────────────────────────────────────────────────────────

export type Role = 'name' | 'quantity' | 'price' | 'currency' | 'vendor' | 'url' | 'vat' | 'note' | 'sku'

/** Header words, folded (lower case, no diacritics), each with a weight. The
 *  more specific the phrase, the heavier: "vendor name" is a vendor, not a name. */
const HEADER_WORDS: Record<Role, [string, number][]> = {
  name: [
    ['product name', 4], ['item name', 4], ['urun adi', 4], ['item', 3], ['product', 3], ['model', 3],
    ['urun', 3], ['aciklama', 3], ['description', 3], ['kalem', 3], ['malzeme', 3], ['name', 2],
    ['ad', 2], ['adi', 2], ['title', 2],
  ],
  quantity: [['quantity', 4], ['qty', 4], ['adet', 4], ['miktar', 4], ['pcs', 3], ['piece', 3], ['pieces', 3], ['units', 3], ['count', 2]],
  price: [
    ['unit price', 5], ['birim fiyat', 5], ['item price', 5], ['price', 4], ['fiyat', 4], ['tutar', 3],
    ['cost', 3], ['maliyet', 3], ['bedel', 3], ['amount', 2], ['total', 1], ['toplam', 1],
  ],
  currency: [['para birimi', 5], ['currency', 4], ['doviz', 4], ['ccy', 4], ['pb', 3], ['para', 2], ['birimi', 2]],
  vendor: [
    ['supplier name', 5], ['vendor name', 5], ['vendor', 4], ['supplier', 4], ['seller', 4], ['satici', 4],
    ['tedarikci', 4], ['firma', 3], ['company', 3], ['merchant', 3], ['store', 3], ['shop', 3], ['magaza', 3],
  ],
  url: [['url', 5], ['link', 4], ['href', 3], ['website', 3], ['web', 2]],
  vat: [['vat', 5], ['kdv', 5], ['tax', 3], ['vergi', 3], ['gst', 3]],
  note: [['notes', 4], ['note', 4], ['notlar', 4], ['not', 3], ['comments', 3], ['comment', 3], ['remarks', 3], ['remark', 3], ['memo', 3]],
  sku: [
    ['stok kodu', 6], ['product code', 6], ['item code', 6], ['urun kodu', 6], ['part number', 5], ['sku', 5],
    ['mpn', 5], ['barcode', 4], ['barkod', 4], ['code', 3], ['kod', 3], ['kodu', 3], ['part no', 4],
  ],
}

const ROLES = Object.keys(HEADER_WORDS) as Role[]

const fold = (text: string): string =>
  text.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ı/g, 'i')

const wordsOf = (header: string): string[] => fold(header).split(/[^a-z0-9]+/).filter(Boolean)

/** Weight of a role for a header: the heaviest phrase it contains, and more if
 *  the header is nothing but that phrase. */
function headerScore(tokens: string[], role: Role): number {
  const whole = tokens.join(' ')
  let best = 0
  for (const [phrase, weight] of HEADER_WORDS[role]) {
    const words = phrase.split(' ')
    let at = -1
    for (let i = 0; i + words.length <= tokens.length && at < 0; i += 1) {
      if (words.every((word, k) => tokens[i + k] === word)) at = i
    }
    if (at >= 0) best = Math.max(best, weight + (whole === phrase ? 2 : 0))
  }
  return best
}

/** Which column plays which role, from the header words in English and Turkish.
 *  Each column serves one role. With no name column by header, the first column
 *  that is mostly text (not numbers) is the name. */
export function guessColumns(table: Table): Partial<Record<Role, number>> {
  const candidates: { role: Role; column: number; score: number }[] = []
  table.header.forEach((header, column) => {
    const tokens = wordsOf(header)
    ROLES.forEach((role) => {
      const score = headerScore(tokens, role)
      if (score >= 2) candidates.push({ role, column, score })
    })
  })
  candidates.sort((a, b) => b.score - a.score || a.column - b.column || ROLES.indexOf(a.role) - ROLES.indexOf(b.role))
  const guess: Partial<Record<Role, number>> = {}
  const used = new Set<number>()
  for (const { role, column } of candidates) {
    if (guess[role] !== undefined || used.has(column)) continue
    guess[role] = column
    used.add(column)
  }
  if (guess.name === undefined) {
    for (let column = 0; column < table.header.length; column += 1) {
      if (used.has(column)) continue
      let text = 0
      let filled = 0
      for (const row of table.rows.slice(0, 200)) {
        const cell = (row[column] ?? '').trim()
        if (!cell) continue
        filled += 1
        if (parseAmount(cell) === null) text += 1
      }
      if (filled > 0 && text * 2 > filled) { guess.name = column; break }
    }
  }
  return guess
}

// ── for a prompt ─────────────────────────────────────────────────────────────

const clip = (cell: string): string => {
  const flat = cell.replace(/\s+/g, ' ').replace(/\|/g, '/').trim()
  return flat.length > 80 ? `${flat.slice(0, 79)}…` : flat
}

/** A compact, pipe-separated rendering of a table for a model prompt: the
 *  header, then up to `limit` rows, then how many more there were. */
export function tableToText(table: Table, limit = 60): string {
  const shown = Math.max(0, Math.floor(limit))
  const lines = [table.header.map(clip).join(' | ')]
  for (const row of table.rows.slice(0, shown)) lines.push(row.map(clip).join(' | '))
  const more = Math.max(0, table.rows.length - shown) + (table.truncated ?? 0)
  if (more > 0) lines.push(`… ${more} more rows`)
  return lines.join('\n')
}

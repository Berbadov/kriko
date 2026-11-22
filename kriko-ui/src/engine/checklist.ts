import { post } from './api'
import type { Cell } from './sheet'
import { cellAmount, parseAmount, type Table } from './spreadsheet'
import type { EstimateLine, EstimateQuote } from './estimates'

/** Check a list: a spreadsheet's product names against the installed catalogs.
 *
 *  Everything here is plain data in and out, so it is tested without a screen.
 *  The one request goes to `POST /api/check-list`, which matches every name the
 *  way the engine does elsewhere and counts each match's claims; the rest is
 *  what the window does with the answer: the rows to send, how a row is worded,
 *  the results file, and the lines and quotes an estimate would get.
 *
 *  Nothing is guessed. A name the engine could not place on exactly one product
 *  stays unmatched until the reader chooses; a row with no price makes a line
 *  with no quote; a price with no currency takes the estimate's, and the dialog
 *  says so. */

/** One request carries at most this many names; the engine refuses more. */
export const MAX_NAMES = 300
const MAX_NAME_LENGTH = 200

// ── the rows to send ─────────────────────────────────────────────────────────

export type ColumnRole = 'name' | 'quantity' | 'price' | 'currency' | 'vendor'
/** Which column of the table plays which role (an index into `Table.header`). */
export type Mapping = Partial<Record<ColumnRole, number>>

export interface Prepared {
  /** The rows that will be checked: the row's place in the table and its name. */
  rows: { row: number; name: string }[]
  /** Rows with no name in the chosen column. */
  blank: number
  /** Rows with a name left out because a request holds at most `MAX_NAMES`. */
  cut: number
}

const flat = (text: string): string => text.replace(/\s+/g, ' ').trim()

export function prepareRows(table: Table, nameColumn: number | undefined): Prepared {
  const rows: Prepared['rows'] = []
  let blank = 0
  let cut = 0
  if (nameColumn === undefined || nameColumn < 0) return { rows, blank: table.rows.length, cut: 0 }
  table.rows.forEach((cells, row) => {
    const name = flat(cells[nameColumn] ?? '').slice(0, MAX_NAME_LENGTH)
    if (!name) { blank += 1; return }
    if (rows.length >= MAX_NAMES) { cut += 1; return }
    rows.push({ row, name })
  })
  return { rows, blank, cut: cut + (table.truncated ?? 0) }
}

// ── the engine's answer ──────────────────────────────────────────────────────

export interface Counts { total: number; serious: number; known: number; minor: number }
export interface Leading { title: string; severity: string }

export interface Candidate {
  subject_id: string
  pack_id: string
  label: string
  claims?: Counts
  leading?: Leading | null
}

export interface Match {
  subject_id: string
  pack_id: string
  label: string
  /** `exact`, `name` and `words` come from the engine; `chosen` is the reader's pick. */
  confidence: 'exact' | 'name' | 'words' | 'chosen' | string
}

export interface CheckedItem {
  index: number
  query: string
  match: Match | null
  claims: Counts
  leading: Leading | null
  others: Candidate[]
}

const NO_CLAIMS: Counts = { total: 0, serious: 0, known: 0, minor: 0 }

/** Ask the engine about every name at once. Aborting stops the wait, and where the
 *  request can be cancelled (the browser) the request itself. */
export async function checkNames(names: string[], signal?: AbortSignal): Promise<CheckedItem[]> {
  const aborted = () => new DOMException('Cancelled', 'AbortError')
  if (signal?.aborted) throw aborted()
  const answer = post<{ items: CheckedItem[] }>('/api/check-list', { names }, 90000)
  const stop = new Promise<never>((_, reject) => signal?.addEventListener('abort', () => reject(aborted()), { once: true }))
  const found = await Promise.race([answer, stop])
  answer.catch(() => undefined)
  return found.items ?? []
}

// ── a row, worded ────────────────────────────────────────────────────────────

/** What a row comes to, worst first. The words are the engine's own severity words. */
export type Level = 'serious' | 'known' | 'minor' | 'check' | 'none' | 'nomatch'

export const LEVELS: Level[] = ['serious', 'known', 'minor', 'check', 'none', 'nomatch']

export const LEVEL_WORD: Record<Level, string> = {
  serious: 'Serious',
  known: 'Known issues',
  minor: 'Minor',
  check: 'To check',
  none: 'No reports',
  nomatch: 'No match',
}

export const CONFIDENCE_WORD: Record<string, string> = {
  exact: 'Exact',
  name: 'Name found in the row',
  words: 'All words found',
  chosen: 'Chosen by you',
}

/** One checked row: what was typed, what it came to, and where it sits in the file. */
export interface Resolved {
  /** The row's place in the table (0 is the first row under the header). */
  row: number
  name: string
  match: Match | null
  claims: Counts
  leading: Leading | null
  others: Candidate[]
}

export function levelOf(item: Pick<Resolved, 'match' | 'claims'>): Level {
  if (!item.match) return 'nomatch'
  const { claims } = item
  if (claims.serious > 0) return 'serious'
  if (claims.known > 0) return 'known'
  if (claims.minor > 0) return 'minor'
  return claims.total > 0 ? 'check' : 'none'
}

/** Join the engine's answers to the rows that were sent. Answers are matched by
 *  `index`, so a missing or reordered answer never lands on the wrong row. */
export function resolveRows(prepared: Prepared, items: CheckedItem[]): Resolved[] {
  const byIndex = new Map(items.map((item) => [item.index, item]))
  return prepared.rows.map(({ row, name }, index) => {
    const found = byIndex.get(index)
    return {
      row,
      name,
      match: found?.match ?? null,
      claims: found?.claims ?? NO_CLAIMS,
      leading: found?.leading ?? null,
      others: found?.others ?? [],
    }
  })
}

/** The reader chose one of the offered products for an unmatched row. Nothing is
 *  asked of the engine: the candidate came with its own counts. */
export function chooseCandidate(item: Resolved, subjectId: string): Resolved {
  const picked = item.others.find((other) => other.subject_id === subjectId)
  if (!picked) return item
  return {
    ...item,
    match: { subject_id: picked.subject_id, pack_id: picked.pack_id, label: picked.label, confidence: 'chosen' },
    claims: picked.claims ?? NO_CLAIMS,
    leading: picked.leading ?? null,
  }
}

export interface Summary {
  rows: number
  matched: number
  serious: number
  /** Rows whose worst finding is a known issue (no serious one). */
  known: number
  nomatch: number
  byLevel: Record<Level, number>
}

export function summarize(items: Resolved[]): Summary {
  const byLevel: Record<Level, number> = { serious: 0, known: 0, minor: 0, check: 0, none: 0, nomatch: 0 }
  for (const item of items) byLevel[levelOf(item)] += 1
  return {
    rows: items.length,
    matched: items.length - byLevel.nomatch,
    serious: byLevel.serious,
    known: byLevel.known,
    nomatch: byLevel.nomatch,
    byLevel,
  }
}

export type Filter = 'all' | Level
export type Order = 'file' | 'worst' | 'best'

const weight = (item: Resolved): number => LEVELS.indexOf(levelOf(item))

/** The rows to show: filtered, then in the file's order or by severity. */
export function visibleRows(items: Resolved[], filter: Filter, order: Order): Resolved[] {
  const kept = filter === 'all' ? items : items.filter((item) => levelOf(item) === filter)
  if (order === 'file') return kept
  const sign = order === 'worst' ? 1 : -1
  return [...kept].sort((a, b) =>
    sign * (weight(a) - weight(b))
    || sign * (b.claims.serious - a.claims.serious)
    || sign * (b.claims.known - a.claims.known)
    || a.row - b.row)
}

/** "3 serious, 2 known issues, 1 minor" or the level's word when nothing is counted. */
export function countsText(item: Pick<Resolved, 'claims'>): string {
  const parts: string[] = []
  if (item.claims.serious) parts.push(`${item.claims.serious} serious`)
  if (item.claims.known) parts.push(`${item.claims.known} known`)
  if (item.claims.minor) parts.push(`${item.claims.minor} minor`)
  return parts.join(', ')
}

// ── the results file ─────────────────────────────────────────────────────────

export const RESULT_COLUMNS = ['Matched product', 'Match confidence', 'Serious', 'Known issues', 'Minor', 'Leading finding']

/** A cell that a spreadsheet program would run as a formula is written as text. Only
 *  the CSV needs this: an `.xlsx` cell is stored as a string and never evaluated. */
export function safeCsvCell(cell: Cell): Cell {
  if (typeof cell !== 'string') return cell
  const text = cell.trimStart()
  if (/^[=@\t\r]/.test(text)) return `'${cell}`
  if (/^[+-]/.test(text) && !/^[+-]?[\d.,\s]+$/.test(text)) return `'${cell}`
  return cell
}

/** The original sheet with the answer to the right of it. Rows that were not
 *  checked (no name, or over the limit) say so rather than looking checked. */
export function resultRows(table: Table, items: Resolved[], options: { csv?: boolean; nameColumn?: number } = {}): Cell[][] {
  const byRow = new Map(items.map((item) => [item.row, item]))
  const width = Math.max(table.header.length, ...table.rows.map((cells) => cells.length))
  const original = (cells: string[], row: number): Cell[] =>
    Array.from({ length: width }, (_, col) => {
      const text = cells[col] ?? ''
      const number = table.numeric?.[row]?.[col] && text !== '' ? Number(text) : NaN
      return Number.isFinite(number) ? number : text
    })
  const header: Cell[] = [...Array.from({ length: width }, (_, col) => table.header[col] ?? ''), ...RESULT_COLUMNS]
  const body = table.rows.map((cells, row): Cell[] => {
    const item = byRow.get(row)
    const typed = options.nameColumn === undefined ? '' : flat(cells[options.nameColumn] ?? '')
    let extra: Cell[]
    if (!item) {
      extra = ['', typed ? `Not checked (the limit is ${MAX_NAMES} products)` : 'No name', '', '', '', '']
    } else if (!item.match) {
      const several = item.others.length ? `Several fit: ${item.others.map((other) => other.label).join('; ')}` : 'No match'
      extra = ['', several, '', '', '', '']
    } else {
      extra = [
        item.match.label,
        CONFIDENCE_WORD[item.match.confidence] ?? item.match.confidence,
        item.claims.serious,
        item.claims.known,
        item.claims.minor,
        item.leading?.title || (levelOf(item) === 'none' ? 'No reports' : ''),
      ]
    }
    const out = [...original(cells, row), ...extra]
    return options.csv ? out.map(safeCsvCell) : out
  })
  return [options.csv ? header.map(safeCsvCell) : header, ...body]
}

// ── to an estimate ───────────────────────────────────────────────────────────

const DEFAULT_VAT_RATE = 20
const MAX_QUOTES = 20
const MAX_LINES = 200
const MAX_QUANTITY = 1_000_000
const FROM_A_LIST = 'From a list'

/** One matched row, ready to become part of a line. */
export interface AddRow {
  row: number
  subject: { subject_id: string; pack_id: string; label: string }
  quantity: number
  /** `null` when the row states no price: the line is made with no quote. */
  quote: null | { vendor: string; unit_price: number; currency: string; note: string }
}

/** A currency as written in a cell of the currency column: a symbol, a name the
 *  reader knows, or a three-letter code. An empty string when it is none of them. */
export function currencyCode(text: string): string {
  const typed = text.trim()
  if (!typed) return ''
  const known = parseAmount(`0 ${typed}`)?.currency
  if (known) return known
  return /^[A-Za-z]{3}$/.test(typed) ? typed.toUpperCase() : ''
}

/** The matched rows as they would go to an estimate. Unmatched rows are counted by the caller. */
export function addRowsOf(table: Table, mapping: Mapping, items: Resolved[], fileName = ''): AddRow[] {
  const out: AddRow[] = []
  for (const item of items) {
    if (!item.match) continue
    let quantity = 1
    if (mapping.quantity !== undefined) {
      const amount = cellAmount(table, item.row, mapping.quantity)
      if (amount && amount.value >= 1) quantity = Math.min(MAX_QUANTITY, Math.round(amount.value))
    }
    let quote: AddRow['quote'] = null
    if (mapping.price !== undefined) {
      const amount = cellAmount(table, item.row, mapping.price)
      if (amount && amount.value >= 0) {
        const own = mapping.currency !== undefined ? currencyCode(table.rows[item.row]?.[mapping.currency] ?? '') : ''
        const vendor = mapping.vendor !== undefined ? flat(table.rows[item.row]?.[mapping.vendor] ?? '').slice(0, 200) : ''
        quote = {
          vendor: vendor || FROM_A_LIST,
          unit_price: amount.value,
          currency: amount.currency || own,
          note: `${fileName ? `${fileName}, ` : ''}item ${item.row + 1}`,
        }
      }
    }
    out.push({ row: item.row, subject: { subject_id: item.match.subject_id, pack_id: item.match.pack_id, label: item.match.label }, quantity, quote })
  }
  return out
}

/** The currency most of the stated prices are in, or '' when none states one. */
export function dominantCurrency(rows: AddRow[]): string {
  const counts = new Map<string, number>()
  for (const row of rows) if (row.quote?.currency) counts.set(row.quote.currency, (counts.get(row.quote.currency) ?? 0) + 1)
  let best = ''
  let most = 0
  for (const [code, n] of counts) if (n > most) { best = code; most = n }
  return best
}

export interface EstimateBuild {
  lines: EstimateLine[]
  /** Lines made new, and existing lines that gained quotes or quantity. */
  created: number
  joined: number
  quotes: number
  /** Matched rows with no price: a line, no quote. */
  unpriced: number
  /** Quotes with no currency of their own, which take the estimate's. */
  defaulted: number
  /** Past the limits of a line or an estimate, left out. */
  droppedQuotes: number
  droppedLines: number
}

const starter = (quote: NonNullable<AddRow['quote']>, currency: string): EstimateQuote => ({
  vendor: quote.vendor,
  seller: '',
  url: '',
  unit_price: quote.unit_price,
  currency: (quote.currency || currency).toUpperCase(),
  vat_rate: DEFAULT_VAT_RATE,
  vat_included: true,
  delivery_days: null,
  warranty_months: null,
  quote_date: '',
  valid_until: '',
  note: quote.note,
  selected: false,
})

/** Exactly one quote is selected: when none is, the first one is. */
const withSelection = (quotes: EstimateQuote[]): EstimateQuote[] =>
  quotes.length === 0 || quotes.some((quote) => quote.selected)
    ? quotes
    : quotes.map((quote, index) => ({ ...quote, selected: index === 0 }))

/** The lines of an estimate after adding the rows, built to go in ONE save.
 *
 *  A line is made per product. Two rows of one product make one line: their
 *  quantities add and both quotes stay. A product already on the estimate keeps
 *  its quantity and gains the quotes, as adding a quote from anywhere else does.
 *  A quote starts with the 20% starting VAT, included in the price, the same as
 *  every other way of adding one. */
export function buildEstimateLines(rows: AddRow[], existing: EstimateLine[], currency: string): EstimateBuild {
  const lines = existing.map((line) => ({ ...line, quotes: [...(line.quotes ?? [])] }))
  const placed = new Map<string, number>(lines.map((line, at) => [line.subject_id, at]))
  const touched = new Set<number>()
  const result: EstimateBuild = { lines, created: 0, joined: 0, quotes: 0, unpriced: 0, defaulted: 0, droppedQuotes: 0, droppedLines: 0 }
  const made = new Set<number>()

  for (const row of rows) {
    if (!row.quote) result.unpriced += 1
    let at = placed.get(row.subject.subject_id)
    const isNew = at === undefined
    if (at === undefined) {
      if (lines.length >= MAX_LINES) { result.droppedLines += 1; if (row.quote) result.droppedQuotes += 1; continue }
      lines.push({
        subject_id: row.subject.subject_id,
        pack_id: row.subject.pack_id,
        label: row.subject.label,
        quantity: row.quantity,
        unit_price: null,
        note: '',
        depreciation: 'straight_line',
        life_years: null,
        salvage: null,
        vuk_rate: null,
        quotes: [],
      })
      at = lines.length - 1
      placed.set(row.subject.subject_id, at)
      made.add(at)
    } else if (made.has(at)) {
      // A second row of a product this call made: the quantities add.
      lines[at] = { ...lines[at], quantity: Math.min(MAX_QUANTITY, lines[at].quantity + row.quantity) }
    }
    if (row.quote) {
      const quotes = lines[at].quotes
      if (quotes.length >= MAX_QUOTES) result.droppedQuotes += 1
      else {
        if (!row.quote.currency) result.defaulted += 1
        quotes.push(starter(row.quote, currency))
        result.quotes += 1
      }
    }
    if (!isNew) touched.add(at)
  }

  lines.forEach((line, at) => { lines[at] = { ...line, quotes: withSelection(line.quotes) } })
  result.created = made.size
  result.joined = [...touched].filter((at) => !made.has(at)).length
  return result
}

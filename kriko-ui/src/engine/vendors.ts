import type { Estimate, EstimateQuote } from './estimates'
import { quoteViews } from './quotes'

/** The vendor scorecard: every quote the reader typed (or the engine ranked),
 *  grouped by vendor and read in counts and plain averages.
 *
 *  Nothing here scores a vendor out of ten or invents a rating. "Won" is the
 *  engine's own rank 1 among at least two comparable quotes on a line; an
 *  average uses only the quotes that state the value, so a missing delivery
 *  time is never read as zero days.
 */

/** Words that name a company's legal form. They are dropped for grouping only. */
const LEGAL_SUFFIXES = new Set([
  'ltd', 'limited', 'as', 'a', 's', 'sti', 'ltdsti', 'inc', 'incorporated', 'llc', 'corp', 'corporation',
  'co', 'gmbh', 'ag', 'ab', 'plc', 'sa', 'srl', 'bv',
])

export interface VendorStats {
  /** The most common spelling of the vendor's name among its quotes. */
  vendor: string
  quotes: number
  estimates: number
  lines: number
  /** Quotes that were the best landed cost on their line, among comparable quotes. */
  won: number
  /** Lines where this vendor had a comparable quote and at least two comparable quotes were on the line. */
  contested: number
  selected: number
  avgDeliveryDays: number | null
  avgWarrantyMonths: number | null
  expired: number
  unpriced: number
  redOrAmber: number
  /** The latest quote date as YYYY-MM-DD, or '' when no quote states one. */
  lastQuoteDate: string
  currencies: string[]
}

/** One quote of one vendor, placed on its estimate and line. */
export interface VendorQuote {
  /** The grouping key (see `vendorKey`). */
  key: string
  estimateId: string
  estimateName: string
  lineKey: string
  label: string
  quantity: number
  /** The estimate's currency: `landed` is in it. */
  currency: string
  quote: EstimateQuote
  /** Gross for one unit in the estimate currency; null when unpriced or without a rate. */
  landed: number | null
  rank: number | null
  won: boolean
  contested: boolean
  expiresInDays: number | null
}

/** Lower case, no diacritics, Turkish dotless i folded to i. Used for grouping and for search. */
export function foldText(text: string): string {
  return text
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '')
    .toLowerCase()
    .replace(/ı/g, 'i')
}

/** The grouping key for a vendor name: folded, punctuation dropped, legal suffixes removed. */
export function vendorKey(name: string): string {
  const tokens = foldText(name).split(/[^\p{L}\p{N}]+/u).filter(Boolean)
  while (tokens.length > 1 && LEGAL_SUFFIXES.has(tokens[tokens.length - 1])) tokens.pop()
  return tokens.join(' ')
}

/** The name a quote's vendor is shown under: the vendor, else the seller on the page. */
const nameOf = (quote: EstimateQuote) => (quote.vendor || '').trim() || (quote.seller || '').trim()

const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

/** Every quote of every estimate, placed on its line and read against its estimate's money.
 *  A quote with no vendor or seller name is not a vendor and is left out. */
export function vendorQuotes(estimates: Estimate[], today: Date = new Date()): VendorQuote[] {
  const rows: VendorQuote[] = []
  for (const estimate of estimates) {
    const currency = (estimate.currency || 'TRY').toUpperCase()
    const rates = estimate.fx ?? {}
    for (const [index, line] of (estimate.lines ?? []).entries()) {
      const lineKey = line.line_id || `${line.subject_id}#${index}`
      const views = quoteViews(line, currency, rates, today)
      const comparable = views.filter((view) => view.rank != null).length
      for (const view of views) {
        const key = vendorKey(nameOf(view.quote))
        if (!key) continue
        rows.push({
          key,
          estimateId: estimate.estimate_id,
          estimateName: estimate.name,
          lineKey,
          label: line.label,
          quantity: line.quantity,
          currency,
          quote: view.quote,
          landed: view.landed,
          rank: view.rank,
          won: view.rank === 1 && comparable >= 2,
          contested: view.rank != null && comparable >= 2,
          expiresInDays: view.expiresInDays,
        })
      }
    }
  }
  return rows
}

/** The display name: the most common spelling in the group, the first one seen on a tie. */
function displayName(names: string[]): string {
  const counts = new Map<string, number>()
  for (const name of names) counts.set(name, (counts.get(name) ?? 0) + 1)
  let best = names[0] ?? ''
  let bestCount = 0
  for (const [name, count] of counts) {
    if (count > bestCount) {
      best = name
      bestCount = count
    }
  }
  return best
}

const mean = (values: number[]): number | null => (values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null)

/** One row per vendor, sorted by wins, then by quote count, then by name. */
export function vendorStats(estimates: Estimate[], today: Date = new Date()): VendorStats[] {
  const groups = new Map<string, VendorQuote[]>()
  for (const row of vendorQuotes(estimates, today)) {
    const group = groups.get(row.key)
    if (group) group.push(row)
    else groups.set(row.key, [row])
  }

  const stats: VendorStats[] = []
  for (const rows of groups.values()) {
    const quotes = rows.map((row) => row.quote)
    const dates = quotes.map((quote) => (quote.quote_date || '').trim().slice(0, 10)).filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date))
    const contestedLines = new Set(rows.filter((row) => row.contested).map((row) => `${row.estimateId}\u0000${row.lineKey}`))
    stats.push({
      vendor: displayName(rows.map((row) => nameOf(row.quote))),
      quotes: rows.length,
      estimates: new Set(rows.map((row) => row.estimateId)).size,
      lines: new Set(rows.map((row) => `${row.estimateId}\u0000${row.lineKey}`)).size,
      won: rows.filter((row) => row.won).length,
      contested: contestedLines.size,
      selected: quotes.filter((quote) => quote.selected).length,
      avgDeliveryDays: mean(quotes.map((quote) => quote.delivery_days).filter(isNumber)),
      avgWarrantyMonths: mean(quotes.map((quote) => quote.warranty_months).filter(isNumber)),
      expired: rows.filter((row) => row.expiresInDays != null && row.expiresInDays < 0).length,
      unpriced: quotes.filter((quote) => quote.unit_price == null).length,
      redOrAmber: quotes.filter((quote) => quote.risk?.level === 'red' || quote.risk?.level === 'amber').length,
      lastQuoteDate: dates.sort()[dates.length - 1] ?? '',
      currencies: [...new Set(rows.map((row) => (row.quote.currency || row.currency).toUpperCase()))].sort(),
    })
  }

  return stats.sort((a, b) => b.won - a.won || b.quotes - a.quotes || a.vendor.localeCompare(b.vendor))
}

const plural = (count: number, one: string, many: string) => (count === 1 ? one : many)
const oneDecimal = (value: number) => String(Math.round(value * 10) / 10)

/** The plain sentences under a vendor's name, built from its numbers only. */
export function vendorSentences(stat: VendorStats): string[] {
  const sentences: string[] = []
  if (stat.contested > 0) {
    sentences.push(`Best landed cost on ${stat.won} of ${stat.contested} comparable ${plural(stat.contested, 'line', 'lines')}.`)
  } else {
    sentences.push('No line compares it with another quote yet.')
  }
  if (stat.avgDeliveryDays != null) {
    const days = oneDecimal(stat.avgDeliveryDays)
    sentences.push(`Delivery averages ${days} ${plural(Number(days), 'day', 'days')}.`)
  } else {
    sentences.push('No delivery time given.')
  }
  if (stat.avgWarrantyMonths != null) {
    const months = oneDecimal(stat.avgWarrantyMonths)
    sentences.push(`Warranty averages ${months} ${plural(Number(months), 'month', 'months')}.`)
  }
  if (stat.expired > 0) sentences.push(`${stat.expired} ${plural(stat.expired, 'quote', 'quotes')} expired.`)
  if (stat.redOrAmber > 0) sentences.push(`${stat.redOrAmber} ${plural(stat.redOrAmber, 'quote', 'quotes')} rated medium or high risk.`)
  if (stat.unpriced > 0) sentences.push(`${stat.unpriced} without a price.`)
  return sentences
}

/** The sentences as one paragraph. */
export function vendorSentence(stat: VendorStats): string {
  return vendorSentences(stat).join(' ')
}


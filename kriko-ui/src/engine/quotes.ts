import type { EstimateLine, EstimateQuote } from './estimates'
import { quoteMoney, type QuoteMoney, type Rates } from './money'

/** One line's quotes read against the estimate's currency and rates.
 *
 *  The money is `quoteMoney`'s, the same arithmetic the forecast uses. A quote
 *  with a price whose currency has no rate is `noRate`: it is listed, shown as
 *  uncomparable, and left out of the ranking and the verdict. A quote with no
 *  price is unpriced. Ties break on the shorter delivery, as the engine does.
 */

export const EXPIRING_DAYS = 14

/** The quote that drives the line: the selected one, else the first, else none. */
export function chosenQuote(line: EstimateLine): EstimateQuote | null {
  const quotes = line.quotes ?? []
  return quotes.find((quote) => quote.selected) ?? quotes[0] ?? null
}

export interface QuoteView {
  index: number
  quote: EstimateQuote
  selected: boolean
  read: QuoteMoney
  /** Gross for one unit in the estimate currency; null when it cannot be compared. */
  landed: number | null
  /** Has a price, but its currency has no rate to the estimate currency. */
  noRate: boolean
  /** Has no price at all. */
  unpriced: boolean
  /** 1 is the cheapest comparable quote; null when not comparable. */
  rank: number | null
  /** Whole days to `valid_until` from `today`; negative once expired; null without a date. */
  expiresInDays: number | null
}

const DAY_MS = 86_400_000

/** Whole days from `today` (local calendar day) to a YYYY-MM-DD date. */
export function daysUntil(validUntil: string, today: Date): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec((validUntil ?? '').trim())
  if (!match) return null
  const target = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) / DAY_MS
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()) / DAY_MS
  return Math.round(target - now)
}

/** The words for a validity date: "Expires in 3 days", "Expires today", "Expired". */
export function expiryWord(days: number | null): string {
  if (days == null) return 'No date'
  if (days < 0) return 'Expired'
  if (days === 0) return 'Expires today'
  return `Expires in ${days} ${days === 1 ? 'day' : 'days'}`
}

export function quoteViews(line: EstimateLine, currency: string, rates: Rates, today: Date = new Date()): QuoteView[] {
  const chosen = chosenQuote(line)
  const views: QuoteView[] = (line.quotes ?? []).map((quote, index) => {
    const read = quoteMoney(quote, currency, rates)
    const unpriced = quote.unit_price == null
    const landed = unpriced ? null : read.landed
    return {
      index,
      quote,
      selected: quote === chosen,
      read,
      landed,
      noRate: !unpriced && landed == null,
      unpriced,
      rank: null,
      expiresInDays: daysUntil(quote.valid_until, today),
    }
  })

  // The engine's ranking decides the order when it ranks every comparable quote;
  // otherwise the landed cost does, with the shorter delivery breaking ties.
  const comparable = views.filter((view) => view.landed != null)
  const engineRank = new Map<string, number>()
  for (const row of line.ranking ?? []) if (row.rank != null) engineRank.set(row.quote_id, row.rank)
  const engineOrder = comparable.length > 0 && comparable.every((view) => view.quote.quote_id != null && engineRank.has(view.quote.quote_id))
  const ordered = [...comparable].sort((a, b) => {
    if (engineOrder) {
      const byRank = engineRank.get(a.quote.quote_id!)! - engineRank.get(b.quote.quote_id!)!
      if (byRank !== 0) return byRank
    }
    if (a.landed! !== b.landed!) return a.landed! - b.landed!
    return (a.quote.delivery_days ?? Infinity) - (b.quote.delivery_days ?? Infinity)
  })
  ordered.forEach((view, at) => { view.rank = at + 1 })
  return views
}

export interface Verdict {
  best: QuoteView | null
  next: QuoteView | null
  /** Next's landed cost minus best's, when both exist and differ. */
  saving: number | null
  comparable: number
  withoutRate: number
}

export function verdictOf(views: QuoteView[]): Verdict {
  const ranked = views.filter((view) => view.rank != null).sort((a, b) => a.rank! - b.rank!)
  const best = ranked[0] ?? null
  const next = ranked[1] ?? null
  const saving = best && next && next.landed! - best.landed! > 0 ? next.landed! - best.landed! : null
  return {
    best,
    next,
    saving,
    comparable: ranked.length,
    withoutRate: views.filter((view) => view.noRate).length,
  }
}

const vendorName = (view: QuoteView) => view.quote.vendor?.trim() || 'Unnamed vendor'

/** The one-line verdict, built from the numbers only. */
export function verdictText(verdict: Verdict, currency: string): string {
  const amount = (value: number) => `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`
  // An expired quote is still the cheapest on paper; the verdict says so rather than hiding it.
  const lapsed = verdict.best && verdict.best.expiresInDays != null && verdict.best.expiresInDays < 0
    ? '. Its validity has expired'
    : ''
  if (verdict.best && verdict.saving != null) {
    return `Best landed cost: ${vendorName(verdict.best)}, saves ${amount(verdict.saving)} against the next quote${lapsed}`
  }
  if (verdict.best) {
    return `Best landed cost: ${vendorName(verdict.best)}, ${amount(verdict.best.landed!)}. No second comparable quote${lapsed}`
  }
  const why = verdict.withoutRate > 0 ? `, ${verdict.withoutRate} without a rate` : ''
  return `No comparable quotes${why}`
}

/** One line as the forecast reads it: the selected quote's gross in the estimate
 *  currency, or the legacy price on the line when it has no quote. Null when
 *  neither can be stated. */
export function lineUnitGross(line: EstimateLine, currency: string, rates: Rates): number | null {
  const quote = chosenQuote(line)
  if (!quote) return line.unit_price ?? null
  return quoteMoney(quote, currency, rates).landed
}

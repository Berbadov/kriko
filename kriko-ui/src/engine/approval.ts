import type { Estimate, EstimateLine } from './estimates'
import { chosenQuote, daysUntil, expiryWord, quoteViews, type QuoteView } from './quotes'
import { forecastOf, priceStateOf, totalsOf, type PriceState } from './scenario'
import { quoteMoney } from './money'

/** The one-page summary a manager signs: built from the same numbers the
 *  Estimate screen shows, in each quote's own currency until it is converted
 *  at a stated rate. A line with no price or no rate is said so, and counted.
 *  Nothing here invents a reason, a failure rate or a repair cost; the
 *  "why it lost" line states the landed difference and the engine's own rank
 *  reasons, and nothing else.
 */

export interface ApprovalProblem {
  severity: string
  domain: string
  title: string
}

export type RiskWordLevel = 'red' | 'amber' | 'green' | 'unknown'

/** The quote risk in the words the screen uses. */
export const RISK_WORD: Record<RiskWordLevel, string> = {
  green: 'Low',
  amber: 'Medium',
  red: 'High',
  unknown: 'Not rated',
}

const SERIOUS = ['critical', 'high']
const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'unrated', 'unknown']
const severityRank = (severity: string) => {
  const at = SEVERITY_ORDER.indexOf((severity || '').trim().toLowerCase())
  return at === -1 ? SEVERITY_ORDER.length : at
}

const pad = (value: number) => String(value).padStart(2, '0')

/** A day as the sheet prints it: YYYY-MM-DD, local calendar. */
export function isoDay(today: Date): string {
  return `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`
}

/** An amount with its currency, in the same form the screen uses. */
export function amountText(value: number, currency: string): string {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`

const sentence = (text: string) => `${text.trim().replace(/[\s.!?]+$/, '')}.`

export interface ApprovalAlternative {
  vendor: string
  state: PriceState
  /** The alternative's landed unit gross in the estimate currency; null when not comparable. */
  landed: number | null
  /** Alternative minus the selected quote, per unit, when both are comparable. */
  difference: number | null
  rank: number | null
  /** The engine's own reasons for its rank, as it wrote them. */
  reasons: string[]
  /** One sentence on why it did not win, from the numbers and the rank only. */
  summary: string
}

export interface ApprovalLine {
  key: string
  product: string
  pack: string
  quantity: number
  vendor: string
  seller: string
  state: PriceState
  unitGross: number | null
  lineGross: number | null
  unitWord: string
  lineWord: string
  delivery: string
  warranty: string
  validity: string
  validityExpired: boolean
  risk: string
  riskReasons: string[]
  alternative: ApprovalAlternative | null
  /** Quotes that are not the selected one and not shown as the alternative. */
  moreQuotes: number
  /** Serious known problems, one sentence each; null when the product's problems were never read. */
  problems: string[] | null
  /** Known problems in all, serious or not; null when not read. */
  known: number | null
}

export interface ApprovalModel {
  title: string
  date: string
  currency: string
  rates: string
  totals: { net: number; vat: number; gross: number; withoutPrice: number; withoutRate: number }
  lines: ApprovalLine[]
  forecast: {
    years: number
    maintenancePct: number
    discountPct: number
    capital: number
    maintenance: number
    depreciation: number
    npv: number
  }
}

const wordFor = (state: PriceState, landed: number | null, currency: string, times = 1) => {
  if (state === 'no_price') return 'No price'
  if (state === 'no_rate') return 'No rate'
  return landed == null ? 'No rate' : amountText(landed * times, currency)
}

function alternativeOf(
  line: EstimateLine,
  view: QuoteView | null,
  chosen: QuoteView | null,
  currency: string,
): ApprovalAlternative | null {
  if (!view) return null
  const state: PriceState = view.unpriced ? 'no_price' : view.noRate ? 'no_rate' : 'priced'
  const vendor = view.quote.vendor?.trim() || 'Unnamed vendor'
  const chosenPriced = chosen != null && chosen.landed != null
  const difference = state === 'priced' && chosenPriced ? view.landed! - chosen!.landed! : null
  const rank = view.rank
  const rankPart = rank != null ? `, ranked ${rank} by landed cost` : ''
  let summary: string
  if (state === 'no_price') {
    summary = 'No price on this quote, so it is not ranked.'
  } else if (state === 'no_rate') {
    summary = `No rate from ${view.quote.currency || currency} to ${currency}, so it cannot be compared.`
  } else if (difference == null) {
    summary = `${amountText(view.landed!, currency)} per unit landed${rankPart}.`
  } else if (difference > 0) {
    summary = `${amountText(difference, currency)} more per unit landed than the selected quote${rankPart}.`
  } else if (difference === 0) {
    summary = `The same landed cost per unit as the selected quote${rankPart}.`
  } else {
    summary = `${amountText(-difference, currency)} less per unit landed than the selected quote, but it is not the selected one${rankPart}.`
  }
  const reasons = (line.ranking ?? []).find((row) => row.quote_id === view.quote.quote_id)?.reasons ?? []
  return { vendor, state, landed: state === 'priced' ? view.landed : null, difference, rank, reasons, summary }
}

function lineOf(
  estimate: Estimate,
  line: EstimateLine,
  index: number,
  claims: ApprovalProblem[] | undefined,
  today: Date,
): ApprovalLine {
  const { currency, fx } = estimate
  const quote = chosenQuote(line)
  const views = quoteViews(line, currency, fx, today)
  const chosen = views.find((view) => view.selected) ?? null
  const state = priceStateOf(line, currency, fx)
  const landed = state === 'priced' ? quoteMoney(quote ?? { unit_price: line.unit_price }, currency, fx).landed : null
  const unitGross = state === 'priced' ? (quote ? landed : line.unit_price) : null
  const lineGross = unitGross == null ? null : unitGross * line.quantity

  const others = views.filter((view) => !view.selected)
  const nearest = [...others].sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.index - b.index)[0] ?? null

  const days = quote ? daysUntil(quote.valid_until, today) : null
  const stated = (quote?.valid_until || '').trim()
  const validity = !stated
    ? 'Not stated'
    : days == null ? stated : `${stated.slice(0, 10)} (${expiryWord(days).toLowerCase()})`

  const problems = claims === undefined
    ? null
    : [...claims]
      .filter((claim) => SERIOUS.includes((claim.severity || '').trim().toLowerCase()))
      .sort((a, b) => severityRank(a.severity) - severityRank(b.severity))
      .map((claim) => sentence(claim.title))

  return {
    key: `${index}:${line.subject_id}`,
    product: line.label,
    pack: line.pack_id,
    quantity: line.quantity,
    vendor: quote ? quote.vendor?.trim() || 'Unnamed vendor' : line.unit_price != null ? 'Migrated price' : 'No quote',
    seller: quote?.seller?.trim() || '',
    state,
    unitGross,
    lineGross,
    unitWord: wordFor(state, unitGross, currency),
    lineWord: wordFor(state, lineGross, currency),
    delivery: quote?.delivery_days != null ? plural(quote.delivery_days, 'day', 'days') : 'Not stated',
    warranty: quote?.warranty_months != null ? plural(quote.warranty_months, 'month', 'months') : 'Not stated',
    validity,
    validityExpired: days != null && days < 0,
    risk: RISK_WORD[(quote?.risk?.level ?? 'unknown') as RiskWordLevel] ?? RISK_WORD.unknown,
    riskReasons: quote?.risk?.reasons ?? [],
    alternative: alternativeOf(line, nearest, chosen, currency),
    moreQuotes: Math.max(0, others.length - (nearest ? 1 : 0)),
    problems,
    known: claims === undefined ? null : claims.length,
  }
}

/** The approval model of an estimate as it stands on screen. `claimsByLine` is keyed by
 *  subject_id; a product whose problems were never read is `undefined` and says so. */
export function buildApproval(
  estimate: Estimate,
  claimsByLine: Record<string, ApprovalProblem[] | undefined>,
  today: Date,
): ApprovalModel {
  const { currency, fx } = estimate
  const totals = totalsOf(estimate)
  const model = forecastOf({
    lines: estimate.lines,
    currency,
    fx,
    years: estimate.years,
    maintenance_pct: estimate.maintenance_pct,
    discount_pct: estimate.discount_pct,
  })
  return {
    title: (estimate.name || '').trim() || 'Untitled estimate',
    date: isoDay(today),
    currency,
    rates: fx.source === 'TCMB' ? `Central Bank bulletin of ${String(fx.date ?? '')}` : 'Typed by hand',
    totals: { net: totals.net, vat: totals.vat, gross: totals.gross, withoutPrice: totals.withoutPrice, withoutRate: totals.withoutRate },
    lines: estimate.lines.map((line, index) => lineOf(estimate, line, index, claimsByLine[line.subject_id], today)),
    forecast: {
      years: model.rows.length - 1,
      maintenancePct: estimate.maintenance_pct,
      discountPct: estimate.discount_pct,
      capital: model.capital,
      maintenance: model.maintenance,
      depreciation: model.depreciation,
      npv: model.npv,
    },
  }
}

/** The sheet as plain text, for "Copy summary". Every figure is the model's own. */
export function approvalText(model: ApprovalModel): string {
  const money = (value: number) => amountText(value, model.currency)
  const out: string[] = [
    model.title,
    `Date: ${model.date}`,
    `Currency: ${model.currency}. Rates: ${model.rates}`,
    '',
    `Net ${money(model.totals.net)}, VAT ${money(model.totals.vat)}, gross ${money(model.totals.gross)}.`,
  ]
  if (model.totals.withoutPrice > 0) out.push(`${plural(model.totals.withoutPrice, 'line', 'lines')} without a price, counted and not in the totals.`)
  if (model.totals.withoutRate > 0) out.push(`${plural(model.totals.withoutRate, 'line', 'lines')} with no rate to ${model.currency}, not converted.`)
  out.push('', 'Lines')
  for (const line of model.lines) {
    out.push(`- ${line.product} (${line.pack}), quantity ${line.quantity}`)
    out.push(`  Vendor: ${line.vendor}${line.seller ? `, seller ${line.seller}` : ''}`)
    out.push(`  Unit landed: ${line.unitWord}. Line gross: ${line.lineWord}.`)
    out.push(`  Delivery: ${line.delivery}. Warranty: ${line.warranty}. Valid until: ${line.validity}.`)
    out.push(`  Quote risk: ${line.risk}${line.riskReasons.length ? ` (${line.riskReasons.join('; ')})` : ''}`)
    if (line.alternative) out.push(`  Not chosen: ${line.alternative.vendor}. ${line.alternative.summary}`)
    if (line.moreQuotes > 0) out.push(`  ${plural(line.moreQuotes, 'other quote is', 'other quotes are')} on the estimate.`)
    if (line.problems === null) out.push('  Known problems: not read yet.')
    else if (line.problems.length === 0) out.push('  Known problems: no serious reports.')
    else for (const problem of line.problems) out.push(`  Serious: ${problem}`)
  }
  out.push(
    '',
    `Forecast over ${model.forecast.years} years: capital ${money(model.forecast.capital)}, upkeep ${money(model.forecast.maintenance)}, depreciation ${money(model.forecast.depreciation)}, present value ${money(model.forecast.npv)}.`,
    '',
    'Prepared by: ____________________   Approved by: ____________________   Date: ____________',
  )
  return out.join('\n')
}

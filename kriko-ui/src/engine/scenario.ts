import type { Estimate, EstimateLine } from './estimates'
import { forecast, vatTotals, type CostLine, type Forecast, type VatSplit } from './forecast'
import { lineUnitGross, chosenQuote } from './quotes'
import { quoteMoney, type Rates } from './money'

/** What-if arithmetic on saved estimates: a copy, and a side-by-side reading.
 *
 *  Money keeps its currency. Two estimates in different currencies are never
 *  subtracted from each other, and a line with no rate is "No rate", not a
 *  converted number. Every figure is computed from the same helpers the
 *  Estimate screen uses (`lineUnitGross`, `forecast`), so a comparison and the
 *  screen cannot disagree.
 */

/** A line's price state for its selected quote, read in the estimate currency. */
export type PriceState = 'priced' | 'no_price' | 'no_rate'

export function priceStateOf(line: EstimateLine, currency: string, rates: Rates): PriceState {
  const quote = chosenQuote(line)
  if (!quote) return line.unit_price == null ? 'no_price' : 'priced'
  if (quote.unit_price == null) return 'no_price'
  return quoteMoney(quote, currency, rates).landed == null ? 'no_rate' : 'priced'
}

export interface ForecastInput {
  lines: EstimateLine[]
  currency: string
  fx: Rates
  years: number
  maintenance_pct: number
  discount_pct: number
}

/** The cost lines the forecast reads: the selected quote's gross, with its own VAT. */
export function costLinesOf(lines: EstimateLine[], currency: string, fx: Rates): CostLine[] {
  return lines.map((line): CostLine => {
    const base = {
      quantity: line.quantity,
      depreciation: line.depreciation,
      life_years: line.life_years,
      salvage: line.salvage,
      vuk_rate: line.vuk_rate,
    }
    // A line with no quote keeps its price as typed, read as VAT-free.
    const unit = lineUnitGross(line, currency, fx)
    const quote = chosenQuote(line)
    if (!quote) return { ...base, unit_price: unit, vat_rate: 0, vat_included: false }
    return { ...base, unit_price: unit, vat_rate: quote.vat_rate, vat_included: true }
  })
}

/** The forecast of an estimate as the screen computes it. */
export function forecastOf(input: ForecastInput): Forecast {
  return forecast(costLinesOf(input.lines, input.currency, input.fx), {
    years: input.years,
    maintenance_pct: input.maintenance_pct,
    discount_pct: input.discount_pct,
  })
}

export interface EstimateTotals extends VatSplit {
  /** Lines with no price at all. */
  withoutPrice: number
  /** Lines whose quote has a price in a currency with no rate. */
  withoutRate: number
}

/** Net, VAT and gross over the priced, comparable lines, in the estimate's currency. */
export function totalsOf(estimate: Estimate): EstimateTotals {
  const { currency, fx } = estimate
  const split = vatTotals(costLinesOf(estimate.lines, currency, fx))
  let withoutPrice = 0
  let withoutRate = 0
  for (const line of estimate.lines) {
    const state = priceStateOf(line, currency, fx)
    if (state === 'no_price') withoutPrice += 1
    if (state === 'no_rate') withoutRate += 1
  }
  return { ...split, withoutPrice, withoutRate }
}

/** The payload that saves a copy: the name with "(copy)", no ids, and every quote kept.
 *  The engine assigns new line and quote ids on save; the copy never reuses them. */
export function copyPayload(estimate: Estimate): Estimate {
  const base = (estimate.name || '').trim() || 'Untitled estimate'
  return {
    ...estimate,
    estimate_id: '',
    name: `${base.slice(0, 192)} (copy)`,
    lines: estimate.lines.map((line) => ({
      ...line,
      line_id: undefined,
      ranking: undefined,
      quotes: (line.quotes ?? []).map((quote) => ({ ...quote, quote_id: '', risk: undefined })),
    })),
  }
}

// ── compare ──

export interface CompareSide {
  vendor: string
  quantity: number
  state: PriceState
  /** Gross for one unit in the estimate's currency; null when not comparable. */
  unitGross: number | null
  /** unitGross times quantity; null when not comparable. */
  lineGross: number | null
}

export type CompareStatus = 'both' | 'only_a' | 'only_b'

export interface CompareRow {
  key: string
  label: string
  status: CompareStatus
  a: CompareSide | null
  b: CompareSide | null
  /** B minus A on the line gross. Only when both are priced in the same currency. */
  difference: number | null
  /** The reason a difference is not shown, in words; empty when it is shown. */
  differenceNote: string
}

export interface CompareModel {
  a: { name: string; currency: string }
  b: { name: string; currency: string }
  sameCurrency: boolean
  rows: CompareRow[]
  totals: { a: EstimateTotals; b: EstimateTotals; difference: VatSplit | null }
}

const nameOf = (estimate: Estimate) => (estimate.name || '').trim() || 'Untitled estimate'

function sideOf(estimate: Estimate, line: EstimateLine): CompareSide {
  const quote = chosenQuote(line)
  const state = priceStateOf(line, estimate.currency, estimate.fx)
  const unitGross = state === 'priced' ? lineUnitGross(line, estimate.currency, estimate.fx) : null
  const vendor = quote
    ? (quote.vendor || '').trim() || 'Unnamed vendor'
    : line.unit_price != null ? 'Migrated price' : 'No quote'
  return {
    vendor,
    quantity: line.quantity,
    state,
    unitGross,
    lineGross: unitGross == null ? null : unitGross * line.quantity,
  }
}

/** Lines are matched by subject_id; a line left over on both sides is matched by an equal label. */
export function matchLines(a: EstimateLine[], b: EstimateLine[]): { a: EstimateLine | null; b: EstimateLine | null }[] {
  const usedB = new Set<number>()
  const pairs: { a: EstimateLine | null; b: EstimateLine | null }[] = []
  const pairedA = new Array<number | null>(a.length).fill(null)

  a.forEach((line, i) => {
    const at = b.findIndex((other, j) => !usedB.has(j) && other.subject_id === line.subject_id)
    if (at !== -1) { usedB.add(at); pairedA[i] = at }
  })
  a.forEach((line, i) => {
    if (pairedA[i] !== null) return
    const label = line.label.trim()
    if (!label) return
    const at = b.findIndex((other, j) => !usedB.has(j) && other.label.trim() === label)
    if (at !== -1) { usedB.add(at); pairedA[i] = at }
  })

  a.forEach((line, i) => {
    pairs.push({ a: line, b: pairedA[i] === null ? null : b[pairedA[i]!] })
  })
  b.forEach((line, j) => {
    if (!usedB.has(j)) pairs.push({ a: null, b: line })
  })
  return pairs
}

export function compareEstimates(a: Estimate, b: Estimate): CompareModel {
  const sameCurrency = a.currency.trim().toUpperCase() === b.currency.trim().toUpperCase()
  const rows: CompareRow[] = matchLines(a.lines, b.lines).map((pair, index) => {
    const sideA = pair.a ? sideOf(a, pair.a) : null
    const sideB = pair.b ? sideOf(b, pair.b) : null
    const status: CompareStatus = sideA && sideB ? 'both' : sideA ? 'only_a' : 'only_b'
    let difference: number | null = null
    let differenceNote = ''
    if (status === 'both') {
      if (!sameCurrency) differenceNote = 'Not comparable: the estimates are in different currencies'
      else if (sideA!.lineGross == null || sideB!.lineGross == null) differenceNote = 'Not comparable'
      else difference = sideB!.lineGross - sideA!.lineGross!
    } else if (status === 'only_a') {
      differenceNote = `Only in ${nameOf(a)}`
    } else {
      differenceNote = `Only in ${nameOf(b)}`
    }
    return {
      key: `${index}:${pair.a?.subject_id ?? pair.b?.subject_id ?? ''}`,
      label: (pair.a ?? pair.b)!.label,
      status,
      a: sideA,
      b: sideB,
      difference,
      differenceNote,
    }
  })

  const totalsA = totalsOf(a)
  const totalsB = totalsOf(b)
  const difference = sameCurrency
    ? { net: totalsB.net - totalsA.net, vat: totalsB.vat - totalsA.vat, gross: totalsB.gross - totalsA.gross }
    : null

  return {
    a: { name: nameOf(a), currency: a.currency },
    b: { name: nameOf(b), currency: b.currency },
    sameCurrency,
    rows,
    totals: { a: totalsA, b: totalsB, difference },
  }
}

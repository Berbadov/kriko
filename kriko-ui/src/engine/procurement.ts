import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Watch } from './buyer'
import { listRecentEstimates, loadEstimate, saveEstimate, selectedQuote, type Estimate, type EstimateLine, type EstimateQuote } from './estimates'
import { quoteMoney, type Rates } from './money'
import { useEngine } from './Engine'

/** Procurement across the whole app: every saved estimate read as lines, quotes
 *  and money, and the one way a screen adds a product to an estimate.
 *
 *  The arithmetic is the Estimate screen's own (`quoteMoney`, the same rates
 *  table, the same gross reading). Nothing here converts a currency without a
 *  rate, and nothing reads an unpriced line as free. A quote with no rate is
 *  uncomparable: it is counted, and it is left out of every sum.
 */

export const PROCUREMENT_CHANGED_EVENT = 'kriko:procurement-changed'

/** The estimate's currency when the reader's estimate names none (the Estimate screen's default). */
const FALLBACK_CURRENCY = 'TRY'
/** `saveEstimate`'s own default currency, used for a new estimate started from here. */
const NEW_ESTIMATE_CURRENCY = 'USD'
/** The starting VAT rate for a new quote (docs/PROCUREMENT.md). */
const DEFAULT_VAT_RATE = 20
const MAX_QUOTES = 20
const EXPIRING_WITHIN_DAYS = 14
const RECENT_ESTIMATES = 12
const CACHE_MS = 20_000

export interface ProcurementLine {
  estimateId: string
  estimateName: string
  /** The estimate's currency: every landed amount below is in it. */
  currency: string
  lineId?: string
  subjectId: string
  packId: string
  label: string
  quantity: number
  /** How many quotes the line holds. */
  quotes: number
  /** The cheapest comparable quote for ONE unit, gross. Null when none can be compared. */
  best: EstimateQuote | null
  /** Gross per unit of `best`, in the estimate currency. Null when it can't be compared. */
  bestLanded: number | null
  /** Gross per unit of the runner-up quote, in the estimate currency. */
  nextLanded: number | null
  /** `nextLanded - bestLanded` when both exist and the difference is positive. */
  saving: number | null
  /** Risk of the selected quote, the one that drives the line total. */
  risk: 'red' | 'amber' | 'green' | 'unknown'
  reasons: string[]
  /** Days from `today` to the best quote's `valid_until`; negative when expired. */
  expiresInDays: number | null
  /** The selected quote has no price, or the line has no quote. */
  unpriced: boolean
}

export interface ProcurementSummary {
  estimates: number
  lines: number
  /** Lines with at least one quote. */
  quotedLines: number
  /** Lines whose selected quote has no price (or that have no quote). */
  unpricedLines: number
  /** Lines whose selected quote has a price that cannot be converted (no rate). */
  uncomparable: number
  /** Currency of each estimate -> sum of quantity x selected quote gross. Never mixed across currencies. */
  gross: Record<string, number>
  /** Valid within 14 days, soonest first. */
  expiring: ProcurementLine[]
  /** Already expired, most recently expired first. */
  expired: ProcurementLine[]
  /** Risk red or amber, red first. */
  atRisk: ProcurementLine[]
}

// ── money ──

const currencyOf = (estimate: Estimate) => (estimate.currency || FALLBACK_CURRENCY).toUpperCase()

/** Gross per unit in the estimate currency. A quote already in that currency
 *  needs no rate; any other currency needs one, or it is uncomparable. */
function landedOf(quote: EstimateQuote, currency: string, fx: Rates): number | null {
  const read = quoteMoney(quote, currency, fx)
  if (read.landed != null) return read.landed
  if (read.gross != null && read.currency === currency) return read.gross
  return null
}

/** Quotes with a price that can be compared, cheapest first. The engine's
 *  ranking decides the order when it ranks every one of them; otherwise the
 *  local landed cost does, with the shorter delivery breaking ties. */
function comparableQuotes(line: EstimateLine, currency: string, fx: Rates): { quote: EstimateQuote; landed: number }[] {
  const rows: { quote: EstimateQuote; landed: number }[] = []
  for (const quote of line.quotes ?? []) {
    if (quote.unit_price == null) continue
    const landed = landedOf(quote, currency, fx)
    if (landed != null) rows.push({ quote, landed })
  }
  const rank = new Map<string, number>()
  for (const row of line.ranking ?? []) {
    if (row.rank != null) rank.set(row.quote_id, row.rank)
  }
  const engineOrder = rows.length > 0 && rows.every((row) => row.quote.quote_id != null && rank.has(row.quote.quote_id))
  rows.sort((a, b) => {
    if (engineOrder) {
      const byRank = rank.get(a.quote.quote_id!)! - rank.get(b.quote.quote_id!)!
      if (byRank !== 0) return byRank
    }
    if (a.landed !== b.landed) return a.landed - b.landed
    return (a.quote.delivery_days ?? Infinity) - (b.quote.delivery_days ?? Infinity)
  })
  return rows
}

// ── dates ──

const DAY_MS = 86_400_000

const isoDay = (date: Date) => {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** Whole days from `today` (local calendar day) to a YYYY-MM-DD date. */
function daysUntil(validUntil: string, today: Date): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec((validUntil ?? '').trim())
  if (!match) return null
  const target = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) / DAY_MS
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()) / DAY_MS
  return Math.round(target - now)
}

// ── lines ──

interface ReadLine {
  item: ProcurementLine
  /** Gross per unit of the selected quote in the estimate currency, or null. */
  drivingLanded: number | null
}

function readLine(estimate: Estimate, line: EstimateLine, today: Date): ReadLine {
  const currency = currencyOf(estimate)
  const fx = estimate.fx ?? {}
  const quotes = line.quotes ?? []
  const selected = selectedQuote(line)
  const priced = selected != null && selected.unit_price != null
  const drivingLanded = priced ? landedOf(selected, currency, fx) : null

  const ordered = comparableQuotes(line, currency, fx)
  const best = ordered[0] ?? null
  const next = ordered[1] ?? null
  const bestLanded = best?.landed ?? null
  const nextLanded = next?.landed ?? null
  const saving = bestLanded != null && nextLanded != null && nextLanded - bestLanded > 0 ? nextLanded - bestLanded : null

  const reasons: string[] = []
  if (selected == null) reasons.push('No quote yet')
  else if (!priced) reasons.push('No price on the selected quote')
  else if (drivingLanded == null) reasons.push(`No ${(selected.currency || currency).toUpperCase()} rate`)
  reasons.push(...(selected?.risk?.reasons ?? []))

  return {
    drivingLanded,
    item: {
      estimateId: estimate.estimate_id,
      estimateName: estimate.name,
      currency,
      lineId: line.line_id,
      subjectId: line.subject_id,
      packId: line.pack_id,
      label: line.label,
      quantity: line.quantity,
      quotes: quotes.length,
      best: best?.quote ?? null,
      bestLanded,
      nextLanded,
      saving,
      risk: selected?.risk?.level ?? 'unknown',
      reasons,
      expiresInDays: best?.quote.valid_until ? daysUntil(best.quote.valid_until, today) : null,
      unpriced: !priced,
    },
  }
}

/** Every line of one estimate as a procurement line, in line order. */
export function linesOf(estimate: Estimate, today: Date = new Date()): ProcurementLine[] {
  return (estimate.lines ?? []).map((line) => readLine(estimate, line, today).item)
}

const RISK_ORDER: Record<string, number> = { red: 0, amber: 1 }

/** The whole picture across estimates: totals per currency, and what needs the eye. */
export function summarize(estimates: Estimate[], today: Date = new Date()): ProcurementSummary {
  const summary: ProcurementSummary = {
    estimates: estimates.length,
    lines: 0,
    quotedLines: 0,
    unpricedLines: 0,
    uncomparable: 0,
    gross: {},
    expiring: [],
    expired: [],
    atRisk: [],
  }
  const all: ProcurementLine[] = []
  for (const estimate of estimates) {
    for (const line of estimate.lines ?? []) {
      const { item, drivingLanded } = readLine(estimate, line, today)
      all.push(item)
      summary.lines += 1
      if ((line.quotes ?? []).length > 0) summary.quotedLines += 1
      if (item.unpriced) {
        summary.unpricedLines += 1
      } else if (drivingLanded == null) {
        summary.uncomparable += 1
      } else {
        const amount = (Number(item.quantity) || 0) * drivingLanded
        summary.gross[item.currency] = (summary.gross[item.currency] ?? 0) + amount
      }
    }
  }
  summary.expiring = all
    .filter((item) => item.expiresInDays != null && item.expiresInDays >= 0 && item.expiresInDays <= EXPIRING_WITHIN_DAYS)
    .sort((a, b) => a.expiresInDays! - b.expiresInDays!)
  summary.expired = all
    .filter((item) => item.expiresInDays != null && item.expiresInDays < 0)
    .sort((a, b) => b.expiresInDays! - a.expiresInDays!)
  summary.atRisk = all
    .filter((item) => item.risk === 'red' || item.risk === 'amber')
    .sort((a, b) => (RISK_ORDER[a.risk] ?? 0) - (RISK_ORDER[b.risk] ?? 0))
  return summary
}

/** Every line, across all estimates, that holds this subject. */
export function findProduct(estimates: Estimate[], subjectId: string): ProcurementLine[] {
  return estimates.flatMap((estimate) => linesOf(estimate)).filter((item) => item.subjectId === subjectId)
}

// ── the hook ──

const EMPTY_SUMMARY = summarize([])
const IDLE = { loading: false, problem: '', estimates: [] as Estimate[] }

interface Recent { estimates: Estimate[]; failed: number; at: number }

let recent: Recent | null = null
let inflight: Promise<Recent> | null = null

/** The most recently updated estimates, read in full. Concurrent callers share one request. */
function fetchRecent(): Promise<Recent> {
  if (!inflight) {
    inflight = (async () => {
      // One request for the list and the newest estimates in full.
      const { items, estimates } = await listRecentEstimates(RECENT_ESTIMATES)
      const wanted = Math.min(items.length, RECENT_ESTIMATES)
      const next: Recent = { estimates, failed: Math.max(0, wanted - estimates.length), at: Date.now() }
      recent = next
      return next
    })().finally(() => { inflight = null })
  }
  return inflight
}

export function useProcurement(): {
  loading: boolean
  problem: string
  estimates: Estimate[]
  summary: ProcurementSummary
  reload: () => Promise<void>
} {
  const { mode } = useEngine()
  const live = mode === 'live'
  const [state, setState] = useState<{ loading: boolean; problem: string; estimates: Estimate[] }>(() => ({
    loading: live,
    problem: '',
    estimates: [],
  }))
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  const run = useCallback(async (force: boolean) => {
    if (!live) return
    if (!force && recent && Date.now() - recent.at < CACHE_MS) {
      setState({ loading: false, problem: recent.failed ? `${recent.failed} saved estimate(s) could not be read.` : '', estimates: recent.estimates })
      return
    }
    setState((current) => ({ ...current, loading: true }))
    try {
      const result = await fetchRecent()
      if (alive.current) {
        setState({
          loading: false,
          problem: result.failed ? `${result.failed} saved estimate(s) could not be read.` : '',
          estimates: result.estimates,
        })
      }
    } catch (error) {
      if (alive.current) {
        setState((current) => ({
          loading: false,
          problem: error instanceof Error ? error.message : 'Could not read the saved estimates.',
          estimates: current.estimates,
        }))
      }
    }
  }, [live])

  useEffect(() => {
    // Read after the effect returns: a cache hit sets state, and an effect body should not.
    queueMicrotask(() => { void run(false) })
  }, [run])

  useEffect(() => {
    const changed = () => { void run(true) }
    window.addEventListener(PROCUREMENT_CHANGED_EVENT, changed)
    return () => window.removeEventListener(PROCUREMENT_CHANGED_EVENT, changed)
  }, [run])

  // Outside the live engine there is nothing to read: the empty answer is derived here, not stored.
  const view = live ? state : IDLE
  const summary = useMemo(() => (view.estimates.length ? summarize(view.estimates) : EMPTY_SUMMARY), [view.estimates])
  const reload = useCallback(() => run(true), [run])

  return { loading: view.loading, problem: view.problem, estimates: view.estimates, summary, reload }
}

// ── adding to an estimate ──

function starterQuote(input: Partial<EstimateQuote> | undefined, currency: string): EstimateQuote {
  return {
    vendor: input?.vendor ?? '',
    seller: input?.seller ?? '',
    url: input?.url ?? '',
    unit_price: input?.unit_price ?? null,
    currency: (input?.currency || currency).toUpperCase(),
    vat_rate: input?.vat_rate ?? DEFAULT_VAT_RATE,
    vat_included: input?.vat_included ?? true,
    delivery_days: input?.delivery_days ?? null,
    warranty_months: input?.warranty_months ?? null,
    quote_date: input?.quote_date ?? '',
    valid_until: input?.valid_until ?? '',
    note: input?.note ?? '',
    selected: false,
  }
}

/** Exactly one quote is selected: when none is, the first one is. */
function withSelection(quotes: EstimateQuote[]): EstimateQuote[] {
  if (quotes.length === 0 || quotes.some((quote) => quote.selected)) return quotes
  return quotes.map((quote, index) => ({ ...quote, selected: index === 0 }))
}

/** Add a subject to an estimate, or to a new one. A subject already on the
 *  estimate gets the quote added to its line. The estimate is saved, and every
 *  mounted screen is told to reload. */
export async function addToEstimate(args: {
  estimateId?: string
  newName?: string
  subject: { subject_id: string; pack_id: string; label: string }
  quote?: Partial<EstimateQuote>
  quantity?: number
}): Promise<Estimate> {
  const existing = args.estimateId ? await loadEstimate(args.estimateId) : null
  const newName = args.newName?.trim() ?? ''
  if (!existing && !newName) throw new Error('Choose an estimate, or name a new one.')
  const currency = existing ? currencyOf(existing) : NEW_ESTIMATE_CURRENCY
  const { subject } = args

  const lines: EstimateLine[] = [...(existing?.lines ?? [])]
  const at = lines.findIndex((line) => line.subject_id === subject.subject_id)
  if (at >= 0) {
    const line = lines[at]
    if (args.quote) {
      const quotes = line.quotes ?? []
      if (quotes.length >= MAX_QUOTES) throw new Error(`A line holds at most ${MAX_QUOTES} quotes.`)
      lines[at] = { ...line, quotes: withSelection([...quotes, starterQuote(args.quote, currency)]) }
    }
  } else {
    lines.push({
      subject_id: subject.subject_id,
      pack_id: subject.pack_id,
      label: subject.label,
      quantity: args.quantity ?? 1,
      unit_price: null,
      note: '',
      depreciation: 'straight_line',
      life_years: null,
      salvage: null,
      vuk_rate: null,
      quotes: args.quote ? withSelection([starterQuote(args.quote, currency)]) : [],
    })
  }

  const saved = existing
    ? await saveEstimate({
      estimate_id: existing.estimate_id,
      name: existing.name,
      currency: existing.currency,
      years: existing.years,
      maintenance_pct: existing.maintenance_pct,
      discount_pct: existing.discount_pct,
      vat_rate: existing.vat_rate,
      fx: existing.fx,
      lines,
    })
    : await saveEstimate({ name: newName, lines })

  recent = null
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(PROCUREMENT_CHANGED_EVENT))
  return saved
}

/** A watched product's price as a quote on an estimate. */
export function quoteFromWatch(watch: Watch): Partial<EstimateQuote> {
  let vendor = ''
  try {
    vendor = new URL(watch.url).hostname.replace(/^www\./, '')
  } catch {
    vendor = ''
  }
  const quote: Partial<EstimateQuote> = {
    vendor,
    url: watch.url,
    unit_price: watch.last_price ?? null,
    quote_date: isoDay(new Date()),
    note: 'From a watched price',
  }
  if (watch.currency) quote.currency = watch.currency
  return quote
}

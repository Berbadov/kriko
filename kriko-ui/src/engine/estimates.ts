import { useCallback, useEffect, useRef, useState } from 'react'
import { del, get, post, seg } from './api'
import { useEngine } from './Engine'

/** Saved cost estimates (`/api/estimates`): the Estimate screen's persistence.
 *  An estimate is the reader's own decision record - which equipment, how
 *  many, at what price, over how many years - kept in the app's state file and
 *  exported to Excel/CSV from exactly this payload. */

export interface EstimateQuote {
  quote_id?: string
  vendor: string
  seller: string
  url: string
  unit_price: number | null
  currency: string
  vat_rate: number
  vat_included: boolean
  delivery_days: number | null
  warranty_months: number | null
  quote_date: string
  valid_until: string
  note: string
  selected: boolean
  /** Computed on read by the engine; never sent on save. */
  risk?: { level: 'red' | 'amber' | 'green' | 'unknown'; reasons: string[] }
}

export interface EstimateLine {
  line_id?: string
  subject_id: string
  pack_id: string
  label: string
  quantity: number
  unit_price: number | null
  note: string
  depreciation: string
  life_years: number | null
  salvage: number | null
  vuk_rate: number | null
  quotes: EstimateQuote[]
  /** Computed on read: the quotes in landed-cost order, with reasons. */
  ranking?: EstimateRanking[]
}

export function selectedQuote(line: EstimateLine): EstimateQuote | null {
  const quotes = line.quotes ?? []
  return quotes.find((quote) => quote.selected) ?? quotes[0] ?? null
}

export interface EstimateRanking {
  quote_id: string
  rank: number | null
  landed: number | null
  reasons: string[]
}

export interface Estimate {
  estimate_id: string
  name: string
  currency: string
  years: number
  maintenance_pct: number
  discount_pct: number
  vat_rate: number
  fx: Record<string, number | string>
  created_at: string
  updated_at: string
  lines: EstimateLine[]
  /** On list rows only: how many lines the estimate holds. */
  lines_count?: number
}

export interface EstimateSummary extends Omit<Estimate, 'lines'> {
  lines: number
}

export async function listEstimates(): Promise<EstimateSummary[]> {
  const data = await get<{ items: EstimateSummary[] }>('/api/estimates?limit=100')
  return data.items ?? []
}

export async function loadEstimate(id: string): Promise<Estimate> {
  const data = await get<{ estimate: Estimate }>(`/api/estimates/${seg(id)}`)
  return data.estimate
}

const quotePayload = (quote: EstimateQuote) => ({
  quote_id: quote.quote_id ?? '',
  vendor: quote.vendor,
  seller: quote.seller,
  url: quote.url,
  unit_price: quote.unit_price,
  currency: quote.currency,
  vat_rate: quote.vat_rate,
  vat_included: quote.vat_included,
  delivery_days: quote.delivery_days,
  warranty_months: quote.warranty_months,
  quote_date: quote.quote_date,
  valid_until: quote.valid_until,
  note: quote.note,
  selected: quote.selected,
})

export async function saveEstimate(estimate: Partial<Estimate> & { lines: EstimateLine[] }): Promise<Estimate> {
  const data = await post<{ estimate: Estimate }>('/api/estimates', {
    estimate_id: estimate.estimate_id ?? '',
    name: estimate.name ?? '',
    currency: estimate.currency ?? 'USD',
    years: estimate.years ?? 5,
    maintenance_pct: estimate.maintenance_pct ?? 5,
    discount_pct: estimate.discount_pct ?? 8,
    vat_rate: estimate.vat_rate ?? 20,
    fx: estimate.fx ?? {},
    lines: estimate.lines.map((line) => ({
      subject_id: line.subject_id,
      pack_id: line.pack_id,
      label: line.label,
      quantity: line.quantity,
      unit_price: line.unit_price,
      note: line.note,
      depreciation: line.depreciation,
      life_years: line.life_years,
      salvage: line.salvage,
      vuk_rate: line.vuk_rate,
      quotes: (line.quotes ?? []).map(quotePayload),
    })),
  })
  return data.estimate
}

export async function deleteEstimate(id: string): Promise<void> {
  await del(`/api/estimates/${seg(id)}`)
}

/** Today's reference rates from TCMB, on the reader's press only. */
export async function fetchTcmbRates(): Promise<{ base: string; date: string; rates: Record<string, number>; source: string }> {
  return get('/api/fx/tcmb')
}

/** The saved estimates list, for the screen's load menu. */
export function useEstimates() {
  const { mode } = useEngine()
  const [items, setItems] = useState<EstimateSummary[] | null>(null)
  const [problem, setProblem] = useState('')
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  const reload = useCallback(async () => {
    if (mode !== 'live') {
      setItems(null)
      setProblem('')
      return
    }
    try {
      const listed = await listEstimates()
      if (alive.current) {
        setItems(listed)
        setProblem('')
      }
    } catch (error) {
      if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not read the saved estimates.')
    }
  }, [mode])

  useEffect(() => {
    void reload()
  }, [reload])

  return { items, problem, reload }
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { del, get, post, seg } from './api'
import { useEngine } from './Engine'

/** Saved cost estimates (`/api/estimates`): the Estimate screen's persistence.
 *  An estimate is the reader's own decision record — which equipment, how
 *  many, at what price, over how many years — kept in the app's state file and
 *  exported to Excel/CSV from exactly this payload. */

export interface EstimateLine {
  line_id?: string
  subject_id: string
  pack_id: string
  label: string
  quantity: number
  unit_price: number | null
  note: string
}

export interface Estimate {
  estimate_id: string
  name: string
  currency: string
  years: number
  maintenance_pct: number
  discount_pct: number
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

export async function saveEstimate(estimate: Partial<Estimate> & { lines: EstimateLine[] }): Promise<Estimate> {
  const data = await post<{ estimate: Estimate }>('/api/estimates', {
    estimate_id: estimate.estimate_id ?? '',
    name: estimate.name ?? '',
    currency: estimate.currency ?? 'USD',
    years: estimate.years ?? 5,
    maintenance_pct: estimate.maintenance_pct ?? 5,
    discount_pct: estimate.discount_pct ?? 8,
    lines: estimate.lines.map((line) => ({
      subject_id: line.subject_id,
      pack_id: line.pack_id,
      label: line.label,
      quantity: line.quantity,
      unit_price: line.unit_price,
      note: line.note,
    })),
  })
  return data.estimate
}

export async function deleteEstimate(id: string): Promise<void> {
  await del(`/api/estimates/${seg(id)}`)
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

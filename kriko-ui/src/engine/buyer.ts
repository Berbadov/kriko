import { useCallback, useEffect, useState } from 'react'
import { del, EngineError, get, post, put, seg } from './api'
import { useEngine } from './Engine'
import { followJob } from './jobs'

/** The reader as a buyer: what they need, what they bought and how it went, the
 *  pages they watch, and what Kriko keeps. All of it lives in a file on this
 *  computer, and none of it works without the engine. */

export const PRIORITIES = ['price', 'quality', 'durability', 'repairability', 'support'] as const
export type Priority = (typeof PRIORITIES)[number]

export interface BuyerProfile {
  about: string
  budget: { max: number | null; currency: string; note: string }
  must: string[]
  avoid: string[]
  prefer: string[]
  distrust: string[]
  priorities: Partial<Record<Priority, number>>
}

export interface Purchase {
  purchase_id: string
  name: string
  url: string
  price: number | null
  currency: string
  bought_at: string
  verdict: '' | 'glad' | 'fine' | 'regret'
  reason: string
}

export interface Tally {
  glad: number
  fine: number
  regret: number
  waiting: number
  answered: number
}

export interface PickRecord {
  picks: number
  followed_and_answered: number
  held_up: number
  regretted: number
  rate: number | null
  note: string
}

export interface Watch {
  watch_id: string
  url: string
  name: string
  currency: string
  target: number | null
  started_price: number | null
  last_price: number | null
  last_checked: string
  last_error: string
}

export interface PriceAlert {
  alert_id: string
  name: string
  url: string
  price: number
  currency: string
  was_price: number | null
}

export interface Holdings {
  profile: number
  purchases: number
  prices: number
  watches: number
  picks: number
  prices_since: string
  where: string
  note: string
  labels: Record<string, string>
}

export interface PickEntry {
  lookup_id: string
  name: string
  url: string
  price: number | null
  currency: string
  score: number
  strengths: string[]
  concerns: string[]
  breaks: string[]
}

export interface Pick {
  ranked: PickEntry[]
  picked: PickEntry | null
  confidence: 'clear' | 'close' | 'toss_up' | 'thin' | ''
  gave_up: string[]
  switch_if: string[]
  check_first: string[]
  profile_used: boolean
}

export type AdviceMode = 'pick' | 'debate' | 'tco' | 'timing'

const reasonOf = (error: unknown, fallback: string) => (error instanceof EngineError ? error.message : fallback)

/** Load a thing from the engine when it is live, and say why when it is not. */
function useLive<T>(path: string, empty: T) {
  const { mode } = useEngine()
  const [value, setValue] = useState<T>(empty)
  const [ready, setReady] = useState(false)
  const [problem, setProblem] = useState('')

  const reload = useCallback(async () => {
    if (mode !== 'live') return
    try {
      setValue(await get<T>(path))
      setProblem('')
    } catch (error) {
      setProblem(reasonOf(error, 'Could not read it.'))
    } finally {
      setReady(true)
    }
  }, [mode, path])

  useEffect(() => {
    void reload()
  }, [reload])

  return { value, setValue, ready, problem, setProblem, reload, live: mode === 'live', checking: mode === 'checking' }
}

const EMPTY_PROFILE: BuyerProfile = { about: '', budget: { max: null, currency: '', note: '' }, must: [], avoid: [], prefer: [], distrust: [], priorities: {} }

export function useBuyerProfile() {
  const { value, setValue, ready, problem, setProblem, reload, live, checking } = useLive<{ profile: BuyerProfile; empty: boolean }>('/api/buyer/profile', { profile: EMPTY_PROFILE, empty: true })
  const [saved, setSaved] = useState(false)

  const save = useCallback(
    async (profile: BuyerProfile) => {
      setSaved(false)
      try {
        const reply = await put<{ profile: BuyerProfile; empty: boolean }>('/api/buyer/profile', profile)
        setValue(reply)
        setProblem('')
        setSaved(true)
      } catch (error) {
        setProblem(reasonOf(error, 'Could not save it.'))
      }
    },
    [setValue, setProblem],
  )

  return { profile: value.profile, empty: value.empty, ready, problem, saved, save, reload, live, checking }
}

export function useLedger() {
  const { value, setValue, ready, problem, setProblem, reload, live } = useLive<{ items: Purchase[]; due: Purchase[]; tally: Tally; record: PickRecord | null }>('/api/buyer/purchases', {
    items: [],
    due: [],
    tally: { glad: 0, fine: 0, regret: 0, waiting: 0, answered: 0 },
    record: null,
  })

  const run = useCallback(
    async (act: () => Promise<unknown>, failed: string) => {
      try {
        await act()
        await reload()
      } catch (error) {
        setProblem(reasonOf(error, failed))
      }
    },
    [reload, setProblem],
  )

  const add = useCallback((name: string, price: string, currency: string) => run(() => post('/api/buyer/purchases', { name, price: price || null, currency }), 'Could not note it.'), [run])
  const answer = useCallback((id: string, verdict: 'glad' | 'fine' | 'regret', reason = '') => run(() => post(`/api/buyer/purchases/${seg(id)}/answer`, { verdict, reason }), 'Could not save the answer.'), [run])
  const snooze = useCallback((id: string) => run(() => post(`/api/buyer/purchases/${seg(id)}/snooze`), 'Could not ask later.'), [run])
  const forget = useCallback((id: string) => run(() => del(`/api/buyer/purchases/${seg(id)}`), 'Could not delete it.'), [run])

  return { items: value.items, due: value.due, tally: value.tally, record: value.record, ready, problem, add, answer, snooze, forget, reload, live, setValue }
}

export function useWatches() {
  const { value, ready, problem, setProblem, reload, live } = useLive<{ items: Watch[]; alerts: PriceAlert[] }>('/api/prices/watches', { items: [], alerts: [] })

  const stop = useCallback(
    async (id: string) => {
      try {
        await del(`/api/prices/watches/${seg(id)}`)
        await reload()
      } catch (error) {
        setProblem(reasonOf(error, 'Could not stop watching.'))
      }
    },
    [reload, setProblem],
  )
  const read = useCallback(async () => {
    try {
      await post('/api/prices/alerts/read', { ids: [] })
      await reload()
    } catch (error) {
      setProblem(reasonOf(error, 'Could not clear them.'))
    }
  }, [reload, setProblem])

  return { watches: value.items, alerts: value.alerts, ready, problem, stop, read, reload, live }
}

export function useHoldings() {
  const { value, ready, problem, setProblem, reload, live } = useLive<Holdings | null>('/api/buyer/privacy', null)

  const forget = useCallback(
    async (what: string) => {
      try {
        await del(`/api/buyer/privacy/${seg(what)}`)
        await reload()
      } catch (error) {
        setProblem(reasonOf(error, 'Could not forget it.'))
      }
    },
    [reload, setProblem],
  )

  return { holdings: value, ready, problem, forget, live, reload }
}

/** The shortlist ranked for this reader, with no agent in the way. */
export const decide = (lookupIds: string[]) => post<Pick>('/api/buyer/pick', { lookup_ids: lookupIds })

/** The agent says the decision well (or debates it, costs it, times it). Returns its words. */
export async function advise(mode: AdviceMode, lookupIds: string[], onWait: (message: string) => void, wanted: () => boolean): Promise<string> {
  const started = await post<{ job_id: string }>('/api/buyer/advice', { mode, lookup_ids: lookupIds })
  const ended = await followJob(started.job_id, (reading) => onWait(reading.message ?? 'Your agent is working.'), wanted)
  if (!ended) return ''
  if (ended.state !== 'succeeded') throw new EngineError(0, ended.message || 'The agent did not finish. Try again.')
  return (ended.result as { answer?: string } | null)?.answer ?? ''
}

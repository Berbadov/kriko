import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import { useEngine } from './engine/Engine'
import { del, EngineError, get, patch, post, seg, type ApiJob, type ApiQueue, type ApiQueueItem, type ApiTarget } from './engine/api'

/** The research queue. The extension queues products. This window researches
 *  them, as many at once as the reader allows, and tells the engine how each
 *  one goes. In demo mode the items move by themselves. */

export type QueueState = 'waiting' | 'researching' | 'paused' | 'done'

export interface QueueItem {
  id: string
  name: string
  agent: string
  state: QueueState
  progress: number
  line: string
  /** Why the product was passed over. A waiting product with a note needs a retry. */
  note?: string
  /** The saved check, once the product is done. */
  lookupId?: string
}

interface Queue {
  items: QueueItem[]
  active: number
  /** The product that finished last, so Compare can take its new check. `n` counts up. */
  lastDone: { n: number; lookupId: string; name: string } | null
  /** Whether this window is researching. It starts when the reader says so and stops when nothing is left. */
  running: boolean
  start: () => void
  stop: () => void
  setItems: Dispatch<SetStateAction<QueueItem[]>>
  toggle: (id: string) => void
  cancel: (id: string) => void
  add: (name: string) => void
}

const Ctx = createContext<Queue | null>(null)

const noop = () => undefined

// ---- demo ----

const SEED: QueueItem[] = [
  { id: 'q1', name: 'Alpha Unit 200', agent: 'Default agent', state: 'researching', progress: 0.42, line: 'Read page' },
  { id: 'q2', name: 'Gamma Unit 400', agent: 'Default agent', state: 'researching', progress: 0.12, line: 'Web search' },
  { id: 'q3', name: 'Kingston A400 480 GB', agent: 'Coding agent', state: 'waiting', progress: 0, line: 'Waits' },
  { id: 'q4', name: 'Combi boiler 30 kW', agent: 'Local model', state: 'waiting', progress: 0, line: 'Waits' },
]

const LINES = ['Catalog lookup', 'Web search', 'Read page', 'Check quote']
const SLOTS = 2

function useDemoQueue(enabled: boolean): Queue {
  const [items, setItems] = useState<QueueItem[]>(enabled ? SEED : [])
  const [lastDone, setLastDone] = useState<Queue['lastDone']>(null)
  const seen = useRef(new Set<string>())

  useEffect(() => {
    if (!enabled) return
    const timer = window.setInterval(() => {
      setItems((list) => {
        let running = list.filter((i) => i.state === 'researching').length
        return list.map((item) => {
          if (item.state === 'researching') {
            const progress = Math.min(1, item.progress + 0.012 + Math.random() * 0.02)
            if (progress >= 1) return { ...item, progress: 1, state: 'done', line: 'Done' }
            return { ...item, progress, line: LINES[Math.min(3, Math.floor(progress * 4))] }
          }
          if (item.state === 'waiting' && running < SLOTS) {
            running += 1
            return { ...item, state: 'researching', line: LINES[0] }
          }
          return item
        })
      })
    }, 700)
    return () => window.clearInterval(timer)
  }, [enabled])

  // A product that finishes in the demo hands Compare a check named after it.
  useEffect(() => {
    for (const item of items) {
      if (item.state === 'done' && !seen.current.has(item.id)) {
        seen.current.add(item.id)
        setLastDone((last) => ({ n: (last?.n ?? 0) + 1, lookupId: `demo:${item.name}`, name: item.name }))
      }
    }
  }, [items])

  const toggle = useCallback((id: string) => {
    setItems((list) =>
      list.map((i) =>
        i.id !== id
          ? i
          : i.state === 'researching'
            ? { ...i, state: 'paused', line: 'Paused' }
            : i.state === 'paused'
              ? { ...i, state: 'waiting', line: 'Waits' }
              : i,
      ),
    )
  }, [])
  const cancel = useCallback((id: string) => setItems((list) => list.filter((i) => i.id !== id)), [])
  const add = useCallback(
    (name: string) =>
      setItems((list) => [...list, { id: `q${Date.now()}`, name, agent: 'Default agent', state: 'waiting', progress: 0, line: 'Waits' }]),
    [],
  )

  return useMemo(
    () => ({ items, active: items.filter((i) => i.state !== 'done').length, running: true, start: noop, stop: noop, lastDone, setItems, toggle, cancel, add }),
    [items, lastDone, toggle, cancel, add],
  )
}

// ---- live ----

const POLL_MS = 700
const REFRESH_MS = 4000
const NOT_IN_CATALOGS = 'not in your catalogs'

/** One research that this window runs. */
interface Worker {
  cancelled: boolean
  /** The reader removed the row: the engine has none to update. */
  removed: boolean
  job: string
}

const host = (url: string) => {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

const sleep = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms))

function lineOf(job: ApiJob): string {
  const last = job.feed?.length ? job.feed[job.feed.length - 1].text : ''
  return last || job.message || 'Starts'
}

const reasonOf = (error: unknown) => (error instanceof EngineError ? error.message : 'The engine does not answer.')

function useLiveQueue(enabled: boolean): Queue {
  const { agents, preferred } = useEngine()
  const agentLabel = agents.find((a) => a.id === preferred)?.label ?? 'Default agent'
  const harness = preferred

  const [items, setItems] = useState<QueueItem[]>([])
  const [limit, setLimit] = useState(1)
  const [lastDone, setLastDone] = useState<Queue['lastDone']>(null)
  const workers = useRef(new Map<string, Worker>())
  const held = useRef(new Set<string>())
  const [running, setRunning] = useState(false)
  /** The address each row was queued from. The list view does not carry it. */
  const urls = useRef(new Map<string, string>())
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const update = useCallback((id: string, change: Partial<QueueItem>) => {
    if (!alive.current) return
    setItems((list) => list.map((i) => (i.id === id ? { ...i, ...change } : i)))
  }, [])

  /** The engine's list, merged with what this window knows of the runs in flight. */
  const refresh = useCallback(async () => {
    try {
      const reply = await get<ApiQueue>('/api/queue', 5000)
      if (!alive.current) return
      setLimit(Math.max(1, reply.concurrency ?? 1))
      for (const row of items_of(reply)) urls.current.set(row.queue_id, row.url)
      setItems((prev) => {
        const byId = new Map(prev.map((i) => [i.id, i]))
        const fromServer = (row: ApiQueueItem): QueueItem => {
          const old = byId.get(row.queue_id)
          const mine = workers.current.has(row.queue_id)
          const name = row.name && row.name !== row.url ? row.name : host(row.url)
          const base = { id: row.queue_id, name, agent: old?.agent ?? agentLabel, lookupId: row.lookup_id || undefined }
          if (row.state === 'done') return { ...base, state: 'done', progress: 1, line: 'Done' }
          if (row.state === 'researching')
            return mine && old ? { ...old, ...base } : { ...base, state: 'researching', progress: old?.progress ?? 0, line: old?.line ?? 'In another window' }
          if (held.current.has(row.queue_id)) return { ...base, state: 'paused', progress: old?.progress ?? 0, line: 'Paused' }
          if (row.note) return { ...base, state: 'waiting', progress: 0, line: row.note, note: row.note }
          return { ...base, state: 'waiting', progress: 0, line: 'Waits' }
        }
        const next = new Map(items_of(reply).map((row) => [row.queue_id, fromServer(row)]))
        // The order the reader set stays. New rows go to the end.
        const kept = prev.filter((i) => next.has(i.id)).map((i) => next.get(i.id)!)
        const fresh = [...next.values()].filter((i) => !byId.has(i.id))
        return [...kept, ...fresh]
      })
    } catch {
      /* The engine will answer on the next turn. */
    }
  }, [agentLabel])

  useEffect(() => {
    if (!enabled) return
    void refresh()
    const timer = window.setInterval(() => void refresh(), REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [enabled, refresh])

  /** Put a product back to waiting. The engine keeps the reason. */
  const passOver = useCallback(
    async (id: string, why: string, worker: Worker) => {
      workers.current.delete(id)
      if (worker.removed) return
      try {
        await patch(`/api/queue/${seg(id)}`, { state: 'waiting', note: why })
      } catch {
        /* The row may be gone. The next refresh tells. */
      }
      update(id, { state: 'waiting', progress: 0, line: why || 'Waits', note: why || undefined })
    },
    [update],
  )

  const run = useCallback(
    async (item: QueueItem, worker: Worker) => {
      const id = item.id
      // 1. Claim it. Another window may have won.
      try {
        await patch(`/api/queue/${seg(id)}`, { state: 'researching' })
      } catch (error) {
        workers.current.delete(id)
        if (error instanceof EngineError && error.status === 409) update(id, { state: 'researching', line: 'In another window' })
        return
      }
      update(id, { state: 'researching', progress: 0, line: 'Finds the product', note: undefined })

      // 2. Which product is it? A product no catalog names is researched as a draft.
      let target: ApiTarget | null = null
      let draft = false
      try {
        target = await get<ApiTarget>(`/api/queue/${seg(id)}/target`)
      } catch (error) {
        if (error instanceof EngineError && error.message === NOT_IN_CATALOGS) draft = true
        else return passOver(id, reasonOf(error), worker)
      }

      // 3. Start the research.
      let job = ''
      try {
        const started = draft
          ? await post<{ job_id: string }>('/api/extension/research-plane', {
              q: item.name,
              url: urls.current.get(id) ?? '',
              harness,
              allow_draft: true,
              quick: false,
            })
          : await post<{ job_id: string }>('/api/research', { subject_id: target!.subject_id, pack_id: target!.pack_id, harness })
        job = started.job_id
        worker.job = job
      } catch (error) {
        return passOver(id, reasonOf(error), worker)
      }

      // 4. Follow it.
      let state = ''
      let message = ''
      for (;;) {
        await sleep(POLL_MS)
        if (!alive.current) return
        if (worker.cancelled) {
          void post(`/api/jobs/${seg(job)}/cancel`, {}).catch(() => undefined)
          state = 'cancelled'
          message = 'stopped'
          break
        }
        try {
          const reading = await get<ApiJob>(`/api/jobs/${seg(job)}`)
          update(id, { progress: Math.min(0.97, reading.progress ?? 0), line: lineOf(reading) })
          if (reading.done || ['succeeded', 'failed', 'cancelled'].includes(reading.state)) {
            state = reading.state
            message = reading.message ?? ''
            break
          }
        } catch (error) {
          state = 'failed'
          message = reasonOf(error)
          break
        }
      }

      // 5. A new product exists once its catalog installed it. Ask which one it is.
      if (state === 'succeeded' && draft) {
        try {
          target = await get<ApiTarget>(`/api/queue/${seg(id)}/target?job_id=${seg(job)}`)
        } catch (error) {
          state = 'failed'
          message = reasonOf(error)
        }
      }

      // 6. Save the check, so Compare reads what was found.
      if (state === 'succeeded' && target) {
        try {
          const saved = await post<{ lookup_id?: string }>(`/api/products/${seg(target.subject_id)}/check`, {})
          if (!saved.lookup_id) throw new Error('empty')
          workers.current.delete(id)
          if (!worker.removed) {
            await patch(`/api/queue/${seg(id)}`, { state: 'done', lookup_id: saved.lookup_id }).catch(() => undefined)
            update(id, { state: 'done', progress: 1, line: 'Done', lookupId: saved.lookup_id, note: undefined })
            if (alive.current) setLastDone((last) => ({ n: (last?.n ?? 0) + 1, lookupId: saved.lookup_id!, name: item.name }))
          }
          return
        } catch (error) {
          state = 'failed'
          message = error instanceof EngineError ? `The answer was not saved: ${error.message}` : 'The answer was not saved.'
        }
      }

      // A job the reader stopped goes back to waiting without blame.
      const why = worker.cancelled ? '' : message ? `Research ${state}: ${message}` : `Research ${state}`
      return passOver(id, why, worker)
    },
    [harness, passOver, update],
  )

  // Start the next waiting products, up to the limit.
  useEffect(() => {
    if (!enabled || !running) return
    const free = limit - workers.current.size
    const next = items
      .filter((i) => i.state === 'waiting' && !i.note && !held.current.has(i.id) && !workers.current.has(i.id))
      .slice(0, Math.max(0, free))
    // Nothing is left to start and nothing runs: the work is done.
    if (!next.length && !workers.current.size) {
      setRunning(false)
      return
    }
    for (const item of next) {
      const worker: Worker = { cancelled: false, removed: false, job: '' }
      workers.current.set(item.id, worker)
      void run(item, worker)
    }
  }, [enabled, running, items, limit, run])

  const toggle = useCallback(
    (id: string) => {
      const worker = workers.current.get(id)
      if (worker) {
        // Pause: stop the job. The product goes back to waiting and stays held.
        held.current.add(id)
        worker.cancelled = true
        update(id, { state: 'paused', line: 'Pauses' })
        return
      }
      if (held.current.delete(id)) {
        update(id, { state: 'waiting', line: 'Waits' })
        return
      }
      // A product that was passed over: try again.
      void patch(`/api/queue/${seg(id)}`, { state: 'waiting', note: '' }).catch(() => undefined)
      update(id, { state: 'waiting', line: 'Waits', note: undefined })
    },
    [update],
  )

  const start = useCallback(() => {
    // Products that were passed over get another try.
    setItems((list) =>
      list.map((i) => {
        if (i.state !== 'waiting' || !i.note) return i
        void patch(`/api/queue/${seg(i.id)}`, { state: 'waiting', note: '' }).catch(() => undefined)
        return { ...i, note: undefined, line: 'Waits' }
      }),
    )
    setRunning(true)
  }, [])

  const stop = useCallback(() => {
    setRunning(false)
    for (const worker of workers.current.values()) worker.cancelled = true
  }, [])

  const cancel = useCallback((id: string) => {
    const worker = workers.current.get(id)
    if (worker) {
      worker.cancelled = true
      worker.removed = true
    }
    held.current.delete(id)
    setItems((list) => list.filter((i) => i.id !== id))
    void del(`/api/queue/${seg(id)}`).catch(() => undefined)
  }, [])

  // The engine queues by address. A product with no address is not queued from here.
  const add = useCallback(() => undefined, [])

  return useMemo(
    () => ({ items, active: items.filter((i) => i.state !== 'done').length, running, start, stop, lastDone, setItems, toggle, cancel, add }),
    [items, running, start, stop, lastDone, toggle, cancel, add],
  )
}

const items_of = (reply: ApiQueue) => reply.items ?? []

export function QueueProvider({ children }: { children: ReactNode }) {
  const { mode } = useEngine()
  const demo = useDemoQueue(mode === 'demo')
  const live = useLiveQueue(mode === 'live')
  return <Ctx.Provider value={mode === 'live' ? live : demo}>{children}</Ctx.Provider>
}

export function useQueue(): Queue {
  const value = useContext(Ctx)
  if (!value) throw new Error('useQueue needs QueueProvider')
  return value
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { RECENTS } from '../mock/data'
import { del, get, post, seg, type ApiHistoryItem } from './api'
import { useEngine } from './Engine'
import { savedLooks, type SavedCatalog, type SavedLook } from './looks'

/** Every saved check, for the History panel. The welcome page shows only the latest few. */

export interface Past {
  /** The id the product page opens. Demo rows use the name. */
  id: string
  name: string
  category: string
  /** Where the check came from: the browser extension or the app. */
  source: string
  risks: number
  at: number
  when: string
}

/** The event that tells other lists a check was deleted. */
export const HISTORY_CHANGED = 'kriko:history'

export function ago(iso: string | number): string {
  const then = typeof iso === 'number' ? iso : new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60000))
  if (minutes < 1) return 'Now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  return days === 1 ? 'Yesterday' : `${days} days ago`
}

/** The group a check sits in: Today, Yesterday, This week, or Earlier. */
export function dayGroup(at: number): string {
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  const days = Math.floor((start.getTime() - at) / 86400000) + 1
  if (at >= start.getTime()) return 'Today'
  if (days <= 1) return 'Yesterday'
  if (days <= 7) return 'This week'
  return 'Earlier'
}

const HOURS_AGO = [0.1, 0.1, 27, 28]
const DEMO: Past[] = [
  ...RECENTS.map((row, index) => ({
    id: `demo:${row.name}`,
    name: row.name,
    category: row.note,
    source: index % 2 ? 'app' : 'extension',
    risks: row.risks,
    at: Date.now() - HOURS_AGO[index % HOURS_AGO.length] * 3600000,
    when: row.when,
  })),
  { id: 'demo:Gamma Unit 400', name: 'Gamma Unit 400', category: 'Power tools', source: 'extension', risks: 0, at: Date.now() - 5 * 86400000, when: '5 days ago' },
  { id: 'demo:Delta Unit 500', name: 'Delta Unit 500', category: '', source: 'app', risks: 2, at: Date.now() - 19 * 86400000, when: '19 days ago' },
]

/** What `DELETE /api/history/{id}` hands back, kept so the delete can be undone.
 *  `demo` is the window's own stand-in for a demo row, which has no engine. */
export interface Undoable {
  lookup?: Record<string, unknown>
  checks?: Record<string, unknown>[]
  notes?: Record<string, unknown>[]
  demo?: Past
}

export function useHistory(query = '') {
  const { mode } = useEngine()
  const [items, setItems] = useState<Past[] | null>(null)
  const [problem, setProblem] = useState('')
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  useEffect(() => { setOffset(0) }, [query])

  // The newest request. An answer to an older one (the search for "kett" arriving after the one
  // for "kettle") is dropped: the list always shows the query in the box.
  const latest = useRef(0)

  const load = useCallback(async () => {
    // `checking` is not `demo`: while the engine is still being asked, showing
    // the window's stand-in list would claim there are no saved checks.
    if (mode === 'checking') return
    if (mode !== 'live') {
      setItems(DEMO)
      return
    }
    const mine = ++latest.current
    const live = () => latest.current === mine
    await get<{ items: ApiHistoryItem[] & { source?: string }[]; has_more?: boolean }>(`/api/history?limit=200&offset=${offset}&q=${encodeURIComponent(query)}`, 20000)
      .then((data) => {
        if (!live()) return
        const page = (data.items as (ApiHistoryItem & { source?: string })[]).map((row) => ({
            id: row.lookup_id,
            name: row.label,
            category: row.category,
            source: row.source ?? '',
            risks: row.claim_count,
            at: new Date(row.created_at).getTime(),
            when: ago(row.created_at),
          }))
        setItems((now) => offset ? [...(now ?? []), ...page.filter((row) => !(now ?? []).some((saved) => saved.id === row.id))] : page)
        setHasMore(!!data.has_more)
        setProblem('')
      })
      .catch((error: unknown) => live() && setProblem(error instanceof Error ? error.message : 'Could not read the history.'))
  }, [mode, query, offset])

  useEffect(() => {
    void load()
  }, [load])

  /**
   * Delete one check, and keep what it takes so the reader can change their mind.
   *
   * `undo` is the reply's `undo` field: the row and its triage, as the engine
   * handed it back. Holding it here rather than in a "trash" table means the
   * undo lasts exactly as long as this panel does, which is the honest lifetime
   * for an action the reader just confirmed — and it is why the engine's delete
   * returns the data instead of storing it.
   */
  const remove = useCallback(
    async (id: string): Promise<Undoable | null> => {
      setProblem('')
      let undo: Undoable | null = null
      if (mode === 'live') {
        try {
          const reply = await del<{ undo?: Undoable }>(`/api/history/${seg(id)}`)
          undo = reply?.undo ?? null
        } catch (error) {
          setProblem(error instanceof Error ? error.message : 'Could not delete it.')
          return null
        }
      } else {
        const row = items?.find((one) => one.id === id)
        undo = row ? { demo: row } : null
      }
      setItems((now) => (now ? now.filter((row) => row.id !== id) : now))
      window.dispatchEvent(new Event(HISTORY_CHANGED))
      return undo
    },
    [mode, items],
  )

  /** Put it back. A demo row goes back into the window's own list. */
  const restore = useCallback(
    async (undo: Undoable) => {
      setProblem('')
      if (mode === 'live') {
        try {
          await post('/api/history/restore', undo)
        } catch (error) {
          setProblem(error instanceof Error ? error.message : 'Could not put it back.')
          return
        }
      } else if (undo.demo) {
        setItems((now) => (now ? [...now, undo.demo as Past].sort((a, b) => b.at - a.at) : now))
      }
      // A restored row belongs on the first page, so start the list again from it.
      if (offset) setOffset(0)
      else await load()
      window.dispatchEvent(new Event(HISTORY_CHANGED))
    },
    [mode, load, offset],
  )

  return { items, problem, remove, restore, hasMore, loadMore: () => setOffset((n) => n + 200), retry: () => void load() }
}

/** The saved quick looks a catalog has not claimed, and the catalogs a reader
 *  may choose from.
 *
 *  `/api/history/records` is the surface that carries a look's `job_id` and its
 *  `categorization` together with `categorization_catalogs`; the plain history
 *  route below has neither. `looks.ts` maps it and keeps the engine's
 *  abstention an open question. Like every other client, demo mode draws
 *  nothing rather than a stand-in: a filed-for-you row would be an assignment
 *  nobody made. */
export function useSavedLooks() {
  const { mode } = useEngine()
  const [looks, setLooks] = useState<SavedLook[] | null>(null)
  const [catalogs, setCatalogs] = useState<SavedCatalog[]>([])
  const [problem, setProblem] = useState('')
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const load = useCallback(async () => {
    if (mode !== 'live') {
      setLooks(null)
      setProblem('')
      return
    }
    try {
      const reply = await get<unknown>('/api/history/records?limit=200')
      if (!alive.current) return
      const found = savedLooks(reply)
      setLooks(found.looks)
      setCatalogs(found.catalogs)
      setProblem('')
    } catch (error) {
      if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not read the saved quick looks.')
    }
  }, [mode])

  useEffect(() => {
    void load()
  }, [load])

  return { looks, catalogs, problem, reload: load }
}

/** Save the reader's catalog choice for one saved look.
 *  The engine validates it against the installed catalogs it listed. */
export async function assignSavedLook(jobId: string, packId: string) {
  return post<{ status?: string; pack_name?: string; message?: string }>(
    `/api/quick-looks/${seg(jobId)}/category`, { pack_id: packId })
}

/** Ask the configured agent to name the catalog, as a job the screen follows.
 *  Spending an agent is the reader's press, which is why it is a separate one. */
export async function askAgentToCategorizeLook(jobId: string) {
  return post<{ job_id: string }>(`/api/quick-looks/${seg(jobId)}/categorize`)
}

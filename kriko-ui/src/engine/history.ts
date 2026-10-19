import { useCallback, useEffect, useState } from 'react'
import { RECENTS } from '../mock/data'
import { del, get, seg, type ApiHistoryItem } from './api'
import { useEngine } from './Engine'

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

export function useHistory(query = '') {
  const { mode } = useEngine()
  const [items, setItems] = useState<Past[] | null>(null)
  const [problem, setProblem] = useState('')
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => { setOffset(0) }, [query])

  useEffect(() => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setItems(DEMO)
      return
    }
    let live = true
    get<{ items: ApiHistoryItem[] & { source?: string }[]; has_more?: boolean }>(`/api/history?limit=200&offset=${offset}&q=${encodeURIComponent(query)}`, 20000)
      .then((data) => {
        if (!live) return
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
      .catch((error: unknown) => live && setProblem(error instanceof Error ? error.message : 'Could not read the history.'))
    return () => {
      live = false
    }
  }, [mode, query, offset, attempt])

  /** Delete one check. The list drops it when the engine says it is gone. */
  const remove = useCallback(
    async (id: string) => {
      setProblem('')
      if (mode === 'live') {
        try {
          await del(`/api/history/${seg(id)}`)
        } catch (error) {
          setProblem(error instanceof Error ? error.message : 'Could not delete it.')
          return
        }
      }
      setItems((now) => (now ? now.filter((row) => row.id !== id) : now))
      window.dispatchEvent(new Event(HISTORY_CHANGED))
    },
    [mode],
  )

  return { items, problem, remove, hasMore, loadMore: () => setOffset((n) => n + 200), retry: () => setAttempt((n) => n + 1) }
}

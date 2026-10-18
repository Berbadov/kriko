import { useCallback, useEffect, useState } from 'react'
import { RECENTS, type Recent } from '../mock/data'
import { get, type ApiHistoryItem } from './api'
import { useEngine } from './Engine'
import { ago, HISTORY_CHANGED } from './history'

/** The latest checks, for the welcome page. Demo data when no engine answers. */
export function useRecents(): Recent[] {
  const { mode } = useEngine()
  const [items, setItems] = useState<Recent[]>(RECENTS)
  const [round, setRound] = useState(0)

  // A check deleted in History must leave this list too.
  const again = useCallback(() => setRound((n) => n + 1), [])
  useEffect(() => {
    window.addEventListener(HISTORY_CHANGED, again)
    return () => window.removeEventListener(HISTORY_CHANGED, again)
  }, [again])

  useEffect(() => {
    if (mode !== 'live') {
      setItems(RECENTS)
      return
    }
    let live = true
    get<{ items: ApiHistoryItem[] }>('/api/history?limit=4')
      .then((data) => {
        if (!live) return
        setItems(
          data.items.map((row) => ({
            id: row.lookup_id,
            name: row.label,
            note: row.category || 'Quick look',
            risks: row.claim_count,
            when: ago(row.created_at),
          })),
        )
      })
      .catch(() => live && setItems([]))
    return () => {
      live = false
    }
  }, [mode, round])

  return items
}

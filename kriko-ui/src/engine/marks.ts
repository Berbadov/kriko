import { useCallback, useEffect, useRef, useState } from 'react'
import { get } from './api'
import { useEngine } from './Engine'

/** The reader's own verdicts on claims the engine served.
 *
 *  `GET /api/marks` is the only read of `claim_marks`; the extension writes and
 *  deletes a mark (`extension/background.js`), so every screen in the window
 *  could only ever know what it had just sent. Nothing here turns a mark into
 *  evidence: the route's own docstring says an opinion never changes a pack,
 *  and this client only carries the rows the engine returns — including the
 *  snapshot `title` and `note`, which is what keeps a mark readable after its
 *  pack is updated or removed. */

export interface Mark {
  pack_id: string
  claim_id: string
  verdict: string
  note: string
  /** Snapshots, so a mark outlives the claim row it was written against. */
  subject_id: string
  title: string
  created_at: string
  updated_at: string
}

export type MarkCounts = Record<string, number>

interface ApiMarks {
  items: Mark[]
  counts: MarkCounts
  verdicts: string[]
}

export function useMarks() {
  const { mode } = useEngine()
  const [marks, setMarks] = useState<Mark[] | null>(null)
  const [counts, setCounts] = useState<MarkCounts>({})
  const [verdicts, setVerdicts] = useState<string[]>([])
  const [problem, setProblem] = useState('')
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const load = useCallback(async () => {
    // Demo mode has no engine, and a mark is the reader's own record: a
    // stand-in row would be the one thing in this window that was invented.
    if (mode !== 'live') {
      setMarks(null)
      setProblem('')
      return
    }
    try {
      const found = await get<ApiMarks>('/api/marks?limit=200')
      if (!alive.current) return
      setMarks(found.items ?? [])
      setCounts(found.counts ?? {})
      setVerdicts(found.verdicts ?? [])
      setProblem('')
    } catch (error) {
      if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not read your marks.')
    }
  }, [mode])

  useEffect(() => {
    void load()
  }, [load])

  return { marks, counts, verdicts, problem, reload: load }
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { del, get, seg } from './api'
import { useEngine } from './Engine'

/** What each unattended research run cost, what it added, and the way back out.
 *
 *  `GET /api/research-runs` is the spend surface the router's own tests call it:
 *  `claims` and `removed` are counted when it is read, because an undo changes
 *  them. `GET /api/usage` says what the sums are and — the part a blank cell
 *  cannot — which columns a plane is even able to count, so a run that spent
 *  nothing and a run nobody metered never read the same. `DELETE
 *  /api/research-runs/{id}` starts the job that takes one run's claims back out;
 *  it is a job because the runner owns the "one write per claim, never two on
 *  one pack" rule, and the screen follows it the way every other job is
 *  followed. */

export interface ResearchRun {
  run_id: string
  job_id: string
  plane: string
  /** `llm` on the wire, for the reason `state._research_run` gives: `model` is
   *  a pack identity word and the interface may not name one. */
  llm: string
  search_provider: string
  budget_usd: number | null
  /** `null` when the plane cannot meter that column — never zero. */
  spent_usd: number | null
  tokens_used: number | null
  started_at: string
  ended_at: string
  outcome: string
  /** Claims the run still owns, counted at read time. */
  claims: number
  removed: number
}

export interface ResearchUsage {
  runs: number
  claims: number
  removed: number
  spent_usd: number | null
  tokens_used: number | null
  runs_counted_in_usd: number
  runs_counted_in_tokens: number
  /** The engine's sentence for why a column is empty, keyed by column. */
  metered: Record<string, string>
}

const USAGE: ResearchUsage = {
  runs: 0,
  claims: 0,
  removed: 0,
  spent_usd: null,
  tokens_used: null,
  runs_counted_in_usd: 0,
  runs_counted_in_tokens: 0,
  metered: {},
}

export function useResearchRuns() {
  const { mode } = useEngine()
  const [runs, setRuns] = useState<ResearchRun[] | null>(null)
  // `null` until `/api/usage` answers: a total of zero for a question that was
  // never answered is the one figure this screen must not print.
  const [usage, setUsage] = useState<ResearchUsage | null>(null)
  const [problem, setProblem] = useState('')
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const load = useCallback(async () => {
    // No engine, no runs: demo mode keeps its stand-in checks and invents no
    // spend, because a cost is exactly the kind of number this window may not
    // make up.
    if (mode !== 'live') {
      setRuns(null)
      setUsage(null)
      setProblem('')
      return
    }
    try {
      const listed = await get<{ runs: ResearchRun[] }>('/api/research-runs?limit=200')
      if (!alive.current) return
      setRuns(listed.runs ?? [])
      setProblem('')
    } catch (error) {
      if (alive.current) {
        setProblem(error instanceof Error ? error.message : 'Could not read the research runs.')
        setUsage(null)
      }
      return
    }
    // The sums are the second question, and a failed total is not a failed
    // list: the per-run rows are the spend surface, and they stay readable
    // without `/api/usage`. The `metered` sentence is what a blank column
    // loses, so it is read after the rows rather than beside them.
    try {
      const totals = await get<ResearchUsage>('/api/usage')
      if (alive.current) setUsage({ ...USAGE, ...totals })
    } catch {
      /* a row's own figures are still the engine's */
    }
  }, [mode])

  useEffect(() => {
    void load()
  }, [load])

  return { runs, usage, problem, reload: load }
}

/** Start the undo. The reply names the job whose progress the screen follows. */
export async function undoResearchRun(runId: string) {
  return del<{ job_id: string; run_id: string }>(`/api/research-runs/${seg(runId)}`)
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { get, seg } from './api'
import { useEngine } from './Engine'
import { plainText, queryOf, type Level, type LogFilter, type LogJob, type LogStep, type LogStepFull, type Source } from './logformat'

export * from './logformat'

const POLL_MS = 1500

/** The jobs, newest first, read again while any of them is still going. */
export function useLogJobs() {
  const { mode } = useEngine()
  const [jobs, setJobs] = useState<LogJob[] | null>(null)
  const [problem, setProblem] = useState('')
  const live = useRef(false)

  const load = useCallback(async () => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setJobs(DEMO_JOBS)
      return
    }
    try {
      const data = await get<{ items: LogJob[] }>('/api/logs/jobs?limit=80')
      setJobs(data.items)
      live.current = data.items.some((one) => !one.done)
      setProblem('')
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not read the log.')
    }
  }, [mode])

  useEffect(() => {
    void load()
    if (mode !== 'live') return
    const timer = window.setInterval(() => void load(), POLL_MS * 2)
    return () => window.clearInterval(timer)
  }, [load, mode])

  return { jobs, problem, reload: load }
}

/** The steps for one filter. A job that is still going is read again every moment. */
export function useLogSteps(filter: LogFilter, following: boolean) {
  const { mode } = useEngine()
  const [data, setData] = useState<{ items: LogStep[]; total: number; truncated: boolean } | null>(null)
  const [problem, setProblem] = useState('')
  const latest = useRef(0)
  const key = queryOf(filter)

  const load = useCallback(async () => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setData(demoSteps(filter))
      return
    }
    const mine = ++latest.current
    try {
      const reply = await get<{ items: LogStep[]; total: number; truncated: boolean }>(`/api/logs/steps?${queryOf(filter, { limit: '1500' })}`, 20000)
      if (mine !== latest.current) return
      setData(reply)
      setProblem('')
    } catch (error) {
      if (mine === latest.current) setProblem(error instanceof Error ? error.message : 'Could not read the steps.')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` is the filter, flattened
  }, [mode, key])

  useEffect(() => {
    setData(null)
    void load()
  }, [load])

  useEffect(() => {
    if (mode !== 'live' || !following) return
    const timer = window.setInterval(() => void load(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [load, mode, following])

  return { data, problem, reload: load }
}

/** One step with its exact request and reply. Only asked for when a row opens. */
export async function loadStep(id: number, live: boolean): Promise<LogStepFull> {
  if (!live) {
    const found = DEMO_STEPS.find((one) => one.step_id === id)
    return { ...(found as LogStep), request: DEMO_BODIES[id]?.[0] ?? '', response: DEMO_BODIES[id]?.[1] ?? '' }
  }
  return get<LogStepFull>(`/api/logs/steps/${seg(String(id))}`)
}

export async function exportLog(filter: LogFilter, bodies: boolean, live: boolean): Promise<{ filename: string; text: string }> {
  if (!live) {
    const shown = demoSteps(filter).items
    return { filename: 'kriko-log-demo.txt', text: plainText(DEMO_JOBS, shown, bodies) }
  }
  return get<{ filename: string; text: string }>(`/api/logs/export?${queryOf(filter, bodies ? { bodies: 'true' } : {})}`, 60000)
}

// ── demo data: a research run with a retry and a refusal, and a failed quick look ──

const T0 = Date.parse('2026-10-20T09:14:02.000Z')
const iso = (ms: number) => new Date(T0 + ms).toISOString()

const step = (id: number, job: string, offset: number, source: Source, level: Level, title: string, more: Partial<LogStep> = {}): LogStep => ({
  step_id: id, job_id: job, at: iso(offset), source, level, title, state: 'done', ms: null, parent_id: null,
  tokens: null, usd: null, detail: {}, request_chars: 0, response_chars: 0, offset_ms: offset, gap_ms: null, depth: 0, ...more,
})

const DEMO_STEPS: LogStep[] = [
  step(1, 'demo-run', 0, 'job', 'info', 'started'),
  step(2, 'demo-run', 410, 'search', 'info', 'searched "Alpha Unit 200 overheating"', { detail: { queries: ['Alpha Unit 200 overheating'] } }),
  step(3, 'demo-run', 1380, 'page', 'info', 'fetched https://forum.example.test/alpha-200-heat', { detail: { urls: ['https://forum.example.test/alpha-200-heat'], read: true } }),
  step(4, 'demo-run', 2210, 'page', 'error', 'could not read: https://shop.example.test/alpha-200', { detail: { urls: ['https://shop.example.test/alpha-200'], read: false } }),
  step(5, 'demo-run', 2300, 'agent', 'error', 'ask: Coding agent · model-a failed: RuntimeError: rate limit', {
    state: 'failed', ms: 1900, request_chars: 5210, response_chars: 33,
    detail: { agent: 'coding', agent_label: 'Coding agent', model: 'model-a', method: 'ask', attempt: 1, prompt_chars: 5210, error: 'RuntimeError: rate limit' },
  }),
  step(6, 'demo-run', 4250, 'retry', 'warn', 'retrying ask (attempt 2): RuntimeError: rate limit', { detail: { attempt: 2, reason: 'RuntimeError: rate limit' } }),
  step(7, 'demo-run', 4260, 'agent', 'info', 'ask: Coding agent · model-a', {
    ms: 12400, tokens: 3180, usd: 0.0214, request_chars: 5210, response_chars: 2840,
    detail: { agent: 'coding', agent_label: 'Coding agent', model: 'model-a', method: 'ask', attempt: 2, prompt_chars: 5210, reply_chars: 2840 },
  }),
  step(8, 'demo-run', 16700, 'verify', 'info', 'kept “Heat under long load” as c-1', { detail: { verdict: 'kept', subject: 'Heat under long load' } }),
  step(9, 'demo-run', 16710, 'verify', 'warn', 'refused “Cable is short”: no quote on the page', { detail: { verdict: 'refused', subject: 'Cable is short', why: 'no quote on the page' } }),
  step(10, 'demo-run', 16800, 'job', 'info', 'succeeded: 1 claim(s) kept', { detail: { state: 'succeeded' } }),
  step(11, 'demo-quick', 0, 'job', 'info', 'started'),
  step(12, 'demo-quick', 300, 'search', 'info', 'searching: Beta Unit 300 cable; Beta Unit 300 recall', { detail: { queries: ['Beta Unit 300 cable', 'Beta Unit 300 recall'] } }),
  step(13, 'demo-quick', 5100, 'job', 'error', 'failed: ValueError: no page could be read', { detail: { state: 'failed' } }),
]

const DEMO_BODIES: Record<number, [string, string]> = {
  5: ['Research the product “Alpha Unit 200”. Search for what goes wrong with it, and quote the page for every claim.\n\n## About this reader\n[saved profile]\n', 'RuntimeError: rate limit'],
  7: ['Research the product “Alpha Unit 200”. Search for what goes wrong with it, and quote the page for every claim.\n\n## About this reader\n[saved profile]\n', '{"claims":[{"title":"Heat under long load","quote":"it throttles after twenty minutes"}]}'],
}

const DEMO_JOBS: LogJob[] = [
  {
    job_id: 'demo-run', kind: 'research', label: 'Alpha Unit 200', state: 'succeeded', done: true, message: '1 claim(s) kept',
    created_at: iso(-200), started_at: iso(0), finished_at: iso(16800), duration_ms: 16800, steps: 10, errors: 2, warnings: 2,
    searches: 1, pages: 2, retries: 1, calls: 2, tokens: 3180, usd: 0.0214, usd_complete: true,
  },
  {
    job_id: 'demo-quick', kind: 'quick_look', label: 'Beta Unit 300', state: 'failed', done: true, message: 'ValueError: no page could be read',
    created_at: iso(-100), started_at: iso(0), finished_at: iso(5100), duration_ms: 5100, steps: 3, errors: 1, warnings: 0,
    searches: 1, pages: 0, retries: 0, calls: 0, tokens: null, usd: null, usd_complete: true,
  },
]

function demoSteps(filter: LogFilter) {
  const needle = filter.q.trim().toLowerCase()
  const items = DEMO_STEPS.filter(
    (one) =>
      (!filter.job || one.job_id === filter.job) &&
      (!filter.levels.length || filter.levels.includes(one.level)) &&
      (!filter.sources.length || filter.sources.includes(one.source)) &&
      (!needle || `${one.title} ${JSON.stringify(one.detail)}`.toLowerCase().includes(needle)),
  )
  return { items, total: items.length, truncated: false }
}

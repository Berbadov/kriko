/** The log section's shapes and the plain functions over them: what the engine's
 *  `/api/logs` returns, how a filter becomes a query, how a step reads. No React
 *  here, so the checks can run it without a window. */

export const LEVELS = ['info', 'warn', 'error'] as const
export const SOURCES = ['job', 'search', 'page', 'agent', 'verify', 'retry', 'note'] as const
export type Level = (typeof LEVELS)[number]
export type Source = (typeof SOURCES)[number]

export interface LogJob {
  job_id: string
  kind: string
  label: string
  state: string
  done: boolean
  message: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  steps: number
  errors: number
  warnings: number
  searches: number
  pages: number
  retries: number
  calls: number
  /** `null` is "nobody counted", which is not the same as none. */
  tokens: number | null
  usd: number | null
  /** False when some call had no price, so `usd` is a floor. */
  usd_complete: boolean
}

export interface LogStep {
  step_id: number
  job_id: string
  at: string
  source: Source
  level: Level
  title: string
  state: 'running' | 'done' | 'failed'
  ms: number | null
  parent_id: number | null
  tokens: number | null
  usd: number | null
  detail: Record<string, unknown>
  request_chars: number
  response_chars: number
  offset_ms: number | null
  gap_ms: number | null
  depth: number
}

export interface LogStepFull extends LogStep {
  request: string
  response: string
}

export interface LogFilter {
  job: string
  levels: Level[]
  sources: Source[]
  q: string
}

export const NO_FILTER: LogFilter = { job: '', levels: [], sources: [], q: '' }

/** The query the engine is asked, built from what the reader picked. */
export function queryOf(filter: LogFilter, extra: Record<string, string> = {}): string {
  const pairs: [string, string][] = []
  if (filter.job) pairs.push(['job_id', filter.job])
  if (filter.levels.length) pairs.push(['level', filter.levels.join(',')])
  if (filter.sources.length) pairs.push(['source', filter.sources.join(',')])
  if (filter.q.trim()) pairs.push(['q', filter.q.trim()])
  for (const [key, value] of Object.entries(extra)) pairs.push([key, value])
  return pairs.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join('&')
}

/** 1234 → "1.2 s", 80 → "80 ms", 125000 → "2 min 5 s". `null` is unknown, not zero. */
export function span(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '·'
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`
  const minutes = Math.floor(ms / 60000)
  return `${minutes} min ${Math.round((ms - minutes * 60000) / 1000)} s`
}

export function cost(usd: number | null | undefined, complete = true): string {
  if (usd === null || usd === undefined) return 'not counted'
  const text = usd < 0.01 && usd > 0 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`
  return complete ? text : `at least ${text}`
}

export function count(value: number | null | undefined): string {
  return value === null || value === undefined ? 'not counted' : value.toLocaleString('en-GB')
}

/** What a step says besides its title: the words, the pages, the sizes, the verdict. */
export function facts(step: LogStep): [string, string][] {
  const d = step.detail
  const out: [string, string][] = []
  const list = (value: unknown) => (Array.isArray(value) ? value.map(String).join(', ') : String(value))
  if (d.queries) out.push(['Searched for', list(d.queries)])
  if (d.urls) out.push([d.read === false ? 'Not read' : 'Page', list(d.urls)])
  else if (d.read === true) out.push(['Read', 'yes'])
  if (d.verdict) out.push(['Verdict', `${d.verdict}${d.why ? `: ${d.why}` : ''}`])
  if (d.reason) out.push(['Why', String(d.reason)])
  if (d.attempt && Number(d.attempt) > 1) out.push(['Attempt', String(d.attempt)])
  if (d.agent) out.push(['Agent', `${d.agent_label ?? d.agent}${d.model ? ` · ${d.model}` : ''}`])
  if (d.prompt_chars !== undefined) out.push(['Prompt', `${Number(d.prompt_chars).toLocaleString('en-GB')} characters`])
  if (d.reply_chars !== undefined) out.push(['Reply', `${Number(d.reply_chars).toLocaleString('en-GB')} characters`])
  if (step.source === 'agent') {
    out.push(['Tokens', count(step.tokens)])
    out.push(['Cost', cost(step.usd)])
  }
  if (d.error) out.push(['Error', String(d.error)])
  return out
}

/** The same rows as plain text, for the demo, where there is no engine to ask. */
export function plainText(jobs: LogJob[], steps: LogStep[], bodies: boolean): string {
  const lines = [`Kriko log (demo data), ${steps.length} step(s)`, '']
  for (const job of jobs) {
    const mine = steps.filter((one) => one.job_id === job.job_id)
    if (!mine.length) continue
    lines.push(`job ${job.job_id}  ${job.kind}  ${job.label}  [${job.state}]`, '')
    for (const one of mine) {
      lines.push(`+${((one.offset_ms ?? 0) / 1000).toFixed(3)}s  ${one.level.toUpperCase().padEnd(5)}  ${one.source.padEnd(6)}  ${'  '.repeat(one.depth)}${one.title}`)
      if (bodies) for (const [key, value] of facts(one)) lines.push(`${' '.repeat(26)}${key}: ${value}`)
    }
    lines.push('')
  }
  return `${lines.join('\n').trimEnd()}\n`
}


/** What the app has used, by what it was used on, as `GET /api/usage/meters`
 *  serves it (`app/usage.py` says what each number is and when it is blank).
 *
 *  Nothing here works a number out. A figure the engine did not give is absent,
 *  and an absent figure is not drawn: a resource with no recorded use is left
 *  out, a window with no priced call has no dollars, and a coding agent that
 *  reported a status and no percentage shows the status and no bar. */

export type ResourceId = 'llm_api' | 'web_search' | 'local_model' | 'cli_agent'
export type WindowId = '5h' | '24h' | '7d' | '30d'

export interface WindowSum {
  calls: number
  tokens_in: number | null
  tokens_out: number | null
  tokens: number | null
  usd: number | null
  rows: number
  rows_priced: number
  rows_tokenised: number
  misses: number | null
}

export interface SourceSum extends WindowSum {
  source: string
  model: string
}

export interface AgentWindow {
  used: number | null
  status: string | null
  resets_at: number | null
  overage: boolean | null
  seen_at: number | null
}

export interface Resource {
  used: boolean
  windows: Record<WindowId, WindowSum>
  by_source: SourceSum[]
  limits?: Record<string, Record<string, AgentWindow>>
}

export interface Meters {
  as_of: number
  windows: WindowId[]
  resources: Record<ResourceId, Resource>
}

export const RESOURCE_WORDS: Record<ResourceId, { title: string; line: string }> = {
  cli_agent: { title: 'Coding agent', line: 'Signed in to a subscription. Counts runs Kriko started.' },
  llm_api: { title: 'LLM API', line: 'A hosted model, billed by the token.' },
  web_search: { title: 'Web search API', line: 'Searches sent to a search provider.' },
  local_model: { title: 'Local model', line: 'Runs on this computer. Costs nothing.' },
}

export const RESOURCE_ORDER: ResourceId[] = ['cli_agent', 'llm_api', 'web_search', 'local_model']

export const WINDOW_WORDS: Record<string, string> = {
  '5h': '5 hours',
  '24h': '24 hours',
  '7d': '7 days',
  '30d': '30 days',
  five_hour: '5 hours',
  seven_day: 'Week',
  seven_day_opus: 'Week, Opus',
  seven_day_sonnet: 'Week, Sonnet',
  overage: 'Extra usage',
}

const ORDER_OF_LIMITS = ['five_hour', 'seven_day', 'seven_day_opus', 'seven_day_sonnet', 'overage']

/** The resources that have ever been used, in the order the card draws them. */
export function usedResources(meters: Meters | null): ResourceId[] {
  if (!meters) return []
  return RESOURCE_ORDER.filter((id) => meters.resources[id]?.used)
}

/** How much of a window is left, 0 to 1, or null when the agent gave no figure. */
export function left(used: number | null): number | null {
  return used === null || !Number.isFinite(used) ? null : Math.min(1, Math.max(0, 1 - used))
}

export type Standing = 'ok' | 'warn' | 'out'

/** How the agent itself called the window, or how full it is where it gave a figure. */
export function standingOf(window: AgentWindow): Standing {
  if (window.status === 'rejected') return 'out'
  if (window.status === 'allowed_warning') return 'warn'
  const remaining = left(window.used)
  if (remaining !== null && remaining <= 0.05) return 'out'
  if (remaining !== null && remaining <= 0.2) return 'warn'
  return 'ok'
}

const STATUS_WORDS: Record<string, string> = { allowed: 'Within the limit', allowed_warning: 'Near the limit', rejected: 'Limit reached' }

export const statusWord = (status: string | null) => (status ? (STATUS_WORDS[status] ?? '') : '')

/** "2 h 10 min", "45 min" or "now"; empty when no reset time was given. */
export function resetsIn(resetsAt: number | null, now: number): string {
  if (resetsAt === null) return ''
  const seconds = Math.round(resetsAt - now)
  if (seconds <= 0) return 'now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${Math.max(1, minutes)} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} h${minutes % 60 ? ` ${minutes % 60} min` : ''}`
  return `${Math.round(hours / 24)} days`
}

/** "just now", "14 min ago", "3 h ago": when the agent last said it. */
export function ago(seenAt: number | null, now: number): string {
  if (seenAt === null) return ''
  const seconds = Math.max(0, Math.round(now - seenAt))
  if (seconds < 90) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 90) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  return hours < 48 ? `${hours} h ago` : `${Math.round(hours / 24)} days ago`
}

export interface AgentLimits {
  agent: string
  windows: ({ id: string; label: string } & AgentWindow)[]
  newest: number | null
}

/** Each agent's windows in the order a reader thinks of them: 5 hours, week, then the rest. */
export function agentLimits(resource: Resource | undefined): AgentLimits[] {
  const out: AgentLimits[] = []
  for (const [agent, windows] of Object.entries(resource?.limits ?? {})) {
    const ids = Object.keys(windows).sort((a, b) => {
      const ia = ORDER_OF_LIMITS.indexOf(a)
      const ib = ORDER_OF_LIMITS.indexOf(b)
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b)
    })
    const rows = ids.map((id) => ({ id, label: WINDOW_WORDS[id] ?? id.replaceAll('_', ' '), ...windows[id] }))
    const seen = rows.map((row) => row.seen_at).filter((value): value is number => typeof value === 'number')
    if (rows.length) out.push({ agent, windows: rows, newest: seen.length ? Math.max(...seen) : null })
  }
  return out
}

/** The one short line on the pill: the tightest window left, then the day's spend. */
export function pillParts(meters: Meters | null): { fill: number | null; text: string } {
  if (!meters) return { fill: null, text: '' }
  let tightest: number | null = null
  for (const agent of agentLimits(meters.resources.cli_agent)) {
    for (const window of agent.windows) {
      const remaining = left(window.used)
      if (remaining !== null && (tightest === null || remaining < tightest)) tightest = remaining
    }
  }
  const day = (id: ResourceId) => meters.resources[id]?.windows['24h']
  const bits: string[] = []
  const usd = day('llm_api')?.usd
  if (typeof usd === 'number') bits.push(usd === 0 ? '$0' : usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`)
  const searches = day('web_search')?.calls
  if (searches) bits.push(`${searches} ${searches === 1 ? 'search' : 'searches'}`)
  return { fill: tightest, text: bits.join(' · ') }
}

/** Example numbers for demo mode. They are marked as examples where they are drawn. */
export function demoMeters(now: number): Meters {
  const sum = (calls: number, extra: Partial<WindowSum> = {}): WindowSum => ({
    calls, tokens_in: null, tokens_out: null, tokens: null, usd: null, rows: calls, rows_priced: 0, rows_tokenised: 0, misses: null, ...extra,
  })
  const spread = (a: WindowSum, b: WindowSum, c: WindowSum, d: WindowSum): Record<WindowId, WindowSum> => ({ '5h': a, '24h': b, '7d': c, '30d': d })
  return {
    as_of: now,
    windows: ['5h', '24h', '7d', '30d'],
    resources: {
      cli_agent: {
        used: true,
        windows: spread(sum(6, { tokens: 41_200 }), sum(14, { tokens: 118_000 }), sum(52, { tokens: 402_000 }), sum(190, { tokens: 1_480_000 })),
        by_source: [{ source: 'claude-code', model: '', ...sum(52, { tokens: 402_000 }) }],
        limits: {
          'claude-code': {
            five_hour: { used: 0.62, status: 'allowed', resets_at: now + 2 * 3600 + 10 * 60, overage: false, seen_at: now - 14 * 60 },
            seven_day: { used: 0.31, status: 'allowed', resets_at: now + 3 * 86400, overage: false, seen_at: now - 14 * 60 },
          },
        },
      },
      llm_api: {
        used: true,
        windows: spread(
          sum(5, { tokens_in: 9_400, tokens_out: 2_100, tokens: 11_500, usd: 0.04, rows_priced: 5, rows_tokenised: 5 }),
          sum(21, { tokens_in: 48_000, tokens_out: 9_800, tokens: 57_800, usd: 0.21, rows_priced: 21, rows_tokenised: 21 }),
          sum(88, { tokens_in: 210_000, tokens_out: 41_000, tokens: 251_000, usd: 0.93, rows_priced: 88, rows_tokenised: 88 }),
          sum(240, { tokens_in: 590_000, tokens_out: 120_000, tokens: 710_000, usd: 2.74, rows_priced: 240, rows_tokenised: 240 }),
        ),
        by_source: [
          { source: 'mistral-api', model: 'mistral-small', ...sum(70, { tokens_in: 160_000, tokens_out: 30_000, tokens: 190_000, usd: 0.62 }) },
          { source: 'api', model: 'gpt-4o-mini', ...sum(18, { tokens_in: 50_000, tokens_out: 11_000, tokens: 61_000, usd: 0.31 }) },
        ],
      },
      web_search: {
        used: true,
        windows: spread(sum(9, { misses: 1 }), sum(37, { misses: 3 }), sum(160, { misses: 11 }), sum(430, { misses: 29 })),
        by_source: [
          { source: 'exa', model: '', ...sum(120, { misses: 6 }) },
          { source: 'brave', model: '', ...sum(40, { misses: 5 }) },
        ],
      },
      local_model: {
        used: true,
        windows: spread(sum(4, { tokens: 6_300 }), sum(12, { tokens: 21_000 }), sum(60, { tokens: 98_000 }), sum(170, { tokens: 280_000 })),
        by_source: [{ source: 'local', model: 'qwen3-8b', ...sum(60, { tokens: 98_000 }) }],
      },
    },
  }
}

import type { ApiActivity, ApiUsage } from '../engine/api'
import type { Product, SourcePage, Usage } from '../activity/run'

/** What the right-hand column and the bars read. Nothing here is a second copy:
 *  every value is drawn from what a turn already carries (`activity`, `sources`,
 *  `products`, and the usage the job recorded), and it holds no list of sites
 *  and no window size. The engine says what a site is and how big a window is. */

const isHttp = (value: string) => /^https?:\/\//i.test(value)

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

/** An address in one spelling, so a page the log names and the page a turn read are one item. */
function canonical(url: string): string {
  try {
    return new URL(url).href.replace(/\/$/, '')
  } catch {
    return url.replace(/\/$/, '')
  }
}

const same = (a: string, b: string) => canonical(a) === canonical(b)

/** The pages a turn touched, in the order it touched them, each once.
 *  A page it read or failed to read comes from `activity`; a page only the
 *  answer named comes from `sources`. A search lead that nobody opened is not a source. */
export function pagesFrom(activity: ApiActivity[] = [], sources: string[] = []): SourcePage[] {
  const cited = sources.filter(isHttp)
  const isCited = (url: string) => cited.some((one) => same(one, url))
  const pages: SourcePage[] = []
  for (const row of activity) {
    if (row.kind !== 'read' || !row.url || !isHttp(row.url)) continue
    if (row.attempted === false) continue
    const found = pages.find((page) => same(page.url, row.url as string))
    const read = row.state === 'done' ? 'read' : 'failed'
    if (found) {
      // A page read after a failed attempt is a page that was read.
      if (read === 'read') found.read = 'read'
      continue
    }
    const standing = row.trust?.standing
    pages.push({
      url: row.url,
      host: row.trust?.domain || hostOf(row.url),
      title: row.title || '',
      read,
      cited: isCited(row.url),
      tier: row.trust?.label,
      standing: standing === 'trusted' || standing === 'neutral' || standing === 'low' ? standing : undefined,
    })
  }
  for (const url of cited) {
    if (pages.some((page) => same(page.url, url))) continue
    pages.push({ url, host: hostOf(url), title: '', read: 'listed', cited: true })
  }
  return pages
}

const count = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null)

/** The usage a job recorded, or nothing when it recorded none. */
export function usageFrom(raw?: ApiUsage): Usage | undefined {
  if (!raw || !raw.context) return undefined
  const context = raw.context
  const state = context.state === 'measured' || context.state === 'not_reported' ? context.state : 'pending'
  return {
    tokensIn: count(raw.tokens_in),
    tokensOut: count(raw.tokens_out),
    tokens: count(raw.tokens),
    usd: count(raw.spent_usd),
    model: context.model ?? '',
    window: count(context.window),
    windowSource: context.window_source ?? '',
    used: count(context.used),
    state,
    fill: count(context.fill),
    trimmed: context.history?.trimmed === true,
    droppedReplies: count(context.history?.dropped_replies) ?? 0,
    omittedRequests: count(context.history?.omitted_requests) ?? 0,
  }
}

/** Amber from 70% of the window, red from 90%. A look, not a rule about any model. */
export const AMBER_AT = 0.7
export const RED_AT = 0.9

export type Tone = 'ok' | 'amber' | 'red'
export const toneOf = (fill: number | null): Tone => (fill === null ? 'ok' : fill >= RED_AT ? 'red' : fill >= AMBER_AT ? 'amber' : 'ok')

/** A count as the reader reads it: 1,240 and 18.4K, never a bare 18400. */
export function formatTokens(value: number | null): string {
  if (value === null) return 'not reported'
  if (value < 10000) return value.toLocaleString('en-GB')
  if (value < 1_000_000) return `${(value / 1000).toFixed(value < 100000 ? 1 : 0)}K`
  return `${(value / 1_000_000).toFixed(1)}M`
}

export function formatUsd(value: number | null): string {
  if (value === null) return ''
  if (value === 0) return '$0'
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`
}

/** One turn's own line: tokens in and out, and the cost where the plane gave one. */
export function turnLine(usage?: Usage): string {
  if (!usage) return ''
  const parts: string[] = []
  if (usage.tokensIn !== null && usage.tokensOut !== null) parts.push(`${formatTokens(usage.tokensIn)} in`, `${formatTokens(usage.tokensOut)} out`)
  else if (usage.tokens !== null) parts.push(`${formatTokens(usage.tokens)} tokens (split not reported)`)
  else parts.push('tokens not reported')
  const cost = formatUsd(usage.usd)
  parts.push(cost || 'cost not reported')
  return parts.join(' · ')
}

export interface ThreadUsage {
  tokensIn: number
  tokensOut: number
  /** Some turn did not report its split, so the totals are a floor. */
  partial: boolean
  usd: number
  /** Some turn did not report a price. */
  usdPartial: boolean
  /** The newest turn that measured a prompt: the thread's context now. */
  latest?: Usage
  trimmed: boolean
}

/** What the whole chat has spent so far, and the context its newest turn left behind. */
export function threadUsage(items: { usage?: Usage }[]): ThreadUsage {
  const out: ThreadUsage = { tokensIn: 0, tokensOut: 0, partial: false, usd: 0, usdPartial: false, trimmed: false }
  for (const item of items) {
    const usage = item.usage
    if (!usage) continue
    if (usage.tokensIn !== null && usage.tokensOut !== null) {
      out.tokensIn += usage.tokensIn
      out.tokensOut += usage.tokensOut
    } else out.partial = true
    if (usage.usd !== null) out.usd += usage.usd
    else out.usdPartial = true
    if (usage.trimmed) out.trimmed = true
    // A turn that has not counted anything yet must not hide what the last one measured.
    if (usage.state !== 'pending' || !out.latest) out.latest = usage
  }
  return out
}

export interface Group {
  id: string
  /** Which question this was, counting from the first. */
  n: number
  prompt: string
  products: Product[]
  pages: SourcePage[]
  running: boolean
}

/** The column's groups, newest first. A running turn and the same turn once it
 *  ends keep one id, so a poll or an ending never re-keys a row. */
export function groupsOf(
  turns: { id: string; prompt: string; products: Product[]; pages?: SourcePage[] }[],
  run?: { id: string; prompt: string; products: Product[]; pages?: SourcePage[]; running: boolean },
): Group[] {
  const groups: Group[] = turns.map((turn, index) => ({ id: turn.id, n: index + 1, prompt: turn.prompt, products: turn.products, pages: turn.pages ?? [], running: false }))
  if (run && !groups.some((group) => group.id === run.id)) {
    groups.push({ id: run.id, n: groups.length + 1, prompt: run.prompt, products: run.products, pages: run.pages ?? [], running: run.running })
  }
  return groups.filter((group) => group.products.length > 0 || group.pages.length > 0 || group.running).reverse()
}

export const productKey = (id: string) => `product:${id}`
export const pageKey = (url: string) => `page:${canonical(url)}`

import type { ProcurementSummary } from '../engine/procurement'
import type { SourcePage } from '../activity/run'

/** The procurement strip under the Ask box: what in the estimates needs the reader's
 *  eye today. Every number is a count the procurement layer already made; this only
 *  words it. A row exists only when its count is above zero, so a quiet estimate
 *  draws no strip at all. */

export type StripTone = 'warn' | 'risk'

export interface StripRow {
  id: 'expiry' | 'risk' | 'unpriced'
  tone: StripTone
  text: string
}

const plural = (count: number, one: string, many: string) => (count === 1 ? one : many)

/** The rows that have something to say, in the order the reader needs them:
 *  quotes that have gone or are going, then risk, then lines with no price. */
export function stripRows(summary: ProcurementSummary): StripRow[] {
  const rows: StripRow[] = []
  const soon = summary.expiring.length
  const gone = summary.expired.length
  if (soon > 0 || gone > 0) {
    const going = plural(soon, 'quote expires', 'quotes expire')
    const text = soon > 0 && gone > 0
      ? `${soon} ${going} within 14 days, and ${gone} ${gone === 1 ? 'has' : 'have'} already expired`
      : gone > 0
        ? `${gone} ${plural(gone, 'quote has', 'quotes have')} expired`
        : `${soon} ${going} within 14 days`
    rows.push({ id: 'expiry', tone: gone > 0 ? 'risk' : 'warn', text })
  }
  const risky = summary.atRisk.length
  if (risky > 0) {
    rows.push({ id: 'risk', tone: summary.atRisk.some((item) => item.risk === 'red') ? 'risk' : 'warn', text: `${risky} ${plural(risky, 'line', 'lines')} at red or amber risk` })
  }
  const unpriced = summary.unpricedLines
  if (unpriced > 0) {
    rows.push({ id: 'unpriced', tone: 'warn', text: `${unpriced} ${plural(unpriced, 'line has', 'lines have')} no price` })
  }
  return rows
}

/** Whether the strip is drawn at all: only in the live engine, and only when there is a line to read. */
export function showStrip(summary: ProcurementSummary, live: boolean): boolean {
  return live && summary.lines > 0 && stripRows(summary).length > 0
}

/** The sources an answer cites, once each, in the order the turn read them. */
export function footnotesOf(pages: SourcePage[] | undefined): SourcePage[] {
  const seen = new Set<string>()
  const out: SourcePage[] = []
  for (const page of pages ?? []) {
    if (!page.cited || seen.has(page.url)) continue
    seen.add(page.url)
    out.push(page)
  }
  return out
}

import type { Meters, ResourceId } from './usagemeters'

/** A reader's own ceiling for one day on one resource.
 *
 *  A cap warns; it never stops a run. The engine cannot know what a reader
 *  would want blocked, and a stopped answer is a worse failure than a warning
 *  that arrived too late.
 *
 *  The number is compared with the same 24-hour window the usage card draws,
 *  in the unit the resource is measured in: dollars for a hosted model, calls
 *  for everything else. An empty cap is no cap.
 *
 *  Nothing here touches storage or React: the rules are one plain function
 *  each, so a test can ask what a cap says without a window. */

export type CapResource = ResourceId

export interface CapWord {
  /** The row in Settings. */
  title: string
  /** The noun the input is measured in. */
  unit: string
  /** The one word the usage card puts after "of N". */
  short: string
  /** Dollars are a decimal; calls are whole. */
  money?: boolean
}

export const CAP_WORDS: Record<CapResource, CapWord> = {
  cli_agent: { title: 'Coding agent runs', unit: 'runs', short: 'runs' },
  llm_api: { title: 'LLM API spend', unit: 'dollars', short: 'spend', money: true },
  web_search: { title: 'Web searches', unit: 'searches', short: 'searches' },
  local_model: { title: 'Local model runs', unit: 'runs', short: 'runs' },
}

export const CAP_ORDER: CapResource[] = ['cli_agent', 'llm_api', 'web_search', 'local_model']

/** What the resource used in the last 24 hours, in the cap's own unit. */
export function usedToday(meters: Meters | null, id: CapResource): number | null {
  const day = meters?.resources[id]?.windows['24h']
  if (!day) return null
  const value = CAP_WORDS[id].money ? day.usd : day.calls
  return typeof value === 'number' ? value : null
}

/** True when today's use has reached the cap. A cap with no measured use is not over. */
export function overCap(meters: Meters | null, id: CapResource, cap: number | null): boolean {
  if (cap === null) return false
  const used = usedToday(meters, id)
  return used !== null && used >= cap
}

const money = (value: number) => `$${value.toFixed(value < 0.01 ? 4 : 2)}`

/** The one line the usage card puts under a resource, or '' when no cap is set. */
export function capLine(meters: Meters | null, id: CapResource, cap: number | null): string {
  if (cap === null) return ''
  const word = CAP_WORDS[id]
  const capText = word.money ? money(cap) : String(Math.round(cap))
  const used = usedToday(meters, id)
  if (used === null) return `No use counted yet today · cap ${capText}`
  const usedText = word.money ? money(used) : String(used)
  return `${usedText} of ${capText} ${word.short} today`
}

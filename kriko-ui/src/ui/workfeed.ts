import type { ApiActivity, ApiFeedEvent, ApiStep } from '../engine/api'

/** How a job's own words become the lines a reader watches.
 *
 *  Nothing here invents a step: a line is a feed event, or a line of the job's
 *  log when the engine sent no feed (a finished job keeps its log, not its
 *  feed). The header reason is the engine's message, the host of the newest
 *  page line, or the real stage the interface is in. */

/** Lines kept from one job. The panel draws the newest few; the rest stay
 *  readable when the reader scrolls, without growing with a long run. */
export const WORK_LINES_KEPT = 24
/** Lines the panel draws at once. */
export const WORK_LINES_VISIBLE = 6

export interface WorkReading {
  /** The engine job state, or the interface's own stage word. */
  state?: string
  message?: string
  /** A real stage before any job exists: "Starting the research". */
  stage?: string
  /** The agent the reader is waiting for, when the header should name it. */
  agent?: string
  feed?: ApiFeedEvent[]
  log?: string
  /** A job with no feed or log still reports the steps it ran and the pages it
   *  touched; those are the same real lines, so they are read last. */
  steps?: ApiStep[]
  activity?: ApiActivity[]
}

export interface WorkLine {
  id: string
  kind: string
  text: string
  host?: string
  url?: string
}

const URL_IN_TEXT = /https?:\/\/[^\s<>"']+/i

export function urlIn(text: string): string | undefined {
  const found = URL_IN_TEXT.exec(text)?.[0]
  return found?.replace(/[.,;:)\]}]+$/, '')
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

/** The job's feed as the engine sent it, or the lines it reported when the
 *  feed is absent: its log, then its steps, then the search/page activity. Feed
 *  wins when both exist: it is already classified. */
export function eventsOf(reading: WorkReading): ApiFeedEvent[] {
  if (reading.feed?.some((event) => event.text.trim())) return reading.feed
  const logged = (reading.log ?? '')
    .split(/\r?\n/)
    .flatMap((line) => line.split('; '))
    .map((text) => ({ kind: 'note', text: text.trim() }))
    .filter((event) => event.text)
  if (logged.length) return logged
  const steps = (reading.steps ?? [])
    .map((step) => ({ kind: 'note', text: (step.label || step.source || '').trim() }))
    .filter((event) => event.text)
  if (steps.length) return steps
  return (reading.activity ?? []).flatMap((item) => {
    if (item.kind === 'search') return item.query ? [{ kind: 'search', text: item.query }] : []
    const text = (item.url || item.title || item.text || '').trim()
    return text ? [{ kind: 'source', text }] : []
  })
}

/** The last `keep` real lines, oldest first. */
export function workLines(reading: WorkReading, keep = WORK_LINES_KEPT): WorkLine[] {
  const seen = new Map<string, number>()
  const lines: WorkLine[] = []
  for (const event of eventsOf(reading)) {
    const text = event.text.trim()
    if (!text) continue
    const key = `${event.kind}\u0000${text}`
    const times = (seen.get(key) ?? 0) + 1
    seen.set(key, times)
    const url = urlIn(text)
    lines.push({ id: `${key}\u0000${times}`, kind: event.kind, text, url, host: url ? hostOf(url) : undefined })
  }
  return lines.slice(-keep)
}

const FILE = /^(fetched|read through the page reader)\b/i
const SEARCH = /^(searched|query:)/i
const KEPT = /^(kept|wrote)\b/i
const PROBLEM = /^(a tool call failed|refused\b|left out\b|stopped:)/i

function kindOf(event: ApiFeedEvent): string {
  if (event.kind && event.kind !== 'note') return event.kind
  if (FILE.test(event.text)) return 'source'
  if (SEARCH.test(event.text)) return 'search'
  if (KEPT.test(event.text)) return 'finding'
  if (PROBLEM.test(event.text)) return 'problem'
  return event.kind || 'note'
}

/** The one line in the terminal header: why the reader is waiting now. */
export function waitReason(reading: WorkReading): string {
  const message = (reading.message ?? '').trim()
  if (message) return message

  const events = eventsOf(reading)
  const last = events[events.length - 1]
  if (last) {
    const kind = kindOf(last)
    const host = hostOf(urlIn(last.text) ?? '')
    if (host) return `Reading ${host}`
    if (kind === 'search') return 'Searching the web'
    if (kind === 'source') return 'Reading pages'
    if (kind === 'finding') return 'Checking what was found'
    if (kind === 'problem') return 'A step failed; continuing'
    return last.text.trim()
  }

  const state = (reading.state ?? '').trim()
  if (state === 'queued' || state === 'waiting') {
    return reading.agent ? `Waiting for ${reading.agent}` : 'Waiting for a research slot'
  }
  if (state === 'paused') return 'Paused'
  if (state === 'running' || state === 'researching') return reading.stage?.trim() || 'Job starting'
  if (state === 'cancelled' || state === 'stopped') return 'Stopped'
  if (state === 'failed') return 'The job did not finish'
  if (state === 'done' || state === 'succeeded') return 'Done'
  return reading.stage?.trim() || 'Starting'
}

/** A short word for the line's gutter. Chrome only; the text is untouched. */
export function markOf(kind: string): string {
  if (kind === 'search') return '?'
  if (kind === 'source') return '>'
  if (kind === 'finding') return '+'
  if (kind === 'problem') return '!'
  return '·'
}

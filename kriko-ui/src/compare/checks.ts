import { get, seg } from '../engine/api'
import { evidenceOf, type Evidence as Thinness } from '../engine/thinness'

/** A saved check, read for the table. The table is the engine's answers lined
 *  up and nothing else: a check's own claims, and the specifications of the
 *  product it matched. */

export type Level = 'critical' | 'high' | 'medium' | 'low' | 'unrated'

export interface Evidence {
  host: string
  url: string
  quote: string
  /** The engine's own word. "refutes" reads against the claim. */
  stance: string
  /** Where the engine puts this source for the reader. Absent when it could not say. */
  standing?: Standing
  /** The kind of site, in the pack's own word. */
  tier?: string
}

export type Standing = 'trusted' | 'neutral' | 'low'

const standingOf = (value: unknown): Standing | undefined => (value === 'trusted' || value === 'neutral' || value === 'low' ? value : undefined)

export interface Risk {
  key?: string
  title: string
  body: string
  level: Level
  disputed: boolean
  sources: Evidence[]
  applicability?: string
  advice?: string
  /** How thin the evidence is, as the engine derived it from the claim. Absent when the row had none. */
  evidence?: Thinness
}

export interface Spec {
  key?: string
  label: string
  value: string
  source: string
  quote?: string
}

export interface Check {
  lookupId: string
  name: string
  category: string
  specs: Spec[]
  risks: Risk[]
  checkedAt?: string
  assumed?: string
  coverage?: Record<string, unknown>
  diagnostic?: string
  context?: Record<string, unknown>
  contextUnits?: Record<string, string>
}

export type Loaded = { status: 'loading' } | { status: 'ready'; check: Check } | { status: 'error'; message: string }

const text = (value: unknown): string => (typeof value === 'string' ? value : '')
const list = (value: unknown): Record<string, unknown>[] => (Array.isArray(value) ? (value as Record<string, unknown>[]) : [])

export function levelOf(word: string): Level {
  const w = word.trim().toLowerCase()
  return w === 'critical' || w === 'high' || w === 'medium' || w === 'low' ? w : 'unrated'
}

export const grave = (level: Level) => level === 'critical' || level === 'high'

const hostOf = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

function riskFrom(claim: Record<string, unknown>): Risk {
  return {
    key: text(claim.concept_id) || text(claim.problem_key),
    title: text(claim.title),
    body: text(claim.body),
    level: levelOf(text(claim.severity)),
    disputed: claim.disputed === true,
    applicability: typeof claim.applicability === 'string' ? claim.applicability : claim.applicability && typeof claim.applicability === 'object'
      ? [text((claim.applicability as Record<string, unknown>).status), text((claim.applicability as Record<string, unknown>).reason)].filter(Boolean).join(': ') : '',
    advice: text(claim.advice),
    evidence: evidenceOf(claim.evidence),
    sources: list(claim.sources)
      .map((s) => {
        const url = text(s.url)
        return { host: text(s.domain) || hostOf(url), url, quote: text(s.quote), stance: text(s.stance), standing: standingOf(s.standing), tier: text(s.tier) || undefined }
      })
      .filter((s) => s.url || s.host),
  }
}

/** The product a check matched: the subject that owns the most claims. */
function matchedSubject(response: Record<string, unknown>): string {
  if (list(response.subjects).length > 1 || (Array.isArray(response.subjects) && response.subjects.length > 1)) return ''
  let best = ''
  let most = -1
  for (const s of Array.isArray(response.subjects) ? (response.subjects as unknown[]) : []) {
    const id = typeof s === 'string' ? s : text((s as Record<string, unknown>).subject_id)
    const claims = typeof s === 'string' ? 0 : Number((s as Record<string, unknown>).claims ?? 0)
    if (id && claims > most) {
      best = id
      most = claims
    }
  }
  return best || text(list(response.claims)[0]?.subject_id)
}

export async function loadCheck(lookupId: string): Promise<Check> {
  const stored = await get<Record<string, unknown>>(`/api/lookup/${seg(lookupId)}`)
  const response = (stored.response ?? {}) as Record<string, unknown>
  const risks = list(response.claims).map(riskFrom).filter((r) => r.title)
  const specs: Spec[] = list(response.specs).map((s) => ({
    key: text(s.key), label: text(s.name) || text(s.label), value: text(s.value),
    source: text(s.url) || text(s.source_url), quote: text(s.quote),
  })).filter((s) => s.label && s.value)
  const subject = matchedSubject(response)
  if (subject) {
    // A product that cannot be read leaves the column without specifications, never without its risks.
    try {
      const found = await get<Record<string, unknown>>(`/api/subjects/${seg(subject)}`)
      for (const a of list(found.attributes)) {
        const value = text(a.value_text)
        if (a.is_identity === true || !value.trim()) continue
        const unit = text(a.unit)
        const label = text(a.label) || text(a.key)
        if (!specs.some((s) => s.label.toLowerCase() === label.toLowerCase())) specs.push({ key: text(a.key), label, value: unit ? `${value} ${unit}` : value, source: text(a.source_url) })
      }
    } catch {
      /* the risks are still here */
    }
  }
  const diagnostic = response.diagnostic as Record<string, unknown> | undefined
  return { lookupId, name: text(stored.label) || 'Product', category: text(stored.category) || text(response.category), specs, risks,
    checkedAt: text(stored.created_at), assumed: text(response.assumed),
    coverage: (response.coverage ?? {}) as Record<string, unknown>, diagnostic: text(diagnostic?.message),
    context: (response.context ?? {}) as Record<string, unknown>, contextUnits: (response.context_units ?? {}) as Record<string, string> }
}

// ---- lining up ----

export interface RiskRow {
  key?: string
  title: string
  cells: (Risk | null)[]
  /** Not every column carries it, or they do not agree on it. */
  differs: boolean
}

export interface SpecRow {
  label: string
  cells: (Spec | null)[]
  differs: boolean
}

/** One row for each risk title that any column carries. */
export function riskRows(columns: Check[]): RiskRow[] {
  const titles = new Map<string, string>()
  for (const c of columns) for (const r of c.risks) if (!titles.has(riskKey(r))) titles.set(riskKey(r), r.title)
  return [...titles].map(([key, title]) => {
    const cells = columns.map((c) => c.risks.find((r) => riskKey(r) === key) ?? null)
    const found = cells.filter((c): c is Risk => c !== null)
    const differs =
      found.length !== cells.length || found.some((r) => r.level !== found[0].level || r.disputed !== found[0].disputed || r.applicability !== found[0].applicability || r.body !== found[0].body)
    return { key, title, cells, differs }
  })
}

export const riskKey = (risk: Risk) => risk.key || risk.title.trim().toLowerCase().replace(/\s+/g, ' ')

/** What the engine said about a check it could not ground, or "" when it kept
 *  findings or said nothing. The sentence is already on the row
 *  (`response.diagnostic.message`), so this reads it rather than writing a
 *  second one: the reasons — no page matched the product, quotes failed the
 *  evidence checks, stages were incomplete — are the engine's to name. */
export function groundingNote(check: Check): string {
  return check.risks.length === 0 ? (check.diagnostic || '').trim() : ''
}

/** The count, only when there is one.
 *
 *  A column with nothing kept used to print "0 risks", which reads as "this
 *  product has no risks" — the one claim the engine's own coverage refuses to
 *  make. It says what the engine said instead: a diagnostic means nothing was
 *  grounded, and its sentence is shown in full by `CheckContext`; no
 *  diagnostic at all is a row that recorded no findings, which is all this
 *  count ever measured. */
export function findingsLabel(check: Check): string {
  if (check.risks.length === 1) return '1 risk'
  if (check.risks.length > 1) return `${check.risks.length} risks`
  return check.diagnostic ? 'No grounded findings' : 'No findings stored'
}

/** One row for each label that any column states. */
export function specRows(columns: Check[]): SpecRow[] {
  const labels: string[] = []
  for (const c of columns) for (const s of c.specs) if (!labels.includes(s.label)) labels.push(s.label)
  return labels.map((label) => {
    const cells = columns.map((c) => c.specs.find((s) => s.label === label) ?? null)
    const found = cells.filter((c): c is Spec => c !== null)
    const differs = found.length !== cells.length || found.some((s) => comparableValue(s.value) !== comparableValue(found[0].value))
    return { label, cells, differs }
  })
}

/** Normalize only known dimensions; ambiguous quantities keep their wording. */
export function comparableValue(value: string): string {
  const match = value.trim().match(/^(-?\d+(?:\.\d+)?)\s*(kg|g|mm|cm|m|wh|kwh|w|kw|ml|l)$/i)
  if (!match) return value.trim().toLowerCase()
  const units: Record<string, [string, number]> = { kg: ['mass', 1000], g: ['mass', 1], mm: ['length', 1], cm: ['length', 10], m: ['length', 1000], wh: ['energy', 1], kwh: ['energy', 1000], w: ['power', 1], kw: ['power', 1000], ml: ['volume', 1], l: ['volume', 1000] }
  const [dimension, multiplier] = units[match[2].toLowerCase()]
  return `${dimension}:${Number((Number(match[1]) * multiplier).toPrecision(12))}`
}

// ---- demo ----

const DEMO_TITLES = ['Heat', 'Cable', 'Noise', 'Battery', 'Support']
const DEMO_LEVELS: (Level | null)[] = ['high', 'low', null, 'medium', 'low', null, 'high', 'critical']

/** A check for a demo name. The same name always gives the same check. */
export function demoCheck(lookupId: string, name: string): Check {
  let seed = 0
  for (const ch of name) seed = (seed * 31 + ch.charCodeAt(0)) >>> 0
  const risks: Risk[] = []
  DEMO_TITLES.forEach((title, i) => {
    const level = DEMO_LEVELS[(seed + i * 3) % DEMO_LEVELS.length]
    if (!level) return
    // Every third demo finding stands on one forum post, and every fourth on a single page.
    const lone = (seed + i) % 3 === 0
    const single = (seed + i) % 4 === 0
    risks.push({
      title,
      level,
      disputed: (seed + i) % 7 === 0,
      body: `${name} has a report about ${title.toLowerCase()}. Read the sources before you buy.`,
      evidence: lone
        ? { level: 'thin', reasons: [{ code: 'single_source', text: 'Only one site says this. Nothing else confirms it yet.' }, { code: 'low_trust', text: 'The best source for this is a low-trust kind of site, such as a forum or an ad-driven blog.' }] }
        : single
          ? { level: 'partial', reasons: [{ code: 'single_source', text: 'Only one site says this. Nothing else confirms it yet.' }] }
          : { level: 'solid', reasons: [] },
      sources: (lone
        ? [{ host: 'forum.example.test', url: 'https://forum.example.test', quote: `A reader reports a ${title.toLowerCase()} problem.`, stance: 'supports', standing: 'low', tier: 'forum_ugc' }]
        : [
            { host: 'maker.example.test', url: 'https://maker.example.test', quote: `The maker lists ${title.toLowerCase()} in its service notes.`, stance: 'supports', standing: 'trusted', tier: 'manufacturer' },
            ...(single ? [] : [{ host: 'club.example.test', url: 'https://club.example.test', quote: `Owners report a ${title.toLowerCase()} problem.`, stance: 'supports', standing: 'neutral', tier: 'specialist' }]),
          ]) as Evidence[],
    })
  })
  return {
    lookupId,
    name,
    category: 'Demo',
    specs: [
      { label: 'Weight', value: `${1 + (seed % 5)}.${seed % 9} kg`, source: '' },
      { label: 'Warranty', value: `${1 + (seed % 3)} years`, source: '' },
    ],
    risks,
  }
}

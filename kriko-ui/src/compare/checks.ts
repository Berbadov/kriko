import { get, seg } from '../engine/api'

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
}

export interface Risk {
  title: string
  body: string
  level: Level
  disputed: boolean
  sources: Evidence[]
}

export interface Spec {
  label: string
  value: string
  source: string
}

export interface Check {
  lookupId: string
  name: string
  category: string
  specs: Spec[]
  risks: Risk[]
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
    title: text(claim.title),
    body: text(claim.body),
    level: levelOf(text(claim.severity)),
    disputed: claim.disputed === true,
    sources: list(claim.sources)
      .map((s) => {
        const url = text(s.url)
        return { host: text(s.domain) || hostOf(url), url, quote: text(s.quote), stance: text(s.stance) }
      })
      .filter((s) => s.url || s.host),
  }
}

/** The product a check matched: the subject that owns the most claims. */
function matchedSubject(response: Record<string, unknown>): string {
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
  const specs: Spec[] = []
  const subject = matchedSubject(response)
  if (subject) {
    // A product that cannot be read leaves the column without specifications, never without its risks.
    try {
      const found = await get<Record<string, unknown>>(`/api/subjects/${seg(subject)}`)
      for (const a of list(found.attributes)) {
        const value = text(a.value_text)
        if (a.is_identity === true || !value.trim()) continue
        const unit = text(a.unit)
        specs.push({ label: text(a.label) || text(a.key), value: unit ? `${value} ${unit}` : value, source: text(a.source_url) })
      }
    } catch {
      /* the risks are still here */
    }
  }
  return { lookupId, name: text(stored.label) || 'Product', category: text(stored.category), specs, risks }
}

// ---- lining up ----

export interface RiskRow {
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
  const titles: string[] = []
  for (const c of columns) for (const r of c.risks) if (!titles.includes(r.title)) titles.push(r.title)
  return titles.map((title) => {
    const cells = columns.map((c) => c.risks.find((r) => r.title === title) ?? null)
    const found = cells.filter((c): c is Risk => c !== null)
    const differs =
      found.length !== cells.length || found.some((r) => r.level !== found[0].level || r.disputed !== found[0].disputed)
    return { title, cells, differs }
  })
}

/** One row for each label that any column states. */
export function specRows(columns: Check[]): SpecRow[] {
  const labels: string[] = []
  for (const c of columns) for (const s of c.specs) if (!labels.includes(s.label)) labels.push(s.label)
  return labels.map((label) => {
    const cells = columns.map((c) => c.specs.find((s) => s.label === label) ?? null)
    const found = cells.filter((c): c is Spec => c !== null)
    const differs = found.length !== cells.length || found.some((s) => s.value !== found[0].value)
    return { label, cells, differs }
  })
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
    risks.push({
      title,
      level,
      disputed: (seed + i) % 7 === 0,
      body: `${name} has a report about ${title.toLowerCase()}. Read the sources before you buy.`,
      sources: [{ host: 'maker.example.test', url: 'https://maker.example.test', quote: `A reader reports a ${title.toLowerCase()} problem.`, stance: 'supports' }],
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

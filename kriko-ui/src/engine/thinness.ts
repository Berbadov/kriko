/** How thin a finding's evidence is, and what the reader's setting does with it.
 *
 *  The engine decides (`app/evidence.py` puts an `evidence` object on every
 *  claim row: a level and the reasons for it). This file only filters what the
 *  reader sees: it never changes a claim, and it holds no rule about a source.
 *  A claim row with no `evidence` (a check from before it existed, a demo)
 *  carries no doubt and is always drawn. */

export type Thin = 'solid' | 'partial' | 'thin'
export type Sensitivity = 'all' | 'hide_thin' | 'strict'

export interface Evidence {
  level: Thin
  reasons: { code: string; text: string }[]
}

export const SENSITIVITIES: Sensitivity[] = ['all', 'hide_thin', 'strict']

export const LEVEL_WORD: Record<Thin, string> = { solid: 'Solid', partial: 'Partial', thin: 'Thin' }

export function normalise(value: unknown): Sensitivity {
  const word = String(value ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_')
  return word === 'hide_thin' || word === 'strict' ? word : 'all'
}

/** Whether the setting draws a finding of this level. */
export function shown(level: Thin | undefined, sensitivity: Sensitivity): boolean {
  if (!level) return true
  if (sensitivity === 'strict') return level === 'solid'
  if (sensitivity === 'hide_thin') return level !== 'thin'
  return true
}

export const hiddenCount = (levels: (Thin | undefined)[], sensitivity: Sensitivity) => levels.filter((level) => !shown(level, sensitivity)).length

/** "3 thin findings hidden", or the strict step's wider reading. */
export function hiddenLine(count: number, sensitivity: Sensitivity): string {
  const noun = count === 1 ? 'finding' : 'findings'
  return sensitivity === 'strict' ? `${count} ${noun} hidden that are not fully supported` : `${count} thin ${noun} hidden`
}

/** The `evidence` object of a claim row, or nothing when the row has none. */
export function evidenceOf(raw: unknown): Evidence | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const row = raw as { level?: unknown; reasons?: unknown }
  if (row.level !== 'solid' && row.level !== 'partial' && row.level !== 'thin') return undefined
  const reasons = Array.isArray(row.reasons)
    ? row.reasons.flatMap((one) => {
        const item = one as { code?: unknown; text?: unknown }
        return typeof item?.text === 'string' ? [{ code: String(item.code ?? ''), text: item.text }] : []
      })
    : []
  return { level: row.level, reasons }
}

/** One sentence for the indicator's hover and focus. */
export function whyLine(evidence: Evidence): string {
  if (evidence.level === 'solid') return 'Solid: several trusted sources, each with its quote, and nothing left open.'
  return `${LEVEL_WORD[evidence.level]}: ${evidence.reasons.map((reason) => reason.text).join(' ')}`
}

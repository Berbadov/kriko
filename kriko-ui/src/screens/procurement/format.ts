/** Formatting shared by the Procurement desk. Numbers are shown as the engine
 *  or the reader produced them; an absent number is a word, never a zero. */

export const EMPTY = '–'

export const money = (amount: number | null | undefined, currency: string) =>
  amount == null ? EMPTY : `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}${currency ? ` ${currency}` : ''}`

export const num = (value: string): number | null => {
  const parsed = Number.parseFloat(value)
  return value.trim() === '' || !Number.isFinite(parsed) ? null : parsed
}

export const int = (value: string): number | null => {
  const parsed = Number.parseInt(value, 10)
  return value.trim() === '' || !Number.isFinite(parsed) ? null : parsed
}

export const slug = (name: string) => (name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'kriko-estimate')

/** A saved estimate's date as the reader reads it, or a dash when it has none. */
export function shortDate(iso: string | undefined): string {
  if (!iso) return EMPTY
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? EMPTY : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'unrated', 'unknown']

export const severityRank = (severity: string) => {
  const at = SEVERITY_ORDER.indexOf((severity || '').toLowerCase())
  return at === -1 ? SEVERITY_ORDER.length : at
}

/** A known problem's severity in words. */
export const SEVERITY_WORD: Record<string, string> = {
  critical: 'Serious',
  high: 'Serious',
  medium: 'Known issues',
  low: 'Minor',
  none: 'No reports',
  unrated: 'To check',
  unknown: 'To check',
}

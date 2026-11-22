import type { ReactNode } from 'react'

/** A quote's risk, said in a word as well as by the shape `.k-risk` draws. */
export type RiskLevel = 'red' | 'amber' | 'green' | 'unknown'

const WORDS: Record<RiskLevel, string> = {
  green: 'Low',
  amber: 'Medium',
  red: 'High',
  unknown: 'Not rated',
}

/** The risk level as a word and a shape. `children` is an optional note after the word. */
export function RiskMark({ level, children }: { level: RiskLevel; children?: ReactNode }) {
  const known: RiskLevel = level in WORDS ? level : 'unknown'
  return (
    <span className="k-risk" data-level={known}>
      {WORDS[known]}
      {children != null && <span className="procurement-risk-note">{children}</span>}
    </span>
  )
}

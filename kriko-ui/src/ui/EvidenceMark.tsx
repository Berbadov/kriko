import { useId } from 'react'
import { LEVEL_WORD, whyLine, type Evidence } from '../engine/thinness'

/** The small indicator next to a finding: solid, partial or thin. It says why
 *  on hover and on keyboard focus, in the engine's own words. A finding whose
 *  row carries no evidence object draws nothing rather than a guess. */
export function EvidenceMark({ evidence }: { evidence?: Evidence }) {
  const tip = useId()
  if (!evidence) return null
  const why = whyLine(evidence)
  return (
    <span className="ev-mark" data-level={evidence.level}>
      <button type="button" className="ev-dot" aria-label={`Evidence: ${why}`} aria-describedby={tip}>
        <span className="ev-glyph" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="ev-word">{LEVEL_WORD[evidence.level]}</span>
      </button>
      <span id={tip} role="tooltip" className="ev-tip">
        {why}
      </span>
    </span>
  )
}

import type { CSSProperties } from 'react'

/** A 5x5 grid of squares that twinkle in steps. It shows that work runs.
 *  The delays are fixed, so the pattern looks random and never changes. */
const DELAYS = [3, 7, 1, 9, 5, 8, 2, 6, 0, 4, 1, 9, 3, 7, 5, 6, 0, 8, 2, 4, 9, 1, 5, 3, 7]

export function PixelGlyph({
  size = 16,
  active = true,
  tone = 'accent',
}: {
  size?: number
  active?: boolean
  tone?: 'accent' | 'ink'
}) {
  const style = { '--size': `${size}px` } as CSSProperties
  return (
    <span className={`pixel-glyph tone-${tone}${active ? ' is-active' : ''}`} style={style} aria-hidden="true">
      {DELAYS.map((delay, index) => (
        <i key={index} style={{ animationDelay: `calc(${delay * 0.13}s * var(--tm))` }} data-warm={index % 7 === 3 ? '' : undefined} />
      ))}
    </span>
  )
}

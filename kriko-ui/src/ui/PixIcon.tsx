import type { CSSProperties } from 'react'
import { SIZE, draw } from '../engine/pixicons'

export type PixState = 'idle' | 'working' | 'waiting' | 'paused' | 'done' | 'failed'

/** An icon drawn in square cells (`engine/pixicons.ts`). The strokes take the
 *  colour of the text, or `tone`; the one signature cell is the brand's teal.
 *  Status moves the cells the way the logo's scan line would: while working a
 *  row of light travels down the icon, when done it travels once and the
 *  signature turns mint, when waiting the signature blinks, when failed it
 *  breaks up in red, and when paused it holds in amber. Idle is still. */
export function PixIcon({ name, size = 24, state = 'idle', tone, label }: { name: string; size?: number; state?: PixState; tone?: string; label?: string }) {
  const rows = draw(name)
  return (
    <span
      className="pix"
      data-state={state}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      style={{ '--s': `${size}px`, ...(tone ? { '--tone': tone } : {}) } as CSSProperties}
    >
      {rows.map((row, y) =>
        Array.from(row).map((ch, x) => (
          <i key={`${x}-${y}`} data-c={ch === ' ' ? undefined : ch} style={{ '--y': y, '--x': x } as CSSProperties} />
        )),
      )}
    </span>
  )
}

export const PIX_CELLS = SIZE

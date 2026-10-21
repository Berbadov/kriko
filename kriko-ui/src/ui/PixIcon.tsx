import type { CSSProperties } from 'react'
import { SIZE, draw } from '../engine/pixicons'

export type PixState = 'idle' | 'working' | 'waiting' | 'paused' | 'done' | 'failed'

/** An agent mark drawn in small square cells (`engine/pixicons.ts`). Lit cells
 *  draw the shape in `tone`, the one signature cell is the brand's teal, and the
 *  empty cells stay as faint dots, so it reads as a display. Status moves the
 *  cells: while working a wave of light crosses the icon, when done it crosses
 *  once and the signature turns mint, when waiting the signature blinks, when
 *  failed it breaks up in red, and when paused it holds in amber. Idle is still. */
export function PixIcon({ name, size = 24, state = 'idle', tone, label }: { name: string; size?: number; state?: PixState; tone?: string; label?: string }) {
  const rows = draw(name)
  return (
    <span
      className="pix"
      data-state={state}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      style={{ '--s': `${size}px`, '--n': SIZE, ...(tone ? { '--tone': tone } : {}) } as CSSProperties}
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

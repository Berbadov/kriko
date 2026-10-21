import type { CSSProperties } from 'react'
import { draw, kindOf } from '../engine/pixicons'

export type PixState = 'idle' | 'working' | 'waiting' | 'paused' | 'done' | 'failed'

/** An icon drawn in square cells (`engine/pixicons.ts`). Navigation icons are solid
 *  and take the colour of the text; agent marks are dot displays in the agent's
 *  `tone`, the empty cells staying as faint dots. The one signature cell is the
 *  brand's teal. Status moves the cells: a scan row down a navigation icon and a
 *  diagonal wave across an agent mark while working, once when done (the signature
 *  turns mint), a blinking signature when waiting, amber when paused, red and
 *  breaking up when failed. Idle is still. */
export function PixIcon({ name, size = 24, state = 'idle', tone, label }: { name: string; size?: number; state?: PixState; tone?: string; label?: string }) {
  const rows = draw(name)
  return (
    <span
      className="pix"
      data-kind={kindOf(name)}
      data-state={state}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      style={{ '--s': `${size}px`, '--n': rows.length, ...(tone ? { '--tone': tone } : {}) } as CSSProperties}
    >
      {rows.map((row, y) =>
        Array.from(row).map((ch, x) => (
          <i key={`${x}-${y}`} data-c={ch === ' ' ? undefined : ch} style={{ '--y': y, '--x': x } as CSSProperties} />
        )),
      )}
    </span>
  )
}


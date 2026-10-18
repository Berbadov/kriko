import type { CSSProperties } from 'react'

/** A bar made of square cells, in the pixel style of the glyph. */
export function PixelBar({
  value,
  active = false,
  cells = 20,
}: {
  value: number
  active?: boolean
  cells?: number
}) {
  const filled = Math.floor(Math.max(0, Math.min(1, value)) * cells)
  return (
    <span
      className="pixel-bar"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value * 100)}
      style={{ '--cells': cells } as CSSProperties}
    >
      {Array.from({ length: cells }, (_, index) => (
        <i key={index} data-on={index < filled ? '' : undefined} data-edge={active && index === filled ? '' : undefined} />
      ))}
    </span>
  )
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: readonly { value: T; label: string }[]
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          role="radio"
          aria-checked={option.value === value}
          data-on={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

export function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button className="switch" role="switch" aria-checked={on} aria-label={label} data-on={on} onClick={() => onChange(!on)}>
      <i />
    </button>
  )
}

/** A native list, dressed like the rest. The browser's own list is the one that
 *  works with a keyboard and a screen reader. */
export function Select({
  value,
  options,
  onChange,
  label,
}: {
  value: string
  options: readonly { value: string; label: string }[]
  onChange: (v: string) => void
  label: string
}) {
  return (
    <span className="select">
      <select value={value} aria-label={label} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </span>
  )
}

/** A choice that can be on or off, in a group of choices. */
export function Chip({ on, onChange, children }: { on: boolean; onChange: (v: boolean) => void; children: string }) {
  return (
    <button className="choice" role="checkbox" aria-checked={on} data-on={on} onClick={() => onChange(!on)}>
      {children}
    </button>
  )
}

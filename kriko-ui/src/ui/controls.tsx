import type { CSSProperties } from 'react'
import { stepOf } from '../engine/steps'

/** The four steps of an agent's run, in order. */
export const AGENT_STEPS = ['Find', 'Search', 'Read', 'Check'] as const

/** Where an agent's run stands as a stepper: numbered pixel tiles joined by a
 *  dashed pixel line. Done tiles are lit, the current tile carries a caret and
 *  a glow, and the line after it fills with the part of the step already done.
 *  The step is read from the progress the engine reports, in equal quarters; it
 *  does not claim a stage the engine did not name. Waiting draws every tile
 *  unlit and a finished run draws every tile done. */
export function AgentSteps({
  value,
  state,
  steps = AGENT_STEPS,
  labels = true,
}: {
  value: number
  state: 'waiting' | 'researching' | 'paused' | 'done'
  steps?: readonly string[]
  labels?: boolean
}) {
  const count = steps.length
  const fraction = Math.max(0, Math.min(1, value))
  const done = state === 'done'
  const waiting = state === 'waiting'
  const { at, within } = stepOf(fraction, state, count)
  const word = done ? 'Done' : waiting ? 'Waiting' : `Step ${at + 1} of ${count}: ${steps[at]}`
  return (
    <div
      className="pstep"
      data-state={state}
      data-labels={labels || undefined}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(fraction * 100)}
      aria-valuetext={word}
    >
      {steps.map((label, index) => {
        const mode = index < at ? 'done' : index === at ? 'now' : 'todo'
        return (
          <div key={label} className="pstep-item" data-mode={mode} style={{ '--tone': `var(--step-${index % 4})` } as CSSProperties}>
            {index > 0 && (
              <span className="pstep-link" data-lit={index <= at ? '' : undefined} data-now={index === at + 1 && state === 'researching' ? '' : undefined}>
                <i style={{ width: `${index <= at ? 100 : index === at + 1 ? within * 100 : 0}%` }} />
              </span>
            )}
            <span className="pstep-node">
              {mode === 'now' && <b className="pstep-caret" aria-hidden="true" />}
              <span className="pstep-box mono">{index + 1}</span>
              {labels && <span className="pstep-label">{label}</span>}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/** A progress bar for work with no steps (a download): pixel cells filled with
 *  the brand gradient, the percent on a small pill at the end of the fill.
 *  `sm` is the same bar without the pill, for a row with no room. */
export function ProgressBar({ value, active = false, size = 'md', tone }: { value: number; active?: boolean; size?: 'sm' | 'md'; tone?: 'warn' | 'out' }) {
  const fraction = Math.max(0, Math.min(1, value))
  const percent = Math.round(fraction * 100)
  return (
    <span
      className="pbar"
      data-size={size}
      data-tone={tone}
      data-active={active || undefined}
      data-done={percent >= 100 || undefined}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      style={{ '--p': `${fraction * 100}%` } as CSSProperties}
    >
      <span className="pbar-cells">
        <i className="pbar-fill" />
      </span>
      {size === 'md' && <b className="pbar-pill mono">{percent}%</b>}
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

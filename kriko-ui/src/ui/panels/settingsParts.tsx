import type { CSSProperties, ReactNode } from 'react'
import { Icon, type IconName } from '../Icon'

/** The pieces the Settings screen is made of, built on the shared `k-` classes.
 *
 *  A section is a caption over one card of rows. A setting is an icon tile, a
 *  label, one sentence of plain words under it (the note), the current value and
 *  one control. Nothing is explained in a tooltip: the words are on the screen.
 *  Every control carries a word, so no press is an icon alone.
 *
 *  The old names (Row, Group, Hint, State, Tile, IconChoice, IconButton, Switch,
 *  Segmented, Select) stay as thin wrappers, so the panels that still use them
 *  draw with the new look. */

/** The tile at the start of a row. Decoration: the label beside it says the same. */
export function Tile({ icon, tone }: { icon: IconName; tone?: 'warn' | 'ok' | 'risk' }) {
  return (
    <span className="k-row-icon" data-tone={tone} aria-hidden="true">
      <Icon name={icon} size={18} />
    </span>
  )
}

/** A caption in sentence case over one card of rows. `note` is one or two plain
 *  sentences under the card; `aside` sits beside the caption (a state, a count). */
export function Section({
  title,
  note,
  aside,
  tour,
  children,
}: {
  title: string
  note?: ReactNode
  aside?: ReactNode
  tour?: string
  children: ReactNode
}) {
  return (
    <section className="k-group settings-section" data-tour={tour}>
      <div className="settings-section-head">
        <h3 className="k-caption">{title}</h3>
        {aside}
      </div>
      <div className="k-card k-list">{children}</div>
      {note && <p className="settings-note">{note}</p>}
    </section>
  )
}

export interface SettingProps {
  icon?: IconName
  /** The name of the setting, as the reader says it. */
  label: string
  /** One sentence of plain words: what the setting does. */
  note?: ReactNode
  /** The current value, in muted type at the right. */
  value?: ReactNode
  /** A short state beside the label, as a pill. */
  state?: ReactNode
  /** The control. `children` does the same job. */
  control?: ReactNode
  /** Put the control under the label at full width, for a field or a wide choice. */
  stack?: boolean
  tour?: string
  id?: string
  children?: ReactNode
}

/** One setting: a row with its label, its note, its value and its control. */
export function Setting({ icon, label, note, value, state, control, stack, tour, id, children }: SettingProps) {
  const ctl = control ?? children
  return (
    <div className="k-row settings-setting" data-stack={stack || undefined} data-tour={tour} id={id} data-setting="">
      <span className="settings-setting-main">
        {icon && <Tile icon={icon} />}
        <span className="k-row-main">
          <span className="k-row-title">
            <span data-setting-label="">{label}</span>
            {state}
          </span>
          {note && <span className="k-row-note">{note}</span>}
        </span>
      </span>
      {value !== undefined && value !== null && value !== '' && <span className="k-row-value">{value}</span>}
      {ctl && <span className="k-row-control">{ctl}</span>}
    </div>
  )
}

/** A choice of a few, every option a word. The chosen one is raised on its track. */
export function Choice<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: readonly { value: T; label: string }[]
  onChange: (value: T) => void
  label: string
}) {
  return (
    <div className="k-seg settings-choice" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button key={option.value} type="button" role="radio" aria-checked={option.value === value} onClick={() => onChange(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  )
}

/** An on and off switch. The word beside it says which, so it does not rest on the knob. */
export function Toggle({ on, onChange, label, disabled }: { on: boolean; onChange: (on: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} className="settings-toggle" data-on={on} disabled={disabled} onClick={() => onChange(!on)}>
      <span className="settings-toggle-word">{on ? 'On' : 'Off'}</span>
      <span className="settings-toggle-track" aria-hidden="true">
        <i />
      </span>
    </button>
  )
}

/** A native select, named by its label. */
export function SelectField({
  value,
  options,
  onChange,
  label,
  disabled,
}: {
  value: string
  options: readonly { value: string; label: string }[]
  onChange: (value: string) => void
  label: string
  disabled?: boolean
}) {
  return (
    <select className="k-input settings-select" aria-label={label} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}

/** The swatch colours of each palette: its real ground, card, ink and brand from
 *  `src/styles/tokens.css`, so a swatch is the same whichever palette is in use. */
const SWATCHES: Record<string, { ground: string; sheet: string; ink: string; brand: string }> = {
  dark: { ground: '#08090d', sheet: '#10131a', ink: '#f6f7fa', brand: '#3562e9' },
  gray: { ground: '#202226', sheet: '#2b2e33', ink: '#f4f5f7', brand: '#7c9bff' },
  paper: { ground: '#f4f0e6', sheet: '#fffdf7', ink: '#24231f', brand: '#2e5bef' },
  white: { ground: '#f7f8fa', sheet: '#ffffff', ink: '#111318', brand: '#2e5bef' },
  system: {
    ground: 'linear-gradient(135deg, #08090d 50%, #f4f0e6 50%)',
    sheet: 'linear-gradient(135deg, #10131a 50%, #fffdf7 50%)',
    ink: '#8e95a4',
    brand: '#3562e9',
  },
}

/** A row of palette swatches, each with its word under it. The chosen one is
 *  marked by a ring and `aria-pressed`, not by a fill. */
export function ThemePicker<T extends string>({ value, options, onChange, label }: { value: T; options: readonly { value: T; label: string }[]; onChange: (value: T) => void; label: string }) {
  return (
    <div className="settings-themes" role="group" aria-label={label}>
      {options.map((option) => {
        const swatch = SWATCHES[option.value] ?? SWATCHES.dark
        const style = {
          '--sw-ground': swatch.ground,
          '--sw-sheet': swatch.sheet,
          '--sw-ink': swatch.ink,
          '--sw-brand': swatch.brand,
        } as CSSProperties
        return (
          <button key={option.value} type="button" className="settings-theme" aria-pressed={option.value === value} onClick={() => onChange(option.value)}>
            <span className="settings-swatch" style={style} aria-hidden="true">
              <i />
            </span>
            <span className="settings-theme-word">{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}

/** A row of settings with no label of its own: a line of buttons at the end. */
export function Actions({ children }: { children: ReactNode }) {
  return (
    <div className="k-row settings-actions">
      <span className="k-row-control">{children}</span>
    </div>
  )
}

/* ---- Wrappers: the old names, drawn with the new primitives. ---- */

/** A row with its label, its state and its control. `hint` becomes the note. */
export function Row({
  icon,
  label,
  state,
  hint,
  stack,
  actions,
  tour,
  children,
}: {
  icon?: IconName
  label?: string
  state?: ReactNode
  hint?: ReactNode
  stack?: boolean
  actions?: boolean
  tour?: string
  children?: ReactNode
}) {
  if (actions) return <Actions>{children}</Actions>
  return <Setting icon={icon} label={label ?? ''} state={state} note={hint} stack={stack} tour={tour} control={children} />
}

/** A section under its old name. `hint` becomes the note under the card. */
export function Group({ title, hint, tour, children }: { icon?: IconName; title: string; hint?: ReactNode; tour?: string; children: ReactNode }) {
  return (
    <Section title={title} note={hint} tour={tour}>
      {children}
    </Section>
  )
}

/** A short pill beside a label: a state, in a word or two. */
export function State({ tone = 'none', icon, children }: { tone?: 'ok' | 'warn' | 'risk' | 'none'; icon?: IconName; children: ReactNode }) {
  return (
    <span className="k-pill" data-tone={tone === 'none' ? undefined : tone}>
      {icon && <Icon name={icon} size={13} />}
      {children}
    </span>
  )
}

/** A fact a setting must keep (data that leaves, money, a key that stays). It is
 *  drawn as words under the label, never hidden behind an icon. */
export function Hint({ children, tone }: { icon?: IconName; title?: string; children: ReactNode; tone?: 'warn'; side?: 'top' | 'bottom' }) {
  return (
    <span className="settings-hint" data-tone={tone}>
      {children}
    </span>
  )
}

/** A press with a word on it. The name is the visible text unless `children` says otherwise. */
export function IconButton({
  icon,
  label,
  onClick,
  disabled,
  tone,
  type = 'button',
  children,
}: {
  icon: IconName
  label: string
  onClick?: () => void
  disabled?: boolean
  tone?: 'primary' | 'danger'
  type?: 'button' | 'submit'
  children?: ReactNode
}) {
  return (
    <button type={type} className="k-btn" data-size="sm" data-kind={tone} aria-label={label} onClick={onClick} disabled={disabled}>
      <Icon name={icon} size={16} />
      {children ?? label}
    </button>
  )
}

export interface IconOption<T extends string> {
  value: T
  label: string
  icon?: ReactNode
  hint?: string
}

/** A choice made of words. The icon and hint of an option are no longer drawn. */
export function IconChoice<T extends string>({ value, options, onChange, label }: { value: T; options: readonly IconOption<T>[]; onChange: (v: T) => void; label: string; tabs?: boolean; side?: 'top' | 'bottom' }) {
  return <Choice value={value} options={options} onChange={onChange} label={label} />
}

/** The old switch, now an on and off word beside a switch. */
export function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return <Toggle on={on} onChange={onChange} label={label} />
}

/** The old segmented control, now a word choice. */
export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: readonly { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return <Choice value={value} options={options} onChange={onChange} label={label} />
}

/** The old select, now the native select. */
export function Select({ value, options, onChange, label }: { value: string; options: readonly { value: string; label: string }[]; onChange: (v: string) => void; label: string }) {
  return <SelectField value={value} options={options} onChange={onChange} label={label} />
}

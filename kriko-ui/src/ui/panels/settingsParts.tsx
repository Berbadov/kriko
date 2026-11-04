import { useId, useState, type CSSProperties, type ReactNode } from 'react'
import { Icon, type IconName } from '../Icon'

/** The pieces the Settings drawer is made of. A row is an icon tile, a name of one
 *  or two words, and one control. What used to be a line of grey text is an icon
 *  with a tooltip (`Hint`), so the fact stays and the page stays quiet.
 *
 *  Every icon-only control here has an accessible name and a visible tooltip on
 *  hover and on keyboard focus. The motion is CSS in `settings.css`, driven
 *  through `--tm`, so reduce motion leaves the final state and nothing moves. */

/** The tile at the start of a row. Decoration: the name beside it says the same. */
export function Tile({ icon, tone }: { icon: IconName; tone?: 'warn' | 'ok' }) {
  return (
    <span className="row-icon" data-tone={tone} aria-hidden="true">
      <Icon name={icon} size={20} />
    </span>
  )
}

/** One row: tile and name on the left, one control on the right. `stack` puts the
 *  control under the name at full width, for a field or a wide choice. A row with
 *  no name (`actions`) is a line of buttons. `state` is a short pill beside the name. */
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
  return (
    <div className={`setting${stack ? ' stack' : ''}${actions ? ' actions' : ''}`} data-tour={tour}>
      {!actions && (
        <span className="row-label">
          {icon && <Tile icon={icon} />}
          {label && <span className="row-name">{label}</span>}
          {state}
          {hint}
        </span>
      )}
      <span className="row-control">{children}</span>
    </div>
  )
}

/** A group: one word as its heading, an icon before it, and a hint for the one
 *  fact it must keep. The hint sits beside the heading so the heading stays a word. */
export function Group({ icon, title, hint, tour, children }: { icon: IconName; title: string; hint?: ReactNode; tour?: string; children: ReactNode }) {
  return (
    <section className="panel-group" data-tour={tour}>
      <header className="group-head">
        <h3>
          <Icon name={icon} size={20} />
          {title}
        </h3>
        {hint}
      </header>
      {children}
    </section>
  )
}

/** A short pill beside a name: a state, in a word or two. */
export function State({ tone = 'none', icon, children }: { tone?: 'ok' | 'warn' | 'risk' | 'none'; icon?: IconName; children: ReactNode }) {
  return (
    <span className="state" data-tone={tone}>
      {icon && <Icon name={icon} size={14} />}
      {children}
    </span>
  )
}

/** The one fact a setting must keep (data that leaves, money, a key that stays,
 *  a cap that only warns), as an icon. The text shows on hover, on keyboard focus
 *  and on press, and it is the button's description for a screen reader. */
export function Hint({ icon, title, children, tone, side = 'bottom' }: { icon: IconName; title: string; children: ReactNode; tone?: 'warn'; side?: 'top' | 'bottom' }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  return (
    <span className="hint" data-open={open || undefined} data-tone={tone} data-side={side}>
      <button
        type="button"
        className="hint-btn"
        aria-label={title}
        aria-describedby={id}
        aria-expanded={open}
        onClick={() => setOpen((on) => !on)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && open) {
            event.stopPropagation()
            setOpen(false)
          }
        }}
      >
        <Icon name={icon} size={20} />
      </button>
      <span className="hint-pop" role="tooltip" id={id}>
        {children}
      </span>
    </span>
  )
}

/** A press that is only an icon. The name is its accessible name and its tooltip. */
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
    <button type={type} className="icon-act" data-tip={label} data-tone={tone} aria-label={label} onClick={onClick} disabled={disabled}>
      {children ?? <Icon name={icon} size={20} />}
    </button>
  )
}

export interface IconOption<T extends string> {
  value: T
  /** The accessible name and the tooltip. */
  label: string
  icon: ReactNode
  /** What the choice does, in the tooltip after the name. */
  hint?: string
}

/** A choice made with icons. Each one is a radio with an accessible name and a
 *  tooltip. The chosen one is filled, drawn heavier and marked by a dot beneath it,
 *  so it does not rest on colour. `tabs` also names the chosen one in words. */
export function IconChoice<T extends string>({
  value,
  options,
  onChange,
  label,
  tabs,
  side = 'top',
}: {
  value: T
  options: readonly IconOption<T>[]
  onChange: (v: T) => void
  label: string
  tabs?: boolean
  side?: 'top' | 'bottom'
}) {
  return (
    <div className="iconchoice" data-tabs={tabs || undefined} role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          aria-label={option.label}
          data-on={option.value === value}
          data-tip={option.hint ? `${option.label}. ${option.hint}` : option.label}
          data-side={side}
          onClick={() => onChange(option.value)}
        >
          <span className="ico">{option.icon}</span>
          {tabs && <span className="ico-word">{option.label}</span>}
        </button>
      ))}
    </div>
  )
}

/** Three bars that stand for a level. The bars up to the level are lit, and they
 *  rise when the level is chosen. */
export function LevelIcon({ level }: { level: 1 | 2 | 3 }) {
  return (
    <svg className="icon ico-level" viewBox="0 0 24 24" width={22} height={22} aria-hidden="true">
      {[1, 2, 3].map((n) => (
        <rect key={n} className="bar" data-lit={n <= level || undefined} style={{ '--i': n } as CSSProperties} x={3 + (n - 1) * 7} y={20 - n * 5} width={4} height={n * 5} rx={1.5} />
      ))}
    </svg>
  )
}

/** A padlock whose shackle lifts when it is open and drops when it is shut. */
export function LockIcon({ locked }: { locked: boolean }) {
  return (
    <svg className="icon ico-lock" data-locked={locked} viewBox="0 0 24 24" width={20} height={20} aria-hidden="true">
      <path className="shackle" d="M8 11V8a4 4 0 0 1 8 0v3" />
      <path d="M6 11h12v9H6z" />
    </svg>
  )
}

/** A sun and a moon that turn into view when chosen. */
export function SunIcon() {
  return (
    <span className="ico-sun">
      <Icon name="sun" size={22} />
    </span>
  )
}
export function MoonIcon() {
  return (
    <span className="ico-moon">
      <Icon name="moon" size={22} />
    </span>
  )
}

import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react'
import { useEstimates } from '../engine/estimates'
import { useHistory } from '../engine/history'
import { keepTabInside } from './focusTrap'
import { Icon } from './Icon'
import { buildItems, filterItems, liveSeams, OPEN_EVENT, type PaletteItem, type PaletteMatch, type PaletteSeams } from './paletteItems'

/** The command palette: Ctrl+Shift+P (Cmd+Shift+P on a Mac) opens one input over
 *  the places, Settings sections, actions, recent checks and estimates. The
 *  palette mounts once and draws nothing until it is opened; the data hooks run
 *  only while it is open. */

/** The most rows drawn at once. A narrower query finds the rest. */
const ROW_CAP = 50

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const openNow = useRef(false)
  /** Where focus was when the palette opened; it goes back there on close. */
  const returnTo = useRef<HTMLElement | null>(null)

  const show = useCallback(() => {
    if (openNow.current) return
    openNow.current = true
    returnTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setOpen(true)
  }, [])

  const close = useCallback(() => {
    openNow.current = false
    setOpen(false)
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || !event.shiftKey || event.key.toLowerCase() !== 'p') return
      event.preventDefault()
      if (openNow.current) close()
      else show()
    }
    const onOpen = () => show()
    window.addEventListener('keydown', onKey)
    window.addEventListener(OPEN_EVENT, onOpen)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener(OPEN_EVENT, onOpen)
    }
  }, [show, close])

  useEffect(() => {
    if (open) return
    const target = returnTo.current
    returnTo.current = null
    if (target?.isConnected) target.focus()
  }, [open])

  if (!open) return null
  return <PaletteSheet onClose={close} />
}

/** Mounted only while the palette is open, so its lists are read on open and
 *  not at startup. */
function PaletteSheet({ onClose }: { onClose: () => void }) {
  const history = useHistory('')
  const estimates = useEstimates()
  const items = useMemo(
    () => buildItems({ recent: history.items ?? [], estimates: estimates.items ?? [] }),
    [history.items, estimates.items],
  )
  return <PaletteDialog items={items} seams={liveSeams} onClose={onClose} />
}

/** The dialog itself: the input, the filtered list, and the keys that move in it. */
export function PaletteDialog({ items, seams, onClose }: { items: PaletteItem[]; seams: PaletteSeams; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const panel = useRef<HTMLDivElement>(null)
  const listId = useId()

  const found = useMemo(() => filterItems(items, query), [items, query])
  const matches = found.slice(0, ROW_CAP)
  const index = Math.min(active, Math.max(matches.length - 1, 0))
  const optionId = (at: number) => `${listId}-${at}`
  const searching = query.trim() !== ''

  useEffect(() => {
    if (matches.length) document.getElementById(`${listId}-${index}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [index, matches.length, listId])

  const choose = (match: PaletteMatch) => {
    onClose()
    match.item.run(seams)
  }

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.nativeEvent.isComposing) return
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key === 'Tab' && panel.current) {
      keepTabInside(event.nativeEvent, panel.current)
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!matches.length) return
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((index + step + matches.length) % matches.length)
      return
    }
    if (event.key === 'Enter' && matches[index]) {
      event.preventDefault()
      choose(matches[index])
    }
  }

  const rows: ReactNode[] = []
  let previous = ''
  matches.forEach((match, at) => {
    // Grouped captions only when the list is the whole catalogue in order. A query
    // mixes groups by how well they match, so each row names its group instead.
    if (!searching && match.item.group !== previous) {
      previous = match.item.group
      rows.push(
        <div key={`caption-${match.item.group}-${at}`} role="presentation" className="palette-caption">
          {match.item.group}
        </div>,
      )
    }
    rows.push(
      <div
        key={match.item.id}
        id={optionId(at)}
        role="option"
        aria-selected={at === index}
        aria-label={match.item.title}
        className="palette-row"
        onMouseMove={() => {
          if (at !== index) setActive(at)
        }}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => choose(match)}
      >
        <span className="k-row-icon">
          <Icon name={match.item.icon} size={18} />
        </span>
        <span className="palette-text">
          <span className="palette-title">
            <Highlighted text={match.item.title} marks={match.marks} />
          </span>
          {searching && <span className="palette-group">{match.item.group}</span>}
        </span>
        {match.item.hint && <kbd className="palette-hint">{match.item.hint}</kbd>}
      </div>,
    )
  })

  return (
    <div
      className="palette-scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div ref={panel} role="dialog" aria-modal="true" aria-label="Command palette" className="palette-card" onKeyDown={onKeyDown}>
        <input
          className="palette-input"
          role="combobox"
          aria-label="Find a place, an action or a check"
          aria-expanded={matches.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={matches.length ? optionId(index) : undefined}
          placeholder="Find a place, an action or a check"
          value={query}
          autoFocus
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => {
            setQuery(event.target.value)
            setActive(0)
          }}
        />
        <div className="palette-list" role="listbox" id={listId} aria-label="Matches">
          {rows}
        </div>
        {!matches.length && (
          <div className="palette-empty">
            {searching ? `Nothing matches “${query.trim()}”. Try a place, an action or a check’s name.` : 'Nothing to show yet.'}
          </div>
        )}
        <div className="palette-sr" role="status" aria-live="polite">
          {matches.length ? `${found.length} ${found.length === 1 ? 'match' : 'matches'}` : 'No matches'}
        </div>
      </div>
    </div>
  )
}

/** The title with the matched letters set apart. */
function Highlighted({ text, marks }: { text: string; marks: number[] }) {
  if (!marks.length) return <>{text}</>
  const on = new Set(marks)
  const parts: ReactNode[] = []
  let run = ''
  let marked = false
  for (let at = 0; at <= text.length; at++) {
    const next = at < text.length && on.has(at)
    if (at === text.length || next !== marked) {
      if (run) parts.push(marked ? <mark key={at}>{run}</mark> : <span key={at}>{run}</span>)
      run = ''
      marked = next
    }
    if (at < text.length) run += text[at]
  }
  return <>{parts}</>
}

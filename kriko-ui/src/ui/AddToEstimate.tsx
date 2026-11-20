import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { useEngine } from '../engine/Engine'
import { listEstimates, type EstimateQuote, type EstimateSummary } from '../engine/estimates'
import { addToEstimate } from '../engine/procurement'

/** "Add to estimate": puts a product on one of the reader's estimates, or on a
 *  new one, from any screen that knows the product. The popover lists the
 *  estimates; choosing one saves it and offers to open the Procurement screen.
 *  Needs the engine: in the demo or offline there is nothing to save to. */

interface Subject { subject_id: string; pack_id: string; label: string }

interface Props {
  subject: Subject
  quote?: Partial<EstimateQuote>
  compact?: boolean
}

const DEFAULT_NAME = 'Untitled estimate'

const messageOf = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback)

const POPOVER_WIDTH = 360
const EDGE = 16

interface Place { top?: number; bottom?: number; left: number; maxHeight: number }

/** Where the popover goes: under the button, or above it when the button is in the lower half of the window.
 *  It is never taller than the space on that side, and scrolls inside itself when it must. */
function measure(button: HTMLElement | null): Place | null {
  if (!button) return null
  const rect = button.getBoundingClientRect()
  const width = Math.min(POPOVER_WIDTH, window.innerWidth - EDGE * 2)
  const left = Math.max(EDGE, Math.min(rect.left, window.innerWidth - width - EDGE))
  return rect.bottom < window.innerHeight / 2
    ? { top: rect.bottom + 8, left, maxHeight: window.innerHeight - rect.bottom - 8 - EDGE }
    : { bottom: window.innerHeight - rect.top + 8, left, maxHeight: rect.top - 8 - EDGE }
}

export function AddToEstimate({ subject, quote, compact }: Props) {
  const { mode } = useEngine()
  const live = mode === 'live'
  const titleId = useId()
  const wrapRef = useRef<HTMLSpanElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const alive = useRef(true)

  const [open, setOpen] = useState(false)
  const [estimates, setEstimates] = useState<EstimateSummary[] | null>(null)
  const [listProblem, setListProblem] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState<{ name: string } | null>(null)
  const [newName, setNewName] = useState('')
  /** Where the popover sits, measured from the button. Fixed to the viewport so a card or list that clips does not clip it. */
  const [place, setPlace] = useState<Place | null>(null)

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  // Each opening reads the list again, so an estimate made elsewhere shows up.
  useEffect(() => {
    if (!open || !live) return
    dialogRef.current?.focus()
    listEstimates()
      .then((listed) => {
        if (!alive.current) return
        setEstimates(listed)
        setListProblem('')
      })
      .catch((reason: unknown) => {
        if (alive.current) setListProblem(messageOf(reason, 'Could not read the saved estimates.'))
      })
  }, [open, live])

  // A press outside the button and the popover closes it, without taking focus from wherever the press landed.
  useEffect(() => {
    if (!open) return
    const onPress = (event: PointerEvent) => {
      const target = event.target as Node
      if (wrapRef.current?.contains(target) || dialogRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('pointerdown', onPress)
    return () => document.removeEventListener('pointerdown', onPress)
  }, [open])

  // Keep the popover beside its button while the page moves under it.
  useEffect(() => {
    if (!open) return
    const follow = () => setPlace(measure(buttonRef.current))
    window.addEventListener('resize', follow)
    window.addEventListener('scroll', follow, true)
    return () => {
      window.removeEventListener('resize', follow)
      window.removeEventListener('scroll', follow, true)
    }
  }, [open])

  const close = (returnFocus: boolean) => {
    setOpen(false)
    if (returnFocus) buttonRef.current?.focus()
  }

  const toggle = () => {
    if (open) {
      close(true)
      return
    }
    setDone(null)
    setError('')
    setPlace(measure(buttonRef.current))
    setOpen(true)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation()
      close(true)
    }
  }

  const choose = async (target: { estimateId?: string; newName?: string }) => {
    setBusy(true)
    setError('')
    try {
      const saved = await addToEstimate({ ...target, subject, quote })
      if (alive.current) setDone({ name: saved.name || DEFAULT_NAME })
    } catch (reason) {
      if (alive.current) setError(messageOf(reason, 'Could not add it to the estimate.'))
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  const createAndAdd = (event: FormEvent) => {
    event.preventDefault()
    void choose({ newName: newName.trim() || DEFAULT_NAME })
  }

  const openEstimate = () => {
    window.dispatchEvent(new CustomEvent('kriko:navigate', { detail: { screen: 'estimate' } }))
    close(true)
  }

  return (
    <span className="procurement-add" ref={wrapRef}>
      <button
        type="button"
        className="k-btn"
        data-size={compact ? 'sm' : undefined}
        ref={buttonRef}
        disabled={!live}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={toggle}
      >
        Add to estimate
      </button>
      {mode !== 'live' && mode !== 'checking' && <span className="procurement-add-needs">Needs the engine</span>}
      {open && live && place && createPortal(
        <div
          role="dialog"
          aria-labelledby={titleId}
          className="procurement-add-pop"
          style={place}
          ref={dialogRef}
          tabIndex={-1}
          onKeyDown={onKeyDown}
        >
          <div className="procurement-add-head">
            <p id={titleId} className="procurement-add-title">Add to estimate</p>
            <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => close(true)}>Close</button>
          </div>
          {done ? (
            <div className="procurement-add-done" role="status">
              <p>Added to {done.name}.</p>
              <div className="procurement-add-actions">
                <button type="button" className="k-btn" data-kind="primary" onClick={openEstimate}>Open it</button>
              </div>
            </div>
          ) : (
            <>
              <p className="procurement-add-caption">Choose the estimate for {subject.label}.</p>
              {listProblem && <p className="k-notice" role="alert">{listProblem}</p>}
              {estimates == null && !listProblem && <p className="k-empty">Reading your estimates…</p>}
              {estimates && estimates.length === 0 && <p className="k-empty">No estimates yet. Name the first one below.</p>}
              {estimates && estimates.length > 0 && (
                <div className="k-list procurement-add-list">
                  {estimates.map((item) => {
                    const lines = item.lines_count ?? item.lines ?? 0
                    return (
                      <button
                        type="button"
                        className="k-row"
                        key={item.estimate_id}
                        disabled={busy}
                        onClick={() => void choose({ estimateId: item.estimate_id })}
                      >
                        <span className="k-row-main">
                          <span className="k-row-title">{item.name || DEFAULT_NAME}</span>
                          <span className="k-row-note">{lines} {lines === 1 ? 'line' : 'lines'} · {item.currency}</span>
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}
              <form className="procurement-add-new" onSubmit={createAndAdd}>
                <label className="procurement-add-label">
                  New estimate
                  <input
                    className="k-input"
                    value={newName}
                    placeholder="Name it"
                    onChange={(event) => setNewName(event.target.value)}
                  />
                </label>
                <button type="submit" className="k-btn" data-kind="primary" disabled={busy}>Create and add</button>
              </form>
              {error && <p className="k-notice" role="alert">{error}</p>}
              {busy && <p className="procurement-add-caption" role="status">Adding…</p>}
            </>
          )}
        </div>,
        document.body,
      )}
    </span>
  )
}

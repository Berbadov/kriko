import { useEffect, useRef, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { get } from '../engine/api'
import { Icon } from './Icon'
import { keepTabInside } from './focusTrap'

/** The small form behind "Not buying this". One line of reason and an optional
 *  price: enough for the Dodged screen to remember the decision and add up what
 *  it saved, and nothing that turns a press into a diary. */
export function DodgeDialog({ name, url, reason, add, problem, onClose, onSaved }: {
  name: string
  url: string
  /** The check's strongest concern, prefilled so the press is one more tap. */
  reason: string
  add: (name: string, price: string, currency: string, reason: string, url: string) => Promise<boolean>
  problem: string
  onClose: () => void
  onSaved: () => void
}) {
  const [price, setPrice] = useState('')
  const [currency, setCurrency] = useState('')
  const [why, setWhy] = useState(reason)
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const priceField = useRef<HTMLInputElement>(null)
  const cameFrom = useRef<HTMLElement | null>(null)

  useEffect(() => {
    cameFrom.current = document.activeElement as HTMLElement | null
    priceField.current?.focus()
    // The reader's own budget currency, when they have said one. The engine is
    // local, and this is the only call the form makes.
    let live = true
    get<{ profile: { budget: { currency: string } } }>('/api/buyer/profile')
      .then((reply) => live && setCurrency((now) => now || reply.profile?.budget?.currency || ''))
      .catch(() => undefined)
    return () => {
      live = false
      cameFrom.current?.focus()
    }
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (box.current) keepTabInside(event, box.current)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    const kept = await add(name, price, currency, why, url)
    setBusy(false)
    if (kept) onSaved()
  }

  return createPortal(
    <div className="dodge-scrim" onPointerDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div ref={box} className="dodge-dialog" role="dialog" aria-modal="true" aria-labelledby="dodge-title" aria-describedby="dodge-lead" tabIndex={-1}>
        <header className="dodge-dialog-head">
          <h2 id="dodge-title">Not buying this</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <Icon name="x" size={15} />
          </button>
        </header>
        <p id="dodge-lead" className="dodge-dialog-lead">{name}</p>
        <form onSubmit={(event) => void submit(event)}>
          <div className="dodge-row">
            <label className="dodge-field">
              <span>Price it asked <small>Optional</small></span>
              <input ref={priceField} value={price} onChange={(event) => setPrice(event.target.value)} placeholder="49.90" inputMode="decimal" aria-label="Price it asked" />
            </label>
            <label className="dodge-field dodge-currency">
              <span>Currency <small>Optional</small></span>
              <input value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase().slice(0, 8))} placeholder="EUR" aria-label="Currency" maxLength={8} />
            </label>
          </div>
          <label className="dodge-field">
            <span>Why not? <small>One line, optional</small></span>
            <input value={why} onChange={(event) => setWhy(event.target.value)} maxLength={200} aria-label="Why not" placeholder="The finding that changed your mind" />
          </label>
          {problem && <p className="error-note" role="alert">{problem}</p>}
          <div className="dodge-actions">
            <button className="btn ghost" type="button" onClick={onClose}>Cancel</button>
            <button className="btn primary" type="submit" disabled={busy}>{busy ? 'Keeping it…' : 'Keep it'}</button>
          </div>
        </form>
        <p className="dodge-dialog-note">Kept on this computer, beside what you bought. Nothing leaves the machine.</p>
      </div>
    </div>,
    document.body,
  )
}

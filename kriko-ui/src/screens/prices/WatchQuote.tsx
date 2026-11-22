import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { get } from '../../engine/api'
import type { Watch } from '../../engine/buyer'
import { useEngine } from '../../engine/Engine'
import { listEstimates, type EstimateSummary } from '../../engine/estimates'
import { addToEstimate, quoteFromWatch } from '../../engine/procurement'
import { moneyText } from '../../compare/figures'
import {
  currencyFor, DEFAULT_ESTIMATE_NAME, missingFor, NEW_ESTIMATE, QUOTE_CURRENCIES, quoteRequest, whyNotQuote,
} from './quoteRequest'
import { forgetWatchSubject, rememberWatchSubject, watchSubjectOf, type WatchSubject } from './watchSubjects'

/** "Add as a quote" on a watch. A watch is a page, not a catalog product, so
 *  the reader says which product this price is for, here, once; the choice is
 *  remembered for the next press. The quote is the page's own figure on the day
 *  of its last read, at the default VAT, and it lands on the chosen estimate. */

const messageOf = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback)

const hostOf = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export function WatchQuote({ watch }: { watch: Watch }) {
  const { mode } = useEngine()
  const live = mode === 'live'
  const why = whyNotQuote(watch, live)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const whyId = useId()

  return (
    <>
      <button
        type="button"
        className="k-btn"
        data-kind="quiet"
        data-size="sm"
        ref={buttonRef}
        disabled={!!why}
        aria-haspopup="dialog"
        aria-describedby={why ? whyId : undefined}
        onClick={() => setOpen(true)}
      >
        Add as a quote
      </button>
      {why && <span className="prices-why" id={whyId}>{why}</span>}
      {open && !why && (
        <QuoteDialog
          watch={watch}
          onClose={() => {
            setOpen(false)
            buttonRef.current?.focus()
          }}
        />
      )}
    </>
  )
}

function QuoteDialog({ watch, onClose }: { watch: Watch; onClose: () => void }) {
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const alive = useRef(true)
  const label = watch.name || hostOf(watch.url)

  const [subject, setSubject] = useState<WatchSubject | null>(() => watchSubjectOf(watch.watch_id))
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<WatchSubject[] | null>(null)
  const [searchProblem, setSearchProblem] = useState('')
  const [estimates, setEstimates] = useState<EstimateSummary[] | null>(null)
  const [listProblem, setListProblem] = useState('')
  const [estimate, setEstimate] = useState('')
  const [newName, setNewName] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [currency, setCurrency] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState<{ name: string } | null>(null)

  useEffect(() => {
    alive.current = true
    dialogRef.current?.focus()
    return () => { alive.current = false }
  }, [])

  useEffect(() => {
    listEstimates()
      .then((listed) => {
        if (!alive.current) return
        setEstimates(listed)
        setEstimate((current) => current || listed[0]?.estimate_id || NEW_ESTIMATE)
      })
      .catch((reason: unknown) => {
        if (!alive.current) return
        setListProblem(messageOf(reason, 'Could not read the saved estimates.'))
        setEstimate((current) => current || NEW_ESTIMATE)
      })
  }, [])

  // The search is debounced and a late answer for an older query is dropped.
  useEffect(() => {
    const typed = query.trim()
    if (subject || typed.length < 2) return
    let current = true
    const timer = window.setTimeout(async () => {
      try {
        // `/api/search`, not `/api/subjects/search`: the subjects route shadows that path.
        const data = await get<{ items: WatchSubject[] }>(`/api/search?q=${encodeURIComponent(typed)}&limit=12`)
        if (!current) return
        setHits(data.items ?? [])
        setSearchProblem('')
      } catch (reason) {
        if (current) setSearchProblem(messageOf(reason, 'Could not read the catalogs.'))
      }
    }, 250)
    return () => {
      current = false
      window.clearTimeout(timer)
    }
  }, [query, subject])

  const choice = { watch, subject, estimate, newName, quantity, currency }
  const missing = missingFor(choice)
  const unit = currencyFor(watch, currency)
  const preview = quoteFromWatch(watch)
  const target = estimate === NEW_ESTIMATE ? (newName.trim() || DEFAULT_ESTIMATE_NAME) : estimates?.find((one) => one.estimate_id === estimate)?.name || DEFAULT_ESTIMATE_NAME

  const pick = (hit: WatchSubject) => {
    setSubject({ subject_id: hit.subject_id, pack_id: hit.pack_id, label: hit.label })
    rememberWatchSubject(watch.watch_id, hit)
    setQuery('')
    setHits(null)
  }

  const change = () => {
    forgetWatchSubject(watch.watch_id)
    setSubject(null)
  }

  const add = async () => {
    if (missing || busy) return
    setBusy(true)
    setError('')
    try {
      const saved = await addToEstimate(quoteRequest(choice))
      if (alive.current) setDone({ name: saved.name || DEFAULT_ESTIMATE_NAME })
    } catch (reason) {
      if (alive.current) setError(messageOf(reason, 'Could not add the quote.'))
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  const openEstimate = () => {
    window.dispatchEvent(new CustomEvent('kriko:navigate', { detail: { screen: 'estimate' } }))
    onClose()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab') return
    // Keep Tab inside the dialog.
    const nodes = [...(dialogRef.current?.querySelectorAll<HTMLElement>('button, input, select, [href]') ?? [])].filter((node) => !(node as HTMLButtonElement).disabled)
    if (nodes.length === 0) return
    const first = nodes[0]
    const last = nodes[nodes.length - 1]
    const at = document.activeElement
    if (event.shiftKey && (at === first || at === dialogRef.current)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && at === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return createPortal(
    <div className="prices-scrim" onPointerDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} className="prices-dialog" ref={dialogRef} tabIndex={-1} onKeyDown={onKeyDown}>
        <div className="prices-dialog-head">
          <h2 id={titleId} className="prices-dialog-title">Add as a quote</h2>
          <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={onClose}>Close</button>
        </div>

        {done ? (
          <div className="prices-dialog-done" role="status">
            <p>Added to {done.name}.</p>
            <div className="prices-dialog-actions">
              <button type="button" className="k-btn" data-kind="primary" onClick={openEstimate}>Open it</button>
            </div>
          </div>
        ) : (
          <>
            <p className="prices-dialog-lede">The price of {label} as a quote on one of your estimates.</p>

            <div className="k-field">
              <span className="k-field-label" id={`${titleId}-product`}>Product</span>
              {subject ? (
                <div className="prices-chosen" aria-labelledby={`${titleId}-product`}>
                  <span className="prices-chosen-name">{subject.label}</span>
                  <span className="k-pill">{subject.pack_id}</span>
                  <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={change}>Change product</button>
                </div>
              ) : (
                <>
                  <input
                    className="k-input"
                    type="search"
                    value={query}
                    aria-labelledby={`${titleId}-product`}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search the catalogs by name"
                    autoComplete="off"
                  />
                  {searchProblem && <p className="k-notice" data-tone="risk" role="status">{searchProblem}</p>}
                  {hits !== null && hits.length === 0 && query.trim().length >= 2 && <p className="prices-dialog-hint">Nothing matches.</p>}
                  {hits !== null && hits.length > 0 && query.trim().length >= 2 && (
                    <ul className="prices-hits" aria-label="Matching products">
                      {hits.slice(0, 8).map((hit) => (
                        <li key={`${hit.pack_id}:${hit.subject_id}`}>
                          <button type="button" className="prices-hit" onClick={() => pick(hit)}>
                            <span className="prices-hit-name">{hit.label}</span>
                            <span className="prices-hit-pack">{hit.pack_id}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>

            <div className="prices-dialog-grid">
              <div className="k-field">
                <label htmlFor={`${titleId}-estimate`}>Estimate</label>
                <select id={`${titleId}-estimate`} className="k-input" value={estimate} disabled={estimates == null && !listProblem} onChange={(event) => setEstimate(event.target.value)}>
                  {(estimates ?? []).map((one) => <option key={one.estimate_id} value={one.estimate_id}>{one.name || DEFAULT_ESTIMATE_NAME}</option>)}
                  <option value={NEW_ESTIMATE}>A new estimate</option>
                </select>
              </div>
              <div className="k-field">
                <label htmlFor={`${titleId}-quantity`}>Quantity</label>
                <input id={`${titleId}-quantity`} className="k-input" type="number" min={1} step={1} inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} />
              </div>
            </div>
            {listProblem && <p className="k-notice" data-tone="risk" role="status">{listProblem}</p>}
            {estimate === NEW_ESTIMATE && (
              <div className="k-field">
                <label htmlFor={`${titleId}-name`}>Name of the new estimate</label>
                <input id={`${titleId}-name`} className="k-input" value={newName} onChange={(event) => setNewName(event.target.value)} placeholder={DEFAULT_ESTIMATE_NAME} />
              </div>
            )}
            {!watch.currency && (
              <div className="k-field">
                <label htmlFor={`${titleId}-currency`}>Currency of the price</label>
                <select id={`${titleId}-currency`} className="k-input" value={currency} onChange={(event) => setCurrency(event.target.value)}>
                  <option value="">Choose</option>
                  {QUOTE_CURRENCIES.map((code) => <option key={code} value={code}>{code}</option>)}
                </select>
                <span className="prices-dialog-hint">The page did not say. Kriko will not guess.</span>
              </div>
            )}

            <dl className="prices-preview" aria-label="The quote that will be created">
              <div><dt>Product</dt><dd>{subject?.label ?? 'Not chosen yet'}</dd></div>
              <div><dt>Estimate</dt><dd>{estimate ? target : 'Not chosen yet'}</dd></div>
              <div><dt>Vendor</dt><dd>{preview.vendor || 'Unknown'}</dd></div>
              <div><dt>Price</dt><dd>{moneyText(watch.last_price, unit)}</dd></div>
              <div><dt>Date</dt><dd>{preview.quote_date}</dd></div>
            </dl>
            <p className="prices-dialog-hint">The price is the page&apos;s own figure from its last read, not an offer from the seller. VAT is the default: 20%, included in the price. Change either on the estimate.</p>

            {missing && <p className="prices-dialog-hint" role="status">{missing}</p>}
            {error && <p className="k-notice" data-tone="risk" role="alert">{error}</p>}
            <div className="prices-dialog-actions">
              <button type="button" className="k-btn" data-kind="quiet" onClick={onClose}>Cancel</button>
              <button type="button" className="k-btn" data-kind="primary" disabled={!!missing || busy} onClick={() => void add()}>
                {busy ? 'Adding…' : 'Add quote'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  )
}

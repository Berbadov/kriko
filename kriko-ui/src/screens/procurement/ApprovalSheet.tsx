import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import type { Estimate } from '../../engine/estimates'
import { approvalText, buildApproval, type ApprovalProblem } from '../../engine/approval'

/** The one-page approval sheet a manager signs, shown in a dialog over the
 *  editor. Print or save as PDF uses the browser's print (approval.css hides
 *  everything but the sheet); Copy summary puts the same figures in plain text.
 */

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** A modal dialog: role, label, Escape to close, focus kept inside, and focus
 *  returned to whatever opened it. It is drawn into `body`, so print can hide the app. */
export function ModalDialog({ label, onClose, wide = false, children }: {
  label: string
  onClose: () => void
  /** A wider panel, for tables that need the room. */
  wide?: boolean
  children: ReactNode
}) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    panel.current?.focus()
    return () => {
      if (opener && document.contains(opener)) opener.focus()
    }
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !panel.current) return
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)]
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <div className="pdialog-layer" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div ref={panel} className={wide ? 'pdialog pdialog-wide' : 'pdialog'} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <header className="pdialog-head">
          <h2 id={titleId} className="pdialog-title">{label}</h2>
          <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={onClose}>Close</button>
        </header>
        {children}
      </div>
    </div>,
    document.body,
  )
}

const amount = (value: number, currency: string) => `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`

export function ApprovalSheet({ estimate, claimsByLine, onClose }: {
  estimate: Estimate
  claimsByLine: Record<string, ApprovalProblem[] | undefined>
  onClose: () => void
}) {
  const [today] = useState(() => new Date())
  const model = useMemo(() => buildApproval(estimate, claimsByLine, today), [estimate, claimsByLine, today])
  const [note, setNote] = useState('')
  const money = (value: number) => amount(value, model.currency)

  const copySummary = async () => {
    try {
      await navigator.clipboard.writeText(approvalText(model))
      setNote('Summary copied. It is plain text: paste it into an email or a note.')
    } catch {
      setNote('Could not copy here. Select the text on the sheet instead.')
    }
  }

  return (
    <ModalDialog label="Approval sheet" onClose={onClose}>
      <div className="pdialog-body">
        <div className="approval-actions approval-noprint">
          <button type="button" className="k-btn" data-kind="primary" onClick={() => window.print()}>Print or save as PDF</button>
          <button type="button" className="k-btn" data-kind="quiet" onClick={() => void copySummary()}>Copy summary</button>
          {note && <span className="approval-note" role="status">{note}</span>}
        </div>

        <article className="approval-sheet" aria-label={`Approval sheet for ${model.title}`}>
          <header className="approval-head">
            <h3 className="approval-title">{model.title}</h3>
            <dl className="approval-facts">
              <div><dt>Date</dt><dd>{model.date}</dd></div>
              <div><dt>Currency</dt><dd>{model.currency}</dd></div>
              <div><dt>Rates</dt><dd>{model.rates}</dd></div>
            </dl>
          </header>

          <section className="approval-section" aria-labelledby="approval-totals-caption">
            <h4 id="approval-totals-caption" className="approval-caption">Totals</h4>
            <table className="approval-totals">
              <thead>
                <tr><th scope="col">Net</th><th scope="col">VAT</th><th scope="col">Gross</th></tr>
              </thead>
              <tbody>
                <tr><td>{money(model.totals.net)}</td><td>{money(model.totals.vat)}</td><td>{money(model.totals.gross)}</td></tr>
              </tbody>
            </table>
            {(model.totals.withoutPrice > 0 || model.totals.withoutRate > 0) && (
              <p className="approval-small">
                {model.totals.withoutPrice > 0 && <>{model.totals.withoutPrice} {model.totals.withoutPrice === 1 ? 'line' : 'lines'} with no price, counted and not in the totals. </>}
                {model.totals.withoutRate > 0 && <>{model.totals.withoutRate} {model.totals.withoutRate === 1 ? 'line' : 'lines'} with no rate to {model.currency}, not converted.</>}
              </p>
            )}
          </section>

          <section className="approval-section" aria-labelledby="approval-lines-caption">
            <h4 id="approval-lines-caption" className="approval-caption">Products and selected quotes</h4>
            <table className="approval-table">
              <thead>
                <tr>
                  <th scope="col">Product</th>
                  <th scope="col" data-num>Qty</th>
                  <th scope="col">Selected vendor</th>
                  <th scope="col" data-num>Unit landed</th>
                  <th scope="col" data-num>Line gross</th>
                  <th scope="col">Delivery</th>
                  <th scope="col">Warranty</th>
                  <th scope="col">Valid until</th>
                  <th scope="col">Quote risk</th>
                </tr>
              </thead>
              <tbody>
                {model.lines.map((line) => (
                  <tr key={line.key} className="approval-row">
                    <td><strong>{line.product}</strong><span className="approval-small"> {line.pack}</span></td>
                    <td data-num>{line.quantity}</td>
                    <td>{line.vendor}{line.seller && <span className="approval-small"> Seller: {line.seller}</span>}</td>
                    <td data-num>{line.unitWord}</td>
                    <td data-num>{line.lineWord}</td>
                    <td>{line.delivery}</td>
                    <td>{line.warranty}</td>
                    <td>{line.validity}</td>
                    <td>
                      {line.risk}
                      {line.riskReasons[0] && <span className="approval-small approval-block">{line.riskReasons[0]}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {model.lines.length === 0 && <p className="approval-small">No products on this estimate.</p>}
          </section>

          {model.lines.some((line) => line.alternative) && (
            <section className="approval-section" aria-labelledby="approval-lost-caption">
              <h4 id="approval-lost-caption" className="approval-caption">Quote not chosen, and why it lost</h4>
              <ul className="approval-list">
                {model.lines.filter((line) => line.alternative).map((line) => (
                  <li key={line.key} className="approval-line">
                    <strong>{line.product}:</strong> {line.alternative!.vendor}. {line.alternative!.summary}
                    {line.moreQuotes > 0 && <span className="approval-small"> {line.moreQuotes} more {line.moreQuotes === 1 ? 'quote' : 'quotes'} on the estimate.</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="approval-section" aria-labelledby="approval-problems-caption">
            <h4 id="approval-problems-caption" className="approval-caption">Serious known problems</h4>
            <ul className="approval-list">
              {model.lines.map((line) => (
                <li key={line.key} className="approval-line">
                  <strong>{line.product}:</strong>{' '}
                  {line.problems === null && 'Not read yet.'}
                  {line.problems !== null && line.problems.length === 0 && (line.known ? `No serious reports among ${line.known} known.` : 'No reports in the catalog.')}
                  {line.problems !== null && line.problems.length > 0 && (
                    <ul className="approval-sublist">
                      {line.problems.map((problem, at) => <li key={at}>{problem}</li>)}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          </section>

          <section className="approval-section" aria-labelledby="approval-forecast-caption">
            <h4 id="approval-forecast-caption" className="approval-caption">Forecast over {model.forecast.years} {model.forecast.years === 1 ? 'year' : 'years'}</h4>
            <table className="approval-totals">
              <thead>
                <tr>
                  <th scope="col">Capital, paid now</th>
                  <th scope="col">Upkeep, {model.forecast.maintenancePct}% a year</th>
                  <th scope="col">Depreciation</th>
                  <th scope="col">Present value, {model.forecast.discountPct}%</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>{money(model.forecast.capital)}</td>
                  <td>{money(model.forecast.maintenance)}</td>
                  <td>{money(model.forecast.depreciation)}</td>
                  <td>{money(model.forecast.npv)}</td>
                </tr>
              </tbody>
            </table>
          </section>

          <footer className="approval-sign">
            <div><span className="approval-line-blank" /><span>Prepared by</span></div>
            <div><span className="approval-line-blank" /><span>Approved by</span></div>
            <div><span className="approval-line-blank" /><span>Date</span></div>
          </footer>
        </article>
      </div>
    </ModalDialog>
  )
}

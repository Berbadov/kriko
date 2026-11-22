import { useState } from 'react'
import { PROCUREMENT_CHANGED_EVENT } from '../../engine/procurement'
import { copyPayload } from '../../engine/scenario'
import { listEstimates, loadEstimate, saveEstimate, type Estimate, type EstimateSummary } from '../../engine/estimates'
import { EMPTY, shortDate } from './format'
import { Compare2 } from './Compare2'

/** The reader's saved estimates, as a list. Open shows the editor below; Duplicate
 *  saves a copy named "<name> (copy)" with its quotes; Compare with… reads two
 *  estimates side by side; Delete removes the estimate. A new estimate starts
 *  blank in the editor. */

export function EstimateList({ items, problem, activeId, onOpen, onDelete, onNew }: {
  items: EstimateSummary[] | null
  problem: string
  activeId: string
  onOpen: (estimateId: string) => void
  onDelete: (estimateId: string) => void
  onNew: () => void
}) {
  // A duplicate changes the list before the screen reloads it, so the list keeps the
  // fresh read until the screen hands over a new `items` array of its own.
  const [fresh, setFresh] = useState<{ base: EstimateSummary[] | null; list: EstimateSummary[] } | null>(null)
  const shown = fresh && fresh.base === items ? fresh.list : items
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState('')
  const [failure, setFailure] = useState('')
  const [comparing, setComparing] = useState<Estimate | null>(null)

  const duplicate = async (estimateId: string) => {
    setBusy(estimateId)
    setNote('')
    setFailure('')
    try {
      const source = await loadEstimate(estimateId)
      const copy = await saveEstimate(copyPayload(source))
      const listed = await listEstimates()
      setFresh({ base: items, list: listed })
      setNote(`Copied as ${copy.name}.`)
      window.dispatchEvent(new Event(PROCUREMENT_CHANGED_EVENT))
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'Could not copy the estimate.')
    } finally {
      setBusy('')
    }
  }

  const compareWith = async (estimateId: string) => {
    setBusy(estimateId)
    setFailure('')
    try {
      setComparing(await loadEstimate(estimateId))
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'Could not read that estimate.')
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="k-group procurement-estimates" aria-labelledby="procurement-estimates-caption">
      <div className="procurement-group-head">
        <span className="k-caption" id="procurement-estimates-caption">Estimates</span>
        <button type="button" className="k-btn" data-kind="primary" data-size="sm" onClick={onNew}>New estimate</button>
      </div>
      {problem && <p className="k-notice" data-tone="risk" role="status">{problem}</p>}
      {failure && <p className="k-notice" data-tone="risk" role="status">{failure}</p>}
      {note && <p className="procurement-quote-sub" role="status">{note}</p>}
      {shown && shown.length === 0 && (
        <div className="k-empty">
          <strong>No estimates yet</strong>
          <p>Start one, then add products from the catalogs. Each product can carry several vendor quotes.</p>
        </div>
      )}
      {shown && shown.length > 0 && (
        <div className="k-card k-list">
          {shown.map((item) => {
            const name = item.name || 'Untitled estimate'
            const working = busy === item.estimate_id
            return (
              <div className="k-row procurement-estimate-row" key={item.estimate_id} data-on={activeId === item.estimate_id ? 'true' : undefined}>
                <div className="k-row-main">
                  <span className="k-row-title">{name}</span>
                  <span className="k-row-note">
                    {item.currency} · {item.lines} {item.lines === 1 ? 'line' : 'lines'} · Updated {shortDate(item.updated_at)}
                  </span>
                </div>
                <span className="k-row-value">{item.years ? `${item.years} ${item.years === 1 ? 'year' : 'years'}` : EMPTY}</span>
                <span className="k-row-control procurement-estimate-actions">
                  <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => onOpen(item.estimate_id)} aria-pressed={activeId === item.estimate_id}>
                    Open
                  </button>
                  <button type="button" className="k-btn" data-kind="quiet" data-size="sm" disabled={working} onClick={() => void duplicate(item.estimate_id)} aria-label={`Duplicate ${name}`}>
                    {working ? 'Copying…' : 'Duplicate'}
                  </button>
                  <button type="button" className="k-btn" data-kind="quiet" data-size="sm" disabled={working} onClick={() => void compareWith(item.estimate_id)} aria-label={`Compare ${name} with another estimate`}>
                    Compare with…
                  </button>
                  <button type="button" className="k-btn" data-kind="danger" data-size="sm" onClick={() => onDelete(item.estimate_id)} aria-label={`Delete ${item.name || 'untitled estimate'}`}>
                    Delete
                  </button>
                </span>
              </div>
            )
          })}
        </div>
      )}
      {comparing && <Compare2 a={comparing} onClose={() => setComparing(null)} />}
    </section>
  )
}

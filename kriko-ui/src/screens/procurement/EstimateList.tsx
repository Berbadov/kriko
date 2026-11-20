import type { EstimateSummary } from '../../engine/estimates'
import { EMPTY, shortDate } from './format'

/** The reader's saved estimates, as a list. Open shows the editor below; Delete
 *  removes the estimate. A new estimate starts blank in the editor. */

export function EstimateList({ items, problem, activeId, onOpen, onDelete, onNew }: {
  items: EstimateSummary[] | null
  problem: string
  activeId: string
  onOpen: (estimateId: string) => void
  onDelete: (estimateId: string) => void
  onNew: () => void
}) {
  return (
    <section className="k-group procurement-estimates" aria-labelledby="procurement-estimates-caption">
      <div className="procurement-group-head">
        <span className="k-caption" id="procurement-estimates-caption">Estimates</span>
        <button type="button" className="k-btn" data-kind="primary" data-size="sm" onClick={onNew}>New estimate</button>
      </div>
      {problem && <p className="k-notice" data-tone="risk" role="status">{problem}</p>}
      {items && items.length === 0 && (
        <div className="k-empty">
          <strong>No estimates yet</strong>
          <p>Start one, then add products from the catalogs. Each product can carry several vendor quotes.</p>
        </div>
      )}
      {items && items.length > 0 && (
        <div className="k-card k-list">
          {items.map((item) => (
            <div className="k-row procurement-estimate-row" key={item.estimate_id} data-on={activeId === item.estimate_id ? 'true' : undefined}>
              <div className="k-row-main">
                <span className="k-row-title">{item.name || 'Untitled estimate'}</span>
                <span className="k-row-note">
                  {item.currency} · {item.lines} {item.lines === 1 ? 'line' : 'lines'} · Updated {shortDate(item.updated_at)}
                </span>
              </div>
              <span className="k-row-value">{item.years ? `${item.years} ${item.years === 1 ? 'year' : 'years'}` : EMPTY}</span>
              <span className="k-row-control procurement-estimate-actions">
                <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => onOpen(item.estimate_id)} aria-pressed={activeId === item.estimate_id}>
                  Open
                </button>
                <button type="button" className="k-btn" data-kind="danger" data-size="sm" onClick={() => onDelete(item.estimate_id)} aria-label={`Delete ${item.name || 'untitled estimate'}`}>
                  Delete
                </button>
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

import { useMemo } from 'react'
import {
  CONFIDENCE_WORD,
  LEVEL_WORD,
  LEVELS,
  countsText,
  levelOf,
  summarize,
  visibleRows,
  type Filter,
  type Level,
  type Order,
  type Resolved,
} from '../../engine/checklist'

/** Step four: what the list came to. Figures, a filter, and one row per product. */

const RISK_LEVEL: Record<Level, 'red' | 'amber' | 'green' | 'unknown'> = {
  serious: 'red',
  known: 'amber',
  minor: 'unknown',
  check: 'unknown',
  none: 'green',
  nomatch: 'unknown',
}

/** The filters offered. Minor and To check only appear when a row has them. */
const ALWAYS: Filter[] = ['all', 'serious', 'known', 'none', 'nomatch']

const NEXT_ORDER: Record<Order, Order> = { file: 'worst', worst: 'best', best: 'file' }
const ORDER_NOTE: Record<Order, string> = { file: 'in file order', worst: 'worst first', best: 'best first' }
const ARIA_SORT: Record<Order, 'none' | 'descending' | 'ascending'> = { file: 'none', worst: 'descending', best: 'ascending' }

const nounOf = (n: number) => `${n} ${n === 1 ? 'row' : 'rows'}`

export function Results({ items, filter, order, opening, onFilter, onOrder, onChoose, onOpen }: {
  items: Resolved[]
  filter: Filter
  order: Order
  /** The row whose product is being opened. */
  opening: number | null
  onFilter: (next: Filter) => void
  onOrder: (next: Order) => void
  onChoose: (row: number, subjectId: string) => void
  onOpen: (item: Resolved) => void
}) {
  const summary = useMemo(() => summarize(items), [items])
  const shown = useMemo(() => visibleRows(items, filter, order), [items, filter, order])
  const chips = (['all', ...LEVELS] as Filter[]).filter((one) => ALWAYS.includes(one) || summary.byLevel[one as Level] > 0)

  return (
    <>
      <div className="k-kpis" aria-label="Summary of the list">
        <div className="k-kpi">
          <span className="k-kpi-value">{summary.rows}</span>
          <span className="k-kpi-label">Rows checked</span>
        </div>
        <div className="k-kpi">
          <span className="k-kpi-value">{summary.matched}</span>
          <span className="k-kpi-label">Matched to a product</span>
        </div>
        <div className="k-kpi" data-tone={summary.serious ? 'risk' : undefined}>
          <span className="k-kpi-value">{summary.serious}</span>
          <span className="k-kpi-label">With serious problems</span>
        </div>
        <div className="k-kpi" data-tone={summary.known ? 'warn' : undefined}>
          <span className="k-kpi-value">{summary.known}</span>
          <span className="k-kpi-label">With known issues</span>
          <span className="k-kpi-fact">and no serious one</span>
        </div>
        <div className="k-kpi">
          <span className="k-kpi-value">{summary.nomatch}</span>
          <span className="k-kpi-label">No match</span>
        </div>
      </div>

      <div className="checklist-filters" role="group" aria-label="Show rows">
        {chips.map((one) => {
          const count = one === 'all' ? summary.rows : summary.byLevel[one as Level]
          return (
            <button key={one} type="button" className="k-chip" aria-pressed={filter === one} onClick={() => onFilter(one)}>
              {one === 'all' ? 'All' : LEVEL_WORD[one as Level]} <span className="checklist-count">{count}</span>
            </button>
          )
        })}
      </div>

      <p className="checklist-status" role="status" aria-live="polite">
        Showing {nounOf(shown.length)} of {summary.rows}, {ORDER_NOTE[order]}.
      </p>

      <div className="k-card checklist-scroll">
        <table className="k-table checklist-results">
          <caption className="checklist-sr">The checked rows</caption>
          <thead>
            <tr>
              <th scope="col" data-num>Row</th>
              <th scope="col">As typed</th>
              <th scope="col">Matched product</th>
              <th scope="col" aria-sort={ARIA_SORT[order]}>
                <button type="button" className="checklist-sort" onClick={() => onOrder(NEXT_ORDER[order])}>
                  Finding <span aria-hidden="true">{order === 'worst' ? '↓' : order === 'best' ? '↑' : ''}</span>
                  <span className="checklist-sr">, sorted {ORDER_NOTE[order]}. Press to change.</span>
                </button>
              </th>
              <th scope="col">Leading finding</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((item) => (
              <Row key={item.row} item={item} opening={opening === item.row} onChoose={onChoose} onOpen={onOpen} />
            ))}
            {shown.length === 0 && (
              <tr><td colSpan={5} className="checklist-none">No rows under this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Row({ item, opening, onChoose, onOpen }: {
  item: Resolved
  opening: boolean
  onChoose: (row: number, subjectId: string) => void
  onOpen: (item: Resolved) => void
}) {
  const level = levelOf(item)
  const counts = countsText(item)
  return (
    <tr className="checklist-row" data-level={level}>
      <td data-num>{item.row + 1}</td>
      <td className="checklist-typed">{item.name}</td>
      <td>
        {item.match && (
          <>
            <button
              type="button"
              className="checklist-open"
              aria-label={`Open ${item.match.label}, row ${item.row + 1}`}
              disabled={opening}
              onClick={() => onOpen(item)}
            >
              {item.match.label}
            </button>
            <span className="checklist-sub-note">{opening ? 'Opening…' : CONFIDENCE_WORD[item.match.confidence] ?? item.match.confidence}</span>
          </>
        )}
        {item.others.length > 0 && (
          <select
            className="k-input checklist-pick"
            aria-label={`Choose the product for row ${item.row + 1}`}
            value={item.match?.confidence === 'chosen' ? item.match.subject_id : ''}
            onChange={(event) => onChoose(item.row, event.target.value)}
          >
            <option value="">{item.match ? 'Change product' : 'Several fit. Choose one'}</option>
            {item.others.map((other) => <option key={other.subject_id} value={other.subject_id}>{other.label}</option>)}
          </select>
        )}
        {!item.match && item.others.length === 0 && <span className="checklist-sub-note">Not in your catalogs</span>}
      </td>
      <td>
        <span className="k-risk" data-level={RISK_LEVEL[level]}>{LEVEL_WORD[level]}</span>
        {counts && <span className="checklist-sub-note">{counts}</span>}
      </td>
      <td className="checklist-lead">{item.leading?.title ?? ''}</td>
    </tr>
  )
}

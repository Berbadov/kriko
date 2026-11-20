import { useEffect } from 'react'
import type { EstimateLine } from '../../engine/estimates'
import type { Rates } from '../../engine/money'
import { lineUnitGross } from '../../engine/quotes'
import { QuoteRows } from '../../ui/QuoteRows'
import { int, money, num, SEVERITY_WORD, severityRank } from './format'
import type { SubjectClaims } from './types'

/** One product on the estimate: its quantity, its quotes compared, what is
 *  known to go wrong with it, and its depreciation, which is folded away. */

const DEPRECIATION = [
  { value: 'straight_line', label: 'Straight-line' },
  { value: 'declining_balance', label: 'Declining balance' },
  { value: 'vuk', label: 'VUK (GİB rate)' },
]

const PROBLEMS_SHOWN = 8

export interface LineCardProps {
  line: EstimateLine
  index: number
  currency: string
  rates: Rates
  horizon: string
  claims: SubjectClaims | undefined
  researchNote: string
  researching: boolean
  onPatch: (index: number, patch: Partial<EstimateLine>) => void
  onRemove: (index: number) => void
  onResearch: (line: EstimateLine) => void
  onNeedClaims: (subjectId: string) => void
}

export function LineCard({ line, index, currency, rates, horizon, claims, researchNote, researching, onPatch, onRemove, onResearch, onNeedClaims }: LineCardProps) {
  const { subject_id: subjectId } = line
  useEffect(() => {
    // Read once per product; the editor de-duplicates and reports a failed read.
    onNeedClaims(subjectId)
  }, [subjectId, onNeedClaims])

  const unit = lineUnitGross(line, currency, rates)
  const lineTotal = unit == null ? null : unit * line.quantity
  const hasQuotes = (line.quotes ?? []).length > 0
  const sorted = [...(claims?.claims ?? [])].sort((a, b) => severityRank(a.severity) - severityRank(b.severity))

  return (
    <article className="k-card procurement-line" aria-label={line.label}>
      <header className="procurement-line-head">
        <div className="procurement-line-name">
          <h3>{line.label}</h3>
          <span className="k-pill">{line.pack_id}</span>
        </div>
        <label className="k-field procurement-line-qty">
          <span>Quantity</span>
          <input
            className="k-input"
            inputMode="numeric"
            value={String(line.quantity)}
            onChange={(event) => {
              const parsed = Number.parseInt(event.target.value, 10)
              onPatch(index, { quantity: Number.isFinite(parsed) && parsed > 0 ? parsed : 1 })
            }}
          />
        </label>
        <div className="procurement-line-total">
          <span className="k-caption">Line gross, {currency}</span>
          <strong data-num>{money(lineTotal, currency)}</strong>
          {unit != null && line.quantity > 1 && <span className="procurement-quote-sub">{money(unit, currency)} each</span>}
        </div>
      </header>

      <div className="procurement-line-block">
        <span className="k-caption">Quotes</span>
        {!hasQuotes && (
          <label className="k-field procurement-line-price">
            <span>Unit price on the line, {currency}</span>
            <input
              className="k-input"
              inputMode="decimal"
              value={line.unit_price == null ? '' : String(line.unit_price)}
              onChange={(event) => onPatch(index, { unit_price: num(event.target.value) })}
              placeholder="No price yet"
            />
          </label>
        )}
        <QuoteRows line={line} index={index} currency={currency} rates={rates} onChange={onPatch} />
      </div>

      <div className="procurement-line-block">
        <span className="k-caption">Known problems</span>
        {claims === undefined && <p className="procurement-quote-sub">Reading the product…</p>}
        {claims !== undefined && sorted.length === 0 && (
          <p className="procurement-none">
            <span className="procurement-severity" data-level="none">No reports</span>
            <span className="procurement-quote-sub">Research this line to look deeper.</span>
          </p>
        )}
        {sorted.length > 0 && (
          <ul className="procurement-problems">
            {sorted.slice(0, PROBLEMS_SHOWN).map((claim) => (
              <li key={claim.claim_id} className="procurement-problem">
                <span className="procurement-severity" data-level={(claim.severity || 'unknown').toLowerCase()}>
                  {SEVERITY_WORD[(claim.severity || 'unknown').toLowerCase()] ?? 'To check'}
                </span>
                <span>
                  <strong>{claim.title}</strong>
                  <span className="procurement-quote-sub">{claim.domain}{claim.via ? ` · via ${claim.via}` : ''}</span>
                </span>
              </li>
            ))}
            {sorted.length > PROBLEMS_SHOWN && <li className="procurement-quote-sub">And {sorted.length - PROBLEMS_SHOWN} more on the product page.</li>}
          </ul>
        )}
      </div>

      <details className="procurement-depreciation">
        <summary>Depreciation</summary>
        <div className="procurement-fields">
          <label className="k-field">
            <span>Method</span>
            <select className="k-input" value={line.depreciation} onChange={(event) => onPatch(index, { depreciation: event.target.value })}>
              {DEPRECIATION.map((method) => <option key={method.value} value={method.value}>{method.label}</option>)}
            </select>
          </label>
          <label className="k-field">
            <span>Useful life, years</span>
            <input className="k-input" inputMode="numeric" value={line.life_years ?? ''} placeholder={horizon} onChange={(event) => onPatch(index, { life_years: int(event.target.value) })} />
          </label>
          <label className="k-field">
            <span>Salvage, {currency}</span>
            <input className="k-input" inputMode="decimal" value={line.salvage ?? ''} onChange={(event) => onPatch(index, { salvage: num(event.target.value) })} />
          </label>
          {line.depreciation === 'vuk' && (
            <label className="k-field">
              <span>VUK rate, %</span>
              <input className="k-input" inputMode="decimal" value={line.vuk_rate ?? ''} onChange={(event) => onPatch(index, { vuk_rate: num(event.target.value) })} />
            </label>
          )}
        </div>
        <p className="procurement-quote-sub">
          {line.depreciation === 'vuk'
            ? 'Enter the rate from the GİB amortisman list. Kriko ships no rate table it cannot verify.'
            : line.depreciation === 'declining_balance'
              ? 'Twice the straight-line rate, on the falling book value.'
              : 'Cost less salvage, spread evenly over the useful life.'}
        </p>
      </details>

      {researchNote && <p className="procurement-quote-sub" role="status">{researchNote}</p>}
      <div className="estimate-line-actions">
        <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => onResearch(line)} disabled={researching} title="Heavy research for this product">
          {researching ? 'Researching…' : 'Research this product'}
        </button>
        <button type="button" className="k-btn" data-kind="danger" data-size="sm" onClick={() => onRemove(index)}>
          Remove {line.label}
        </button>
      </div>
    </article>
  )
}

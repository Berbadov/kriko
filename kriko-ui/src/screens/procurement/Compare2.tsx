import { useEffect, useMemo, useRef, useState } from 'react'
import type { CompareModel, CompareRow, CompareSide } from '../../engine/scenario'
import { compareEstimates } from '../../engine/scenario'
import { listEstimates, loadEstimate, type Estimate, type EstimateSummary } from '../../engine/estimates'
import { EMPTY, money } from './format'
import { ModalDialog } from './ApprovalSheet'

/** "Compare with…": pick a second saved estimate and read the two side by side.
 *  Lines are matched by product; a difference is shown only within one currency.
 *  Every figure is the comparison's own (`compareEstimates`), never recomputed here. */

const signed = (value: number, currency: string) => `${value > 0 ? '+' : value < 0 ? '-' : ''}${money(Math.abs(value), currency)}`

function quoteCell(side: CompareSide | null): string {
  if (!side) return 'Not in this estimate'
  return side.vendor
}

function landedCell(side: CompareSide | null, currency: string) {
  if (!side) return <span>{EMPTY}</span>
  if (side.state === 'no_price') return <span>No price</span>
  if (side.state === 'no_rate') return <span>No rate</span>
  return (
    <>
      <span>{money(side.unitGross, currency)} each</span>
      <span className="compare-sub">Line {money(side.lineGross ?? 0, currency)}, {side.quantity} {side.quantity === 1 ? 'unit' : 'units'}</span>
    </>
  )
}

function differenceCell(row: CompareRow, currency: string) {
  if (row.difference != null) {
    return <span>{row.difference === 0 ? 'Same' : signed(row.difference, currency)}</span>
  }
  return <span className="compare-sub">{row.differenceNote}</span>
}

function CompareTable({ model }: { model: CompareModel }) {
  const a = model.a
  const b = model.b
  const t = model.totals
  return (
    <>
      <div className="compare-scroll">
        <table className="k-table compare-table">
          <thead>
            <tr>
              <th scope="col">Product</th>
              <th scope="col">{a.name}: selected quote</th>
              <th scope="col" data-num>{a.name}: landed</th>
              <th scope="col">{b.name}: selected quote</th>
              <th scope="col" data-num>{b.name}: landed</th>
              <th scope="col" data-num>Difference, {model.sameCurrency ? `${b.name} minus ${a.name}` : 'not comparable'}</th>
            </tr>
          </thead>
          <tbody>
            {model.rows.map((row) => (
              <tr key={row.key} data-status={row.status}>
                <th scope="row">{row.label}</th>
                <td>{quoteCell(row.a)}</td>
                <td data-num className="compare-landed">{landedCell(row.a, a.currency)}</td>
                <td>{quoteCell(row.b)}</td>
                <td data-num className="compare-landed">{landedCell(row.b, b.currency)}</td>
                <td data-num className="compare-diff">{differenceCell(row, a.currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {model.rows.length === 0 && <p className="compare-sub">Neither estimate has a product yet.</p>}

      <h4 className="compare-caption">Totals</h4>
      <div className="compare-scroll">
        <table className="k-table compare-table compare-totals">
          <thead>
            <tr>
              <th scope="col">Totals</th>
              <th scope="col" data-num>{a.name} ({a.currency})</th>
              <th scope="col" data-num>{b.name} ({b.currency})</th>
              <th scope="col" data-num>Difference</th>
            </tr>
          </thead>
          <tbody>
            {([['Net', 'net'], ['VAT', 'vat'], ['Gross', 'gross']] as const).map(([label, key]) => (
              <tr key={key}>
                <th scope="row">{label}</th>
                <td data-num>{money(t.a[key], a.currency)}</td>
                <td data-num>{money(t.b[key], b.currency)}</td>
                <td data-num>{t.difference ? signed(t.difference[key], a.currency) : 'Not comparable'}</td>
              </tr>
            ))}
            <tr>
              <th scope="row">Lines with no price</th>
              <td data-num>{t.a.withoutPrice}</td>
              <td data-num>{t.b.withoutPrice}</td>
              <td data-num></td>
            </tr>
            <tr>
              <th scope="row">Lines with no rate</th>
              <td data-num>{t.a.withoutRate}</td>
              <td data-num>{t.b.withoutRate}</td>
              <td data-num></td>
            </tr>
          </tbody>
        </table>
      </div>
      {!model.sameCurrency && (
        <p className="compare-sub">The estimates are in different currencies. Each total stays in its own currency, and nothing is subtracted.</p>
      )}
    </>
  )
}

export function Compare2({ a, onClose }: { a: Estimate; onClose: () => void }) {
  const [candidates, setCandidates] = useState<EstimateSummary[] | null>(null)
  const [chosen, setChosen] = useState('')
  const [other, setOther] = useState<Estimate | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const alive = useRef(true)
  const request = useRef(0)

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  useEffect(() => {
    listEstimates()
      .then((items) => { if (alive.current) setCandidates(items.filter((item) => item.estimate_id !== a.estimate_id)) })
      .catch((error) => { if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not list the estimates.') })
  }, [a.estimate_id])

  const pick = async (estimateId: string) => {
    const mine = ++request.current
    setChosen(estimateId)
    setOther(null)
    setProblem('')
    if (!estimateId) return
    setBusy(true)
    try {
      const loaded = await loadEstimate(estimateId)
      if (alive.current && mine === request.current) setOther(loaded)
    } catch (error) {
      if (alive.current && mine === request.current) setProblem(error instanceof Error ? error.message : 'Could not read that estimate.')
    } finally {
      if (alive.current && mine === request.current) setBusy(false)
    }
  }

  // Recomputed when either side changes on screen, so an unsaved edit to this estimate shows.
  const model = useMemo(() => (other ? compareEstimates(a, other) : null), [a, other])
  const aName = (a.name || '').trim() || 'Untitled estimate'

  return (
    <ModalDialog label={`Compare ${aName} with another estimate`} onClose={onClose} wide>
      <div className="pdialog-body compare">
        <label className="k-field compare-pick">
          <span>Compare with</span>
          <select className="k-input" value={chosen} onChange={(event) => void pick(event.target.value)} disabled={candidates === null}>
            <option value="">Choose a saved estimate</option>
            {(candidates ?? []).map((item) => (
              <option key={item.estimate_id} value={item.estimate_id}>{item.name || 'Untitled estimate'}</option>
            ))}
          </select>
        </label>
        {candidates !== null && candidates.length === 0 && (
          <p className="compare-sub">There is no other saved estimate. Save a second one, then compare.</p>
        )}
        {busy && <p className="compare-sub" role="status">Reading the estimate…</p>}
        {problem && <p className="k-notice" data-tone="risk" role="status">{problem}</p>}
        {model && <CompareTable model={model} />}
      </div>
    </ModalDialog>
  )
}

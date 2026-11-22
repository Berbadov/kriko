import { useEffect, useMemo, useState } from 'react'
import {
  addRowsOf,
  buildEstimateLines,
  dominantCurrency,
  type Mapping,
  type Resolved,
} from '../../engine/checklist'
import { listEstimates, loadEstimate, saveEstimate, type Estimate, type EstimateSummary } from '../../engine/estimates'
import { PROCUREMENT_CHANGED_EVENT } from '../../engine/procurement'
import type { Table } from '../../engine/spreadsheet'
import { ModalDialog } from '../procurement/ApprovalSheet'

/** "Add matched rows to an estimate": pick an estimate or start one, see what would be
 *  made, and press once. Everything is saved in a single request. */

const NEW = ''
/** What a new estimate is called when the reader types nothing else. */
const DEFAULT_CURRENCY = 'USD'
/** An estimate saved with no currency reads as this one, the same as on the Procurement desk. */
const FALLBACK_CURRENCY = 'TRY'

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
const reason = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback)

export function AddDialog({ table, mapping, items, fileName, onClose, onSaved }: {
  table: Table
  mapping: Mapping
  items: Resolved[]
  fileName: string
  onClose: () => void
  onSaved: (done: { name: string; created: number; joined: number }) => void
}) {
  const [estimates, setEstimates] = useState<EstimateSummary[] | null>(null)
  const [target, setTarget] = useState(NEW)
  const [existing, setExisting] = useState<Estimate | null>(null)
  const [loading, setLoading] = useState(false)
  const [name, setName] = useState(() => fileName.replace(/\.[^.]+$/, '').trim() || 'Checked list')
  const [saving, setSaving] = useState(false)
  const [problem, setProblem] = useState('')

  useEffect(() => {
    let on = true
    listEstimates()
      .then((rows) => { if (on) setEstimates(rows) })
      .catch((error: unknown) => { if (on) { setEstimates([]); setProblem(reason(error, 'Could not read your estimates.')) } })
    return () => { on = false }
  }, [])

  const choose = (id: string) => {
    setTarget(id)
    setExisting(null)
    setProblem('')
    if (!id) return
    setLoading(true)
    loadEstimate(id)
      .then((found) => { setExisting(found) })
      .catch((error: unknown) => { setProblem(reason(error, 'Could not read that estimate.')); setTarget(NEW) })
      .finally(() => setLoading(false))
  }

  const rows = useMemo(() => addRowsOf(table, mapping, items, fileName), [table, mapping, items, fileName])
  const skipped = items.length - rows.length
  const currency = existing ? (existing.currency || FALLBACK_CURRENCY).toUpperCase() : dominantCurrency(rows) || DEFAULT_CURRENCY
  const build = useMemo(() => buildEstimateLines(rows, existing?.lines ?? [], currency), [rows, existing, currency])
  const ready = rows.length > 0 && !loading && !saving && (target !== NEW || name.trim() !== '')

  const save = async () => {
    setSaving(true)
    setProblem('')
    try {
      const saved = existing
        ? await saveEstimate({
          estimate_id: existing.estimate_id,
          name: existing.name,
          currency: existing.currency,
          years: existing.years,
          maintenance_pct: existing.maintenance_pct,
          discount_pct: existing.discount_pct,
          vat_rate: existing.vat_rate,
          fx: existing.fx,
          lines: build.lines,
        })
        : await saveEstimate({ name: name.trim(), currency, lines: build.lines })
      window.dispatchEvent(new Event(PROCUREMENT_CHANGED_EVENT))
      onSaved({ name: saved.name || name.trim(), created: build.created, joined: build.joined })
    } catch (error) {
      setProblem(reason(error, 'The estimate could not be saved. Nothing was added.'))
      setSaving(false)
    }
  }

  return (
    <ModalDialog label="Add matched rows to an estimate" onClose={onClose}>
      <div className="pdialog-body checklist-dialog">
        <div className="k-field">
          <label htmlFor="checklist-estimate">Estimate</label>
          <select id="checklist-estimate" className="k-input" value={target} onChange={(event) => choose(event.target.value)} disabled={estimates === null || saving}>
            <option value={NEW}>A new estimate</option>
            {(estimates ?? []).map((one) => <option key={one.estimate_id} value={one.estimate_id}>{one.name || 'Untitled estimate'}</option>)}
          </select>
        </div>

        {target === NEW && (
          <div className="k-field">
            <label htmlFor="checklist-estimate-name">Name of the new estimate</label>
            <input id="checklist-estimate-name" className="k-input" value={name} maxLength={200} onChange={(event) => setName(event.target.value)} />
          </div>
        )}

        <div className="checklist-preview-box" role="status" aria-live="polite" aria-label="What will be added">
          {loading ? <p>Reading the estimate…</p> : (
            <>
              <p>
                <strong>{plural(build.created, 'new line', 'new lines')}</strong> and{' '}
                <strong>{plural(build.quotes, 'quote', 'quotes')}</strong> will be added
                {build.joined > 0 && <>, and {plural(build.joined, 'line already on the estimate', 'lines already on the estimate')} will get the quotes (their quantities stay)</>}.
              </p>
              <ul className="checklist-facts">
                {build.unpriced > 0 && <li>{plural(build.unpriced, 'matched row has', 'matched rows have')} no price, so {build.unpriced === 1 ? 'it gets' : 'they get'} a line and no quote.</li>}
                {skipped > 0 && <li>{plural(skipped, 'row has', 'rows have')} no matched product and {skipped === 1 ? 'is' : 'are'} skipped.</li>}
                {build.defaulted > 0 && <li>{plural(build.defaulted, 'price names', 'prices name')} no currency, so {build.defaulted === 1 ? 'it uses' : 'they use'} {currency}, {existing ? 'this estimate’s currency' : 'the currency of your other prices, or USD when none states one'}.</li>}
                {build.quotes > 0 && <li>Each quote starts with VAT at 20%, included in the price. Change it on the estimate.</li>}
                {build.droppedQuotes > 0 && <li>{plural(build.droppedQuotes, 'quote is', 'quotes are')} left out because a line holds at most 20.</li>}
                {build.droppedLines > 0 && <li>{plural(build.droppedLines, 'row is', 'rows are')} left out because an estimate holds at most 200 lines.</li>}
                {rows.length === 0 && <li>No row has a matched product yet. Choose a product for the rows that offer a choice, then try again.</li>}
              </ul>
            </>
          )}
        </div>

        {problem && <p className="k-notice" data-tone="risk" role="alert">{problem}</p>}

        <div className="checklist-dialog-actions">
          <button type="button" className="k-btn" data-kind="quiet" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="button" className="k-btn" data-kind="primary" onClick={() => void save()} disabled={!ready}>
            {saving ? 'Adding…' : 'Add to estimate'}
          </button>
        </div>
      </div>
    </ModalDialog>
  )
}

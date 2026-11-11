import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useEngine } from '../engine/Engine'
import { get, post, seg, EngineError } from '../engine/api'
import { followJob } from '../engine/jobs'
import { forecast, type ForecastRow } from '../engine/forecast'
import { csvOf, downloadFile, xlsxOf, type Cell, type Sheet } from '../engine/sheet'
import { deleteEstimate, loadEstimate, saveEstimate, useEstimates, type Estimate, type EstimateLine } from '../engine/estimates'
import { useResearchRuns } from '../engine/research'
import { Icon } from '../ui/Icon'

/** The Estimate screen: equipment from the installed catalogs, what each costs,
 *  what is known to go wrong with it, a multi-year forecast, and the whole thing
 *  as an Excel or CSV file. Built for accountants and capital managers: every
 *  number on screen is either typed by the reader or read from the engine, and
 *  a line without a price is counted, never read as free. */

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'unrated', 'unknown']
const severityRank = (severity: string) => {
  const at = SEVERITY_ORDER.indexOf((severity || '').toLowerCase())
  return at === -1 ? SEVERITY_ORDER.length : at
}

interface SubjectHit {
  subject_id: string
  pack_id: string
  label: string
}

interface SubjectClaims {
  subject_id: string
  label: string
  pack_id: string
  claims: { claim_id: string; severity: string; domain: string; title: string; via?: string }[]
}

interface CostsPayload {
  spent: { usd?: number; runs?: number; days?: number; planes?: { plane: string; llm: string; runs: number; usd: number }[] }
  estimates: Record<string, { usd: number | null }>
}

const money = (amount: number | null | undefined, currency: string) =>
  amount == null ? '—' : `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}${currency ? ` ${currency}` : ''}`

const num = (value: string): number | null => {
  const parsed = Number.parseFloat(value)
  return value.trim() === '' || !Number.isFinite(parsed) ? null : parsed
}

const slug = (name: string) => (name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'kriko-estimate')

export function EstimateScreen() {
  const { mode, preferred } = useEngine()
  const saved = useEstimates()
  const research = useResearchRuns()

  const [estimateId, setEstimateId] = useState('')
  const [name, setName] = useState('')
  const [currency, setCurrency] = useState('USD')
  const [years, setYears] = useState('5')
  const [maintenancePct, setMaintenancePct] = useState('5')
  const [discountPct, setDiscountPct] = useState('8')
  const [lines, setLines] = useState<EstimateLine[]>([])

  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SubjectHit[] | null>(null)
  const [pickerProblem, setPickerProblem] = useState('')

  const [claims, setClaims] = useState<Record<string, SubjectClaims | null>>({})
  const [expanded, setExpanded] = useState('')
  const [researching, setResearching] = useState<Record<string, { busy: boolean; note: string }>>({})
  const [costs, setCosts] = useState<CostsPayload | null>(null)
  const [note, setNote] = useState('')
  const [problem, setProblem] = useState('')
  const [saving, setSaving] = useState(false)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  // ── the equipment picker: catalog search, or the most-claimed subjects when empty ──

  useEffect(() => {
    if (mode !== 'live') return
    const typed = query.trim()
    const timer = window.setTimeout(async () => {
      try {
        if (typed.length >= 2) {
          const data = await get<{ items: SubjectHit[] }>(`/api/subjects/search?q=${encodeURIComponent(typed)}&limit=20`)
          if (alive.current) { setHits(data.items ?? []); setPickerProblem('') }
        } else {
          const data = await get<SubjectHit[]>(`/api/subjects?limit=30`)
          if (alive.current) { setHits(Array.isArray(data) ? data : []); setPickerProblem('') }
        }
      } catch (error) {
        if (alive.current) setPickerProblem(error instanceof Error ? error.message : 'Could not read the catalogs.')
      }
    }, 250)
    return () => window.clearTimeout(timer)
  }, [query, mode])

  useEffect(() => {
    if (mode !== 'live') return
    get<CostsPayload>('/api/costs').then((data) => { if (alive.current) setCosts(data) }).catch(() => {})
  }, [mode])

  const addLine = (hit: SubjectHit) => {
    setLines((current) => current.some((l) => l.subject_id === hit.subject_id && l.pack_id === hit.pack_id)
      ? current
      : [...current, { subject_id: hit.subject_id, pack_id: hit.pack_id, label: hit.label, quantity: 1, unit_price: null, note: '' }])
    setQuery('')
  }

  const patchLine = (index: number, patch: Partial<EstimateLine>) => {
    setLines((current) => current.map((line, i) => (i === index ? { ...line, ...patch } : line)))
  }

  const loadClaims = useCallback(async (subjectId: string) => {
    const data = await get<SubjectClaims>(`/api/subjects/${seg(subjectId)}`)
    if (alive.current) setClaims((current) => ({ ...current, [subjectId]: data }))
    return data
  }, [])

  const toggleInfo = async (line: EstimateLine) => {
    if (expanded === line.subject_id) { setExpanded(''); return }
    setExpanded(line.subject_id)
    if (!claims[line.subject_id]) {
      try {
        await loadClaims(line.subject_id)
      } catch (error) {
        if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not read this product.')
      }
    }
  }

  /** Heavy research for this line: the engine's research job, followed to the end. */
  const researchLine = async (line: EstimateLine) => {
    if (mode !== 'live') return
    const mark = (busy: boolean, note: string) => {
      if (alive.current) setResearching((current) => ({ ...current, [line.subject_id]: { busy, note } }))
    }
    mark(true, 'Starting…')
    try {
      const started = await post<{ job_id: string }>('/api/research', {
        subject_id: line.subject_id, pack_id: line.pack_id, harness: preferred,
      })
      const ended = await followJob(
        started.job_id,
        (reading) => mark(true, reading.message || 'Researching…'),
        () => alive.current,
      )
      if (!ended) return
      if (ended.state !== 'succeeded') throw new EngineError(0, ended.message || `The research ${ended.state}.`)
      const fresh = await loadClaims(line.subject_id)
      mark(false, `Done — ${fresh.claims.length} known issues`)
      void research.reload()
    } catch (error) {
      mark(false, error instanceof Error ? error.message : 'The research failed.')
    }
  }

  // ── save / load / delete ──

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (mode !== 'live') return
    setSaving(true)
    setNote('')
    setProblem('')
    try {
      const savedEstimate = await saveEstimate({
        estimate_id: estimateId,
        name: name.trim() || 'Untitled estimate',
        currency: currency.trim() || 'USD',
        years: num(years) ?? 5,
        maintenance_pct: num(maintenancePct) ?? 5,
        discount_pct: num(discountPct) ?? 8,
        lines,
      })
      if (!alive.current) return
      setEstimateId(savedEstimate.estimate_id)
      setName(savedEstimate.name)
      setCurrency(savedEstimate.currency)
      setYears(String(savedEstimate.years))
      setMaintenancePct(String(savedEstimate.maintenance_pct))
      setDiscountPct(String(savedEstimate.discount_pct))
      setLines(savedEstimate.lines.map((l) => ({ ...l })))
      await saved.reload()
      setNote('Saved.')
    } catch (error) {
      if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not save the estimate.')
    } finally {
      if (alive.current) setSaving(false)
    }
  }

  const load = async (id: string) => {
    if (mode !== 'live' || !id) return
    setProblem('')
    try {
      const estimate: Estimate = await loadEstimate(id)
      if (!alive.current) return
      setEstimateId(estimate.estimate_id)
      setName(estimate.name)
      setCurrency(estimate.currency)
      setYears(String(estimate.years))
      setMaintenancePct(String(estimate.maintenance_pct))
      setDiscountPct(String(estimate.discount_pct))
      setLines(estimate.lines.map((l) => ({ ...l })))
      setExpanded('')
      setNote('Loaded.')
    } catch (error) {
      if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not load the estimate.')
    }
  }

  const removeSaved = async (id: string) => {
    if (mode !== 'live') return
    try {
      await deleteEstimate(id)
      await saved.reload()
      if (id === estimateId) {
        setEstimateId('')
        setLines([])
        setName('')
      }
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not delete the estimate.')
    }
  }

  // ── the numbers ──

  const model = useMemo(() => forecast(
    lines.map((l) => ({ quantity: l.quantity, unit_price: l.unit_price })),
    { years: num(years) ?? 5, maintenance_pct: num(maintenancePct) ?? 5, discount_pct: num(discountPct) ?? 8 },
  ), [lines, years, maintenancePct, discountPct])

  // ── export ──

  const estimateSheet = (): Sheet => {
    const rows: Cell[][] = [
      [name.trim() || 'Untitled estimate', '', `Currency: ${currency}`],
      [],
      ['Equipment', 'Catalog', 'Qty', `Unit price (${currency})`, `Line total (${currency})`, 'Note'],
      ...lines.map((line) => [
        line.label,
        line.pack_id,
        line.quantity,
        line.unit_price ?? '',
        line.unit_price == null ? '' : line.quantity * line.unit_price,
        line.note,
      ]),
      [],
      ['Subtotal', '', '', '', model.capital, model.unpriced ? `${model.unpriced} line(s) unpriced` : ''],
      ['Research spend so far', '', '', '', research.usage?.spent_usd ?? '', research.usage ? `${research.usage.runs} run(s), ${research.usage.claims} claims kept` : ''],
    ]
    if (costs) {
      rows.push(['Next research run, estimated', ...Object.entries(costs.estimates).map(([plane, est]) => `${plane}: ${est.usd == null ? 'not enough history yet' : money(est.usd, 'USD')}`)])
    }
    return { name: 'Estimate', rows }
  }

  const forecastSheet = (): Sheet => {
    const rows: Cell[][] = [
      ['Forecast', `Currency: ${currency}`, `Years: ${num(years) ?? 5}`, `Upkeep %/yr: ${num(maintenancePct) ?? 5}`, `Discount %: ${num(discountPct) ?? 8}`],
      [],
      ['Year', 'Capital', 'Maintenance', 'Depreciation', 'Cash', 'Discounted', 'Cumulative'],
      ...model.rows.map((row: ForecastRow) => [row.year, row.capital, row.maintenance, row.depreciation, row.cash, row.discounted, row.cumulative]),
      [],
      ['Total', model.capital, model.maintenance, model.depreciation, model.cash, '', ''],
      ['NPV (discounted cash)', model.npv, '', '', '', '', ''],
    ]
    return { name: 'Forecast', rows }
  }

  const researchSheet = (): Sheet => {
    const rows: Cell[][] = [['Equipment', 'Catalog', 'Severity', 'Domain', 'Known issue']]
    for (const line of lines) {
      const found = claims[line.subject_id]
      if (!found) continue
      const sorted = [...found.claims].sort((a, b) => severityRank(a.severity) - severityRank(b.severity))
      for (const claim of sorted) {
        rows.push([line.label, line.pack_id, claim.severity, claim.domain, claim.via ? `${claim.title} (via ${claim.via})` : claim.title])
      }
      if (sorted.length === 0) rows.push([line.label, line.pack_id, '', '', 'No known issues in the catalog yet — research it.'])
    }
    return { name: 'Research', rows }
  }

  const costsSheet = (): Sheet => {
    const rows: Cell[][] = [
      ['Research costs', '', ''],
      ['Spent so far (USD)', research.usage?.spent_usd ?? 'not metered', ''],
      ['Runs', research.usage?.runs ?? 0, `${research.usage?.claims ?? 0} claims kept`],
    ]
    if (costs) {
      rows.push([], ['Next research run, estimated by plane', '', ''])
      for (const [plane, est] of Object.entries(costs.estimates)) {
        rows.push([plane, est.usd == null ? 'not enough history yet' : `$${est.usd.toFixed(4)}`, ''])
      }
    }
    return { name: 'Costs', rows }
  }

  const exportCsv = () => {
    const base = slug(name)
    downloadFile(`${base}.csv`, csvOf(estimateSheet().rows), 'text/csv;charset=utf-8')
  }

  const exportXlsx = () => {
    const base = slug(name)
    downloadFile(`${base}.xlsx`, xlsxOf([estimateSheet(), forecastSheet(), researchSheet(), costsSheet()]), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
  }

  // ── render ──

  if (mode !== 'live') {
    return (
      <section className="estimate">
        <header className="estimate-head">
          <div className="hello-index mono" aria-hidden="true">04 / estimate</div>
          <h1>Estimate</h1>
          <p className="muted">Connect the engine to build a cost estimate from the installed catalogs and export it as Excel or CSV.</p>
        </header>
      </section>
    )
  }

  return (
    <section className="estimate">
      <header className="estimate-head">
        <div className="hello-index mono" aria-hidden="true">04 / estimate</div>
        <h1>Estimate</h1>
        <p className="muted">Pick equipment from the catalogs, price it, forecast it, and take the file. Research a line for what is known to go wrong with it.</p>
      </header>

      <form className="estimate-bar" onSubmit={(event) => void save(event)}>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Estimate name" aria-label="Estimate name" maxLength={200} />
        <input className="estimate-currency" value={currency} onChange={(event) => setCurrency(event.target.value)} placeholder="USD" aria-label="Currency" maxLength={8} />
        {saved.items && saved.items.length > 0 && (
          <select value={estimateId} onChange={(event) => void load(event.target.value)} aria-label="Saved estimates">
            <option value="">Load a saved estimate…</option>
            {saved.items.map((item) => (
              <option key={item.estimate_id} value={item.estimate_id}>{item.name} ({item.lines} lines)</option>
            ))}
          </select>
        )}
        <button className="btn primary" type="submit" disabled={saving}>
          <Icon name="check" size={15} /> {saving ? 'Saving…' : estimateId ? 'Save changes' : 'Save'}
        </button>
        {estimateId && (
          <button className="btn ghost" type="button" onClick={() => void removeSaved(estimateId)}>
            <Icon name="trash" size={15} /> Delete
          </button>
        )}
        <span className="estimate-bar-spacer" />
        <button className="btn" type="button" onClick={exportCsv} disabled={!lines.length} title="The estimate table as CSV">
          <Icon name="download" size={15} /> CSV
        </button>
        <button className="btn" type="button" onClick={exportXlsx} disabled={!lines.length} title="Estimate, forecast, research and costs as one .xlsx workbook">
          <Icon name="download" size={15} /> Excel
        </button>
      </form>
      {(note || problem || saved.problem) && (
        <p className={problem || saved.problem ? 'error-note' : 'estimate-note'} role="status">{problem || saved.problem || note}</p>
      )}

      <div className="estimate-picker">
        <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search the catalogs for equipment… (empty: most-claimed products)" aria-label="Search the catalogs" />
        {pickerProblem && <p className="error-note">{pickerProblem}</p>}
        {hits !== null && hits.length === 0 && <span className="muted">Nothing matches.</span>}
        <ul className="estimate-hits">
          {(hits ?? []).slice(0, 12).map((hit) => (
            <li key={`${hit.pack_id}:${hit.subject_id}`}>
              <button className="chip" onClick={() => addLine(hit)} disabled={lines.some((l) => l.subject_id === hit.subject_id && l.pack_id === hit.pack_id)}>
                <strong>{hit.label}</strong>
                <span className="muted">{hit.pack_id}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {lines.length === 0 ? (
        <p className="muted estimate-empty">No equipment yet. Search above and add a line — or load a saved estimate.</p>
      ) : (
        <table className="estimate-lines">
          <thead>
            <tr><th>Equipment</th><th>Catalog</th><th className="num">Qty</th><th className="num">Unit price</th><th className="num">Line total</th><th></th></tr>
          </thead>
          <tbody>
            {lines.map((line, index) => (
              <Fragment key={`${line.pack_id}:${line.subject_id}`}>
                <tr>
                  <td><strong>{line.label}</strong></td>
                  <td className="mono muted">{line.pack_id}</td>
                  <td className="num"><input inputMode="numeric" value={String(line.quantity)} onChange={(event) => { const v = Number.parseInt(event.target.value, 10); patchLine(index, { quantity: Number.isFinite(v) && v > 0 ? v : 1 }) }} aria-label="Quantity" /></td>
                  <td className="num"><input inputMode="decimal" value={line.unit_price == null ? '' : String(line.unit_price)} onChange={(event) => patchLine(index, { unit_price: num(event.target.value) })} placeholder="—" aria-label={`Unit price for ${line.label}`} /></td>
                  <td className="num mono">{line.unit_price == null ? '—' : money(line.quantity * line.unit_price, currency)}</td>
                  <td className="estimate-line-actions">
                    <button className="icon-btn" onClick={() => void toggleInfo(line)} aria-label={`Product information for ${line.label}`} title="Product information">
                      <Icon name={expanded === line.subject_id ? 'collapse' : 'expand'} size={15} />
                    </button>
                    <button className="icon-btn" onClick={() => void researchLine(line)} disabled={researching[line.subject_id]?.busy ?? false} aria-label={`Research ${line.label}`} title="Heavy research for this product">
                      <Icon name="search" size={15} />
                    </button>
                    <button className="icon-btn" onClick={() => setLines((current) => current.filter((_, i) => i !== index))} aria-label={`Remove ${line.label}`} title="Remove">
                      <Icon name="x" size={15} />
                    </button>
                  </td>
                </tr>
                {researching[line.subject_id] && (
                  <tr className="estimate-sub"><td colSpan={6}><span className="muted">{researching[line.subject_id].note}</span></td></tr>
                )}
                {expanded === line.subject_id && (
                  <tr className="estimate-sub">
                    <td colSpan={6}>
                      {(() => {
                        const found = claims[line.subject_id]
                        if (!found) return <span className="muted">Reading the product…</span>
                        const sorted = [...found.claims].sort((a, b) => severityRank(a.severity) - severityRank(b.severity))
                        if (!sorted.length) return <span className="muted">The catalog knows no issues for this one yet. Press the research button to look deeper.</span>
                        return (
                          <ul className="estimate-claims">
                            {sorted.slice(0, 8).map((claim) => (
                              <li key={claim.claim_id}>
                                <span className="level" data-level={(claim.severity || 'unknown').toLowerCase()}>{claim.severity}</span>
                                <strong>{claim.title}</strong>
                                <span className="muted">{claim.domain}{claim.via ? ` · via ${claim.via}` : ''}</span>
                              </li>
                            ))}
                            {sorted.length > 8 && <li className="muted">…and {sorted.length - 8} more in the product page.</li>}
                          </ul>
                        )
                      })()}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}

      <section className="estimate-forecast">
        <div className="estimate-forecast-bar">
          <h2>Forecast</h2>
          <label>Years <input inputMode="numeric" value={years} onChange={(event) => setYears(event.target.value)} aria-label="Forecast years" /></label>
          <label>Upkeep %/yr <input inputMode="decimal" value={maintenancePct} onChange={(event) => setMaintenancePct(event.target.value)} aria-label="Maintenance percent per year" /></label>
          <label>Discount % <input inputMode="decimal" value={discountPct} onChange={(event) => setDiscountPct(event.target.value)} aria-label="Discount percent" /></label>
        </div>
        <table className="estimate-table">
          <thead>
            <tr><th className="num">Year</th><th className="num">Capital</th><th className="num">Maintenance</th><th className="num">Depreciation</th><th className="num">Cash</th><th className="num">Discounted</th><th className="num">Cumulative</th></tr>
          </thead>
          <tbody>
            {model.rows.map((row) => (
              <tr key={row.year}>
                <td className="num mono">{row.year}</td>
                <td className="num mono">{row.capital ? money(row.capital, currency) : ''}</td>
                <td className="num mono">{row.maintenance ? money(row.maintenance, currency) : ''}</td>
                <td className="num mono">{row.depreciation ? money(row.depreciation, currency) : ''}</td>
                <td className="num mono">{money(row.cash, currency)}</td>
                <td className="num mono">{money(row.discounted, currency)}</td>
                <td className="num mono">{money(row.cumulative, currency)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td className="num">Total</td>
              <td className="num mono">{money(model.capital, currency)}</td>
              <td className="num mono">{money(model.maintenance, currency)}</td>
              <td className="num mono">{money(model.depreciation, currency)}</td>
              <td className="num mono">{money(model.cash, currency)}</td>
              <td className="num mono" colSpan={2}>NPV {money(model.npv, currency)}</td>
            </tr>
          </tfoot>
        </table>
        <p className="muted">
          Subtotal {money(model.capital, currency)}
          {model.unpriced > 0 && <> · <strong>{model.unpriced} line{model.unpriced === 1 ? '' : 's'}</strong> without a price, not counted</>}
          {' · '}research so far {research.usage?.spent_usd != null ? `$${research.usage.spent_usd.toFixed(2)}` : 'not metered'} over {research.usage?.runs ?? 0} run(s)
        </p>
      </section>
    </section>
  )
}

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useEngine } from '../../engine/Engine'
import { get, post, seg, EngineError } from '../../engine/api'
import { followJob } from '../../engine/jobs'
import { forecast, type CostLine } from '../../engine/forecast'
import { rateOf } from '../../engine/money'
import { csvOf, downloadFile, xlsxOf } from '../../engine/sheet'
import { estimateSheet, workbookSheets, type ExportInput, type KnownProblem } from '../../engine/estimateExport'
import { chosenQuote, lineUnitGross } from '../../engine/quotes'
import { deleteEstimate, fetchTcmbRates, loadEstimate, saveEstimate, type Estimate, type EstimateLine } from '../../engine/estimates'
import { useResearchRuns } from '../../engine/research'
import { AddProduct } from './AddProduct'
import { ForecastCard } from './ForecastCard'
import { LineCard } from './LineCard'
import { num, slug } from './format'
import type { CostsPayload, SubjectClaims, SubjectHit } from './types'

/** One estimate open for editing: its settings, exchange rates, products with
 *  their quotes, the forecast and the exports. Every number on screen is typed
 *  by the reader or read from the engine; a line without a price is counted,
 *  never read as free, and a quote with no rate is shown as uncomparable.
 */

const QUOTE_CURRENCIES = ['TRY', 'EUR', 'USD']
const TCMB_URL = 'https://www.tcmb.gov.tr/kurlar/today.xml'

const emptyLine = (hit: SubjectHit): EstimateLine => ({
  subject_id: hit.subject_id,
  pack_id: hit.pack_id,
  label: hit.label,
  quantity: 1,
  unit_price: null,
  note: '',
  depreciation: 'straight_line',
  life_years: null,
  salvage: null,
  vuk_rate: null,
  quotes: [],
})

export function EstimateEditor({ target, onSaved, onDeleted, onClose }: {
  /** '' for a new estimate, otherwise the saved estimate's id. */
  target: string
  onSaved: (estimate: Estimate) => void
  onDeleted: (estimateId: string) => void
  onClose: () => void
}) {
  const { mode, preferred } = useEngine()
  const research = useResearchRuns()

  const [loading, setLoading] = useState(target !== '')
  const [estimateId, setEstimateId] = useState('')
  const [name, setName] = useState('')
  const [currency, setCurrency] = useState('TRY')
  const [vatRate, setVatRate] = useState('20')
  const [fx, setFx] = useState<Record<string, number | string>>({ TRY: 1, EUR: 0, USD: 0, source: 'manual' })
  const [years, setYears] = useState('5')
  const [maintenancePct, setMaintenancePct] = useState('5')
  const [discountPct, setDiscountPct] = useState('8')
  const [lines, setLines] = useState<EstimateLine[]>([])

  const [claims, setClaims] = useState<Record<string, SubjectClaims | undefined>>({})
  const requested = useRef(new Set<string>())
  const [researching, setResearching] = useState<Record<string, { busy: boolean; note: string }>>({})
  const [costs, setCosts] = useState<CostsPayload | null>(null)
  const [note, setNote] = useState('')
  const [problem, setProblem] = useState('')
  const [ratesNote, setRatesNote] = useState('')
  const [fetchingRates, setFetchingRates] = useState(false)
  const [saving, setSaving] = useState(false)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  const applyEstimate = useCallback((estimate: Estimate) => {
    setEstimateId(estimate.estimate_id)
    setName(estimate.name)
    setCurrency(estimate.currency)
    setVatRate(String(estimate.vat_rate ?? 20))
    setFx({ TRY: 1, EUR: 0, USD: 0, ...(estimate.fx ?? {}) })
    setYears(String(estimate.years))
    setMaintenancePct(String(estimate.maintenance_pct))
    setDiscountPct(String(estimate.discount_pct))
    setLines(estimate.lines.map((line) => ({ ...line, quotes: (line.quotes ?? []).map((quote) => ({ ...quote })) })))
  }, [])

  // Open the estimate named by `target`; a new one starts blank.
  useEffect(() => {
    if (target === '' || mode !== 'live') return
    let cancelled = false
    loadEstimate(target)
      .then((estimate) => { if (!cancelled && alive.current) { applyEstimate(estimate); setLoading(false) } })
      .catch((error) => { if (!cancelled && alive.current) { setProblem(error instanceof Error ? error.message : 'Could not load the estimate.'); setLoading(false) } })
    return () => { cancelled = true }
  }, [target, mode, applyEstimate])

  useEffect(() => {
    if (mode !== 'live') return
    get<CostsPayload>('/api/costs').then((data) => { if (alive.current) setCosts(data) }).catch(() => {})
  }, [mode])

  // ── products ──

  const loadClaims = useCallback(async (subjectId: string) => {
    const data = await get<SubjectClaims>(`/api/subjects/${seg(subjectId)}`)
    if (alive.current) setClaims((current) => ({ ...current, [subjectId]: data }))
    return data
  }, [])

  /** Read a product's known problems once; a failed read is reported, not retried in a loop. */
  const needClaims = useCallback((subjectId: string) => {
    if (requested.current.has(subjectId)) return
    requested.current.add(subjectId)
    loadClaims(subjectId).catch((error) => {
      if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not read this product.')
    })
  }, [loadClaims])

  const addLine = (hit: SubjectHit) => {
    setLines((current) => current.some((l) => l.subject_id === hit.subject_id && l.pack_id === hit.pack_id)
      ? current
      : [...current, emptyLine(hit)])
  }

  const patchLine = useCallback((index: number, patch: Partial<EstimateLine>) => {
    setLines((current) => current.map((line, i) => (i === index ? { ...line, ...patch } : line)))
  }, [])

  const removeLine = (index: number) => setLines((current) => current.filter((_, i) => i !== index))

  /** Heavy research for this line: the engine's research job, followed to the end. */
  const researchLine = async (line: EstimateLine) => {
    if (mode !== 'live') return
    const mark = (busy: boolean, text: string) => {
      if (alive.current) setResearching((current) => ({ ...current, [line.subject_id]: { busy, note: text } }))
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
      mark(false, `Done. ${fresh.claims.length} ${fresh.claims.length === 1 ? 'risk' : 'risks'} kept.`)
      void research.reload()
    } catch (error) {
      mark(false, error instanceof Error ? error.message : 'The research failed.')
    }
  }

  // ── save / delete ──

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (mode !== 'live') return
    setSaving(true)
    setNote('')
    setProblem('')
    try {
      const saved = await saveEstimate({
        estimate_id: estimateId,
        name: name.trim() || 'Untitled estimate',
        currency: currency.trim() || 'TRY',
        years: num(years) ?? 5,
        maintenance_pct: num(maintenancePct) ?? 5,
        discount_pct: num(discountPct) ?? 8,
        vat_rate: num(vatRate) ?? 20,
        fx,
        lines,
      })
      if (!alive.current) return
      applyEstimate(saved)
      onSaved(saved)
      setNote('Saved.')
    } catch (error) {
      if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not save the estimate.')
    } finally {
      if (alive.current) setSaving(false)
    }
  }

  const removeSaved = async () => {
    if (mode !== 'live' || !estimateId) return
    try {
      await deleteEstimate(estimateId)
      onDeleted(estimateId)
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not delete the estimate.')
    }
  }

  // ── rates ──

  const setRate = (code: string, value: string) => {
    setFx((current) => ({ ...current, [code]: num(value) ?? 0, source: 'manual' }))
  }

  const fetchRates = async () => {
    setFetchingRates(true)
    setRatesNote('')
    try {
      const payload = await fetchTcmbRates()
      if (!alive.current) return
      setFx({ ...payload.rates, source: payload.source, date: payload.date, url: TCMB_URL })
      setRatesNote(`TCMB bulletin ${payload.date}, TRY per one unit.`)
    } catch (error) {
      if (alive.current) setRatesNote(error instanceof Error ? error.message : 'Could not fetch the rates.')
    } finally {
      if (alive.current) setFetchingRates(false)
    }
  }

  // ── the numbers ──

  const model = useMemo(() => forecast(
    lines.map((line): CostLine => {
      const base = {
        quantity: line.quantity,
        depreciation: line.depreciation,
        life_years: line.life_years,
        salvage: line.salvage,
        vuk_rate: line.vuk_rate,
      }
      // The selected quote's gross in the estimate currency, with its own VAT rate.
      // A line with no quote keeps its price as typed, read as VAT-free.
      const unit = lineUnitGross(line, currency, fx)
      const quote = chosenQuote(line)
      if (!quote) return { ...base, unit_price: unit, vat_rate: 0, vat_included: false }
      return { ...base, unit_price: unit, vat_rate: quote.vat_rate, vat_included: true }
    }),
    { years: num(years) ?? 5, maintenance_pct: num(maintenancePct) ?? 5, discount_pct: num(discountPct) ?? 8 },
  ), [lines, years, maintenancePct, discountPct, currency, fx])

  const rateWarning = QUOTE_CURRENCIES.filter((code) => code !== currency && rateOf(code, fx) == null)

  // ── export ──

  const exportInput = (): ExportInput => {
    const problems: Record<string, KnownProblem[] | undefined> = {}
    for (const [subjectId, found] of Object.entries(claims)) problems[subjectId] = found?.claims
    return {
      name,
      currency,
      vatRate: num(vatRate) ?? 20,
      years: num(years) ?? 5,
      maintenancePct: num(maintenancePct) ?? 5,
      discountPct: num(discountPct) ?? 8,
      fx,
      lines,
      model,
      usage: research.usage ?? null,
      problems,
      costs,
    }
  }

  const exportCsv = () => {
    downloadFile(`${slug(name)}.csv`, csvOf(estimateSheet(exportInput()).rows), 'text/csv;charset=utf-8')
  }

  const exportXlsx = () => {
    downloadFile(`${slug(name)}.xlsx`, xlsxOf(workbookSheets(exportInput())), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
  }

  // ── render ──

  const title = name.trim() || 'New estimate'
  const researchSoFar = research.usage?.spent_usd != null
    ? `Research so far: $${research.usage.spent_usd.toFixed(2)} over ${research.usage.runs ?? 0} run(s).`
    : `Research so far: not metered over ${research.usage?.runs ?? 0} run(s).`

  if (loading) {
    return <section className="k-card procurement-editor" aria-busy="true"><p className="procurement-quote-sub">Reading the estimate…</p></section>
  }

  return (
    <section className="procurement-editor" aria-label={`Estimate ${title}`}>
      <form className="procurement-editor-form" onSubmit={(event) => void save(event)}>
        <div className="procurement-editor-head">
          <h2 className="procurement-editor-title">{title}</h2>
          <div className="k-head-actions">
            <button type="submit" className="k-btn" data-kind="primary" disabled={saving}>
              {saving ? 'Saving…' : estimateId ? 'Save changes' : 'Save estimate'}
            </button>
            {estimateId && (
              <button type="button" className="k-btn" data-kind="danger" onClick={() => void removeSaved()}>Delete estimate</button>
            )}
            <button type="button" className="k-btn" data-kind="quiet" onClick={onClose}>Close</button>
          </div>
        </div>
        {(note || problem) && (
          <p className="k-notice" data-tone={problem ? 'risk' : undefined} role="status">{problem || note}</p>
        )}

        <div className="k-group">
          <span className="k-caption">Estimate settings</span>
          <div className="k-card procurement-settings" data-pad>
            <label className="k-field procurement-settings-name">
              <span>Estimate name</span>
              <input className="k-input" value={name} onChange={(event) => setName(event.target.value)} maxLength={200} placeholder="Untitled estimate" />
            </label>
            <label className="k-field">
              <span>Currency of the estimate</span>
              <select className="k-input" value={currency} onChange={(event) => setCurrency(event.target.value)}>
                {QUOTE_CURRENCIES.map((code) => <option key={code} value={code}>{code}</option>)}
              </select>
            </label>
            <label className="k-field">
              <span>Forecast years</span>
              <input className="k-input" inputMode="numeric" value={years} onChange={(event) => setYears(event.target.value)} />
            </label>
            <label className="k-field">
              <span>Upkeep, % of capital a year</span>
              <input className="k-input" inputMode="decimal" value={maintenancePct} onChange={(event) => setMaintenancePct(event.target.value)} />
            </label>
            <label className="k-field">
              <span>Discount rate, %</span>
              <input className="k-input" inputMode="decimal" value={discountPct} onChange={(event) => setDiscountPct(event.target.value)} />
            </label>
            <label className="k-field">
              <span>Default VAT, %</span>
              <input className="k-input" inputMode="decimal" value={vatRate} onChange={(event) => setVatRate(event.target.value)} />
            </label>
          </div>
        </div>

        <div className="k-group">
          <span className="k-caption">Exchange rates</span>
          <div className="k-card procurement-settings" data-pad>
            {QUOTE_CURRENCIES.map((code) => {
              const value = typeof fx[code] === 'number' && fx[code] ? String(fx[code]) : (code === currency ? '1' : '')
              return (
                <label className="k-field" key={code}>
                  <span>One {code} in TRY</span>
                  <input
                    className="k-input"
                    inputMode="decimal"
                    value={value}
                    disabled={code === currency}
                    onChange={(event) => setRate(code, event.target.value)}
                    placeholder="No rate"
                  />
                </label>
              )
            })}
            <div className="procurement-rates-actions">
              <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => void fetchRates()} disabled={fetchingRates}>
                {fetchingRates ? 'Fetching…' : "Fetch today's rates"}
              </button>
              <span className="procurement-quote-sub">
                {fx.source === 'TCMB' ? `Central Bank bulletin${fx.date ? ` of ${String(fx.date)}` : ''}` : 'Typed by hand'}
                {ratesNote && ` · ${ratesNote}`}
              </span>
            </div>
            {rateWarning.length > 0 && (
              <p className="procurement-warn">No rate for {rateWarning.join(', ')}. Quotes in those currencies are not compared, and are never converted at 1.</p>
            )}
          </div>
        </div>
      </form>

      <AddProduct
        lines={lines}
        loadClaims={loadClaims}
        claimsOf={(subjectId) => claims[subjectId]}
        onAdd={addLine}
      />

      <div className="k-group">
        <span className="k-caption">Equipment</span>
        {lines.length === 0 && (
          <div className="k-empty">
            <strong>No products yet</strong>
            <p>Search the catalogs above and add the first product. Then compare its vendor quotes here.</p>
          </div>
        )}
        {lines.map((line, index) => (
          <LineCard
            key={line.line_id || `${line.pack_id}:${line.subject_id}`}
            line={line}
            index={index}
            currency={currency}
            rates={fx}
            horizon={years}
            claims={claims[line.subject_id]}
            researchNote={researching[line.subject_id]?.note ?? ''}
            researching={researching[line.subject_id]?.busy ?? false}
            onPatch={patchLine}
            onRemove={removeLine}
            onResearch={(item) => void researchLine(item)}
            onNeedClaims={needClaims}
          />
        ))}
      </div>

      <ForecastCard
        model={model}
        currency={currency}
        canExport={lines.length > 0}
        onCsv={exportCsv}
        onExcel={exportXlsx}
        research={researchSoFar}
      />
    </section>
  )
}

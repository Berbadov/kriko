import { useEffect, useRef, useState } from 'react'
import { get, post, seg } from '../engine/api'
import { followJob } from '../engine/jobs'
import { ExternalLink } from './ExternalLink'

/** The catalog subject a saved check belongs to, when the engine could tie it to one. */
export interface ProductTarget { subject_id: string; pack_id: string }

interface Insights {
  freshness: { last_verified: string | null; stale: boolean; stale_after_days: number; undated_sources: number; basis: string }
  costs: { items: { title: string; prices: string[]; quote: string; url: string }[]; missing: string[]; note: string }
  target: ProductTarget | null
}

/** Evidence dates and quoted part costs are independent of when a check was saved. `onTarget` hands the
 *  product's catalog subject up once it is read, so the Procurement section can find its estimates. */
export function ProductInsights({ lookupId, live, onResearch, onReload, onTarget }: {
  lookupId: string; live: boolean; onResearch: (question: string) => void; onReload: () => void; onTarget: (target: ProductTarget | null) => void
}) {
  const [days, setDays] = useState(30)
  const [data, setData] = useState<Insights | null>(null)
  const [problem, setProblem] = useState('')
  const [status, setStatus] = useState('')
  const [running, setRunning] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  useEffect(() => {
    let active = true
    setData(null)
    setProblem('')
    if (live) get<Insights>(`/api/products/checks/${seg(lookupId)}/insights?days=${days}`)
      .then((reply) => {
        if (!active) return
        setData(reply)
        onTarget(reply.target ?? null)
      })
      .catch((error: unknown) => active && setProblem(error instanceof Error ? error.message : 'Could not read evidence dates and part prices.'))
    return () => { active = false }
  }, [lookupId, live, days, attempt, onTarget])

  const save = async () => {
    setProblem('')
    try {
      const made = await get<{ filename: string; html: string }>(`/api/products/checks/${seg(lookupId)}/report-data?days=${days}`)
      const url = URL.createObjectURL(new Blob([made.html], { type: 'text/html;charset=utf-8' }))
      const link = document.createElement('a'); link.href = url; link.download = made.filename; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 30000)
      setStatus('Report saved. Open the HTML file and print to Save as PDF.')
    } catch (error) { setProblem(error instanceof Error ? error.message : 'Could not export report.') }
  }

  const research = async () => {
    if (!data?.target || running) return
    setRunning(true); setProblem(''); setStatus('Starting research…')
    try {
      const sent = await post<{ job_id: string }>('/api/research', data.target)
      const ended = await followJob(sent.job_id, (job) => setStatus(job.message || 'Researching current evidence…'), () => active.current)
      if (!active.current) return
      if (ended?.state !== 'succeeded') throw new Error(ended?.message || 'Research did not complete. The saved check is unchanged.')
      const refreshed = await post<{ refreshed: boolean }>(`/api/lookup/${seg(lookupId)}/refresh`, {})
      if (!refreshed.refreshed) throw new Error('Research finished, but this saved check could not be refreshed.')
      setStatus('Research complete. Evidence dates reflect the sources available in the catalog.')
      setAttempt((value) => value + 1); onReload()
    } catch (error) { setProblem(error instanceof Error ? error.message : 'Could not research product.') }
    finally { setRunning(false) }
  }

  if (!live) return null
  return <section className="k-group product-insights" aria-label="Product evidence and cost forecast">
    <p className="k-caption">Evidence and part prices</p>
    <div className="k-card product-insights-card" data-pad>
      <div className="product-insights-top">
        <p className="product-insights-verified">
          <strong>Last verified (source retrieval): {data?.freshness.last_verified ? new Date(data.freshness.last_verified).toLocaleDateString() : 'Unknown'}</strong>
        </p>
        <div className="product-insights-controls">
          <label className="product-stale">Stale after
            <select className="k-input" value={days} onChange={(event) => setDays(Number(event.target.value))}>
              {[7, 30, 90, 180, 365].map((value) => <option key={value} value={value}>{value} days</option>)}
            </select>
          </label>
          <button className="k-btn" data-size="sm" onClick={() => void save()}>Export HTML / PDF</button>
        </div>
      </div>
      {data && <>
        <p className="product-quiet">{data.freshness.basis}</p>
        {data.freshness.stale && <p className="k-notice" data-tone="warn" role="status">
          <span>Evidence is stale or has incomplete dates.</span>
          {data.target
            ? <button className="k-btn" data-size="sm" disabled={running} onClick={() => void research()}>{running ? 'Researching…' : 'Re-research product'}</button>
            : <button className="k-btn" data-size="sm" onClick={() => onResearch('Re-research this exact product for current sourced evidence, confirming its variant and market.')}>Research fresh evidence</button>}
        </p>}
        <h2 className="product-subhead">Cost forecast · parts that may cause problems</h2>
        <p className="product-quiet">{data.costs.note}</p>
        {data.costs.items.length > 0 && <ul className="product-costs">{data.costs.items.map((item, index) => <li key={index}>
          <strong>{item.title}: {item.prices.join(', ')}</strong>
          <blockquote>{item.quote}</blockquote>
          <ExternalLink href={item.url}>Price source</ExternalLink>
        </li>)}</ul>}
        {data.costs.missing.length > 0 && <details className="product-missing"><summary>No part price recorded for {data.costs.missing.length} findings</summary><ul>{data.costs.missing.map((name, index) => <li key={index}>{name}</li>)}</ul></details>}
        {!data.costs.items.length && <p className="product-quiet">No sourced repair or replacement prices are recorded yet.</p>}
        <div>
          <button className="k-btn" data-size="sm" onClick={() => onResearch('Find current replacement part and repair prices for the problems in this saved check. Confirm exact product/part compatibility, market and currency. Separate part price, labour, tax and shipping. Cite a live source and its date for each price; report unknowns and do not invent failure probabilities or an expected-cost total.')}>Find current part prices</button>
        </div>
      </>}
      {status && <p role="status" className="product-quiet">{status}</p>}
      {problem && <p className="error-note" role="alert">{problem}</p>}
    </div>
  </section>
}

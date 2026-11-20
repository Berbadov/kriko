import { useEffect, useState } from 'react'
import { get } from '../../engine/api'
import { severityRank, SEVERITY_WORD } from './format'
import type { SubjectClaims, SubjectHit } from './types'

/** Search the installed catalogs and add a product to the estimate. Choosing a
 *  product first shows its leading known problems; the line is added only on
 *  the reader's press of "Add to estimate". */

const LEADING = 3

export function AddProduct({ lines, loadClaims, claimsOf, onAdd }: {
  lines: { subject_id: string; pack_id: string }[]
  loadClaims: (subjectId: string) => Promise<SubjectClaims>
  claimsOf: (subjectId: string) => SubjectClaims | undefined
  onAdd: (hit: SubjectHit) => void
}) {
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SubjectHit[] | null>(null)
  const [problem, setProblem] = useState('')
  const [chosen, setChosen] = useState<SubjectHit | null>(null)

  useEffect(() => {
    const typed = query.trim()
    const timer = window.setTimeout(async () => {
      try {
        if (typed.length >= 2) {
          // `/api/search`, not `/api/subjects/search`: the subjects route shadows that path.
          const data = await get<{ items: SubjectHit[] }>(`/api/search?q=${encodeURIComponent(typed)}&limit=20`)
          setHits(data.items ?? [])
        } else {
          const data = await get<SubjectHit[]>('/api/subjects?limit=30')
          setHits(Array.isArray(data) ? data : [])
        }
        setProblem('')
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not read the catalogs.')
      }
    }, 250)
    return () => window.clearTimeout(timer)
  }, [query])

  const pick = (hit: SubjectHit) => {
    setChosen(hit)
    if (!claimsOf(hit.subject_id)) {
      loadClaims(hit.subject_id).catch((error) => setProblem(error instanceof Error ? error.message : 'Could not read this product.'))
    }
  }

  const onList = (hit: SubjectHit) => lines.some((line) => line.subject_id === hit.subject_id && line.pack_id === hit.pack_id)
  const leading = chosen ? [...(claimsOf(chosen.subject_id)?.claims ?? [])].sort((a, b) => severityRank(a.severity) - severityRank(b.severity)).slice(0, LEADING) : []
  const chosenKnown = chosen ? claimsOf(chosen.subject_id) : undefined

  return (
    <div className="k-card procurement-picker">
      <div className="k-field procurement-picker-search">
        <label htmlFor="procurement-picker-search">Add a product</label>
        <input
          id="procurement-picker-search"
          className="k-input"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search the catalogs. Empty shows the most-claimed products."
        />
      </div>
      {problem && <p className="k-notice" data-tone="risk" role="status">{problem}</p>}
      {hits !== null && hits.length === 0 && <p className="procurement-picker-none">Nothing matches.</p>}
      {(hits ?? []).length > 0 && (
        <ul className="procurement-hits" aria-label="Matching products">
          {(hits ?? []).slice(0, 12).map((hit) => (
            <li key={`${hit.pack_id}:${hit.subject_id}`}>
              <button
                type="button"
                className="k-chip"
                aria-pressed={chosen?.subject_id === hit.subject_id && chosen?.pack_id === hit.pack_id}
                disabled={onList(hit)}
                onClick={() => pick(hit)}
              >
                <strong>{hit.label}</strong>
                <span className="procurement-quote-sub">{onList(hit) ? 'Already on this estimate' : hit.pack_id}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {chosen && (
        <div className="procurement-pending" aria-label={`Leading problems for ${chosen.label}`}>
          <div className="procurement-pending-head">
            <strong>{chosen.label}</strong>
            <span className="k-pill">{chosen.pack_id}</span>
          </div>
          <span className="k-caption">Leading known problems</span>
          {!chosenKnown && <p className="procurement-quote-sub">Reading the product…</p>}
          {chosenKnown && leading.length === 0 && <p className="procurement-quote-sub">No reports yet. Research this product after it is added.</p>}
          {leading.length > 0 && (
            <ul className="procurement-problems">
              {leading.map((claim) => (
                <li key={claim.claim_id} className="procurement-problem">
                  <span className="procurement-severity" data-level={(claim.severity || 'unknown').toLowerCase()}>
                    {SEVERITY_WORD[(claim.severity || 'unknown').toLowerCase()] ?? 'To check'}
                  </span>
                  <span>{claim.title}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="procurement-pending-actions">
            <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => setChosen(null)}>Cancel</button>
            <button type="button" className="k-btn" onClick={() => { onAdd(chosen); setChosen(null) }} disabled={onList(chosen)}>
              Add to estimate
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

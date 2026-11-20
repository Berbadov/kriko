import { useMemo, useState } from 'react'
import { useCompare } from '../../compare'
import { ago, dayGroup, useHistory, type Past, type Undoable } from '../../engine/history'
import { useResearchRuns, undoResearchRun, type ResearchRun, type ResearchUsage } from '../../engine/research'
import { followJob } from '../../engine/jobs'
import { cost, count as counted } from '../../engine/logformat'
import { Icon } from '../Icon'
import { ProductGlyph } from '../ProductGlyph'
import { glyphFor } from '../productGlyphs'
import { useEngine } from '../../engine/Engine'

const GROUPS = ['Today', 'Yesterday', 'This week', 'Earlier']

const reason = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback)

/** Every saved check, and the research runs that wrote into the catalogs.
 *  Open one, put it in Compare, or delete it; undo a run that filed claims the
 *  reader no longer wants. Drawn inside the History page, which has its title. */
export function HistoryPanel({ onOpen }: { onOpen: (id: string) => void }) {
  const [query, setQuery] = useState('')
  const { items, problem, remove, restore, hasMore, loadMore, retry } = useHistory(query)
  const { mode } = useEngine()
  const runs = useResearchRuns()
  const { add } = useCompare()
  const [asking, setAsking] = useState<string | null>(null)
  const [added, setAdded] = useState<Set<string>>(new Set())
  /** What the last delete took, and the row it was, for the undo line. */
  const [undone, setUndone] = useState<{ undo: Undoable; name: string } | null>(null)

  const forget = async (row: Past) => {
    const undo = await remove(row.id)
    if (undo) setUndone({ undo, name: row.name })
  }

  const undoLast = async () => {
    if (!undone) return
    await restore(undone.undo)
    setUndone(null)
  }

  const shown = useMemo(() => {
    if (mode === 'live') return items ?? []
    const needle = query.trim().toLowerCase()
    return (items ?? []).filter((row) => !needle || `${row.name} ${row.category}`.toLowerCase().includes(needle))
  }, [items, query, mode])

  // A failed read and a read still in flight must not look the same. The
  // combined `{problem || 'Reading the history…'}` put the failure in the same
  // muted style as the wait, so "the engine refused" read as "still loading".
  // The runs are drawn first in every one of these states: a checks read that
  // failed must not hide what the research already spent.
  const spent = mode === 'live' ? <ResearchRuns runs={runs.runs} usage={runs.usage} problem={runs.problem} reload={runs.reload} /> : null
  if (!items && problem) {
    return (
      <>
        <p className="error-note" role="alert">
          Your checks could not be read. {problem} <button className="k-btn" data-size="sm" onClick={retry}>Try again</button>
        </p>
        {spent}
      </>
    )
  }
  if (!items) {
    return (
      <>
        <p className="work-note">Reading the history…</p>
        {spent}
      </>
    )
  }
  const empty = !items.length && !query

  return (
    <>
      <label className="work-search">
        <Icon name="search" size={16} />
        <input type="search" className="k-input" placeholder="Search your checks" aria-label="Search your checks" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      {problem && (
        <p className="error-note">
          {problem} <button className="k-btn" data-size="sm" onClick={retry}>Try again</button>
        </p>
      )}

      {/* The undo, where the delete happened. A confirm dialog is the wrong
          shape for this: the reader has already said yes, and what they need
          is the next few seconds in which they can say "not that one". The
          engine hands the deleted row back for exactly this (`DELETE
          /api/history/{id}` returns `undo`), so nothing is kept in a trash
          table nobody empties. */}
      {undone && (
        <aside className="k-notice" role="status">
          <span>
            Deleted {undone.name}.
          </span>
          <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => void undoLast()}>
            Undo
          </button>
          <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => setUndone(null)}>
            Dismiss
          </button>
        </aside>
      )}

      {empty && (
        <section className="k-empty work-empty">
          <strong>No checks yet</strong>
          <p>Your checks are kept here once Kriko has looked into a product. Open one from History to read it again, or put it in Compare.</p>
        </section>
      )}
      {!empty && shown.length === 0 && <p className="work-note">Nothing matches.</p>}
      {GROUPS.map((group) => {
        const rows = shown.filter((row) => dayGroup(row.at) === group)
        if (!rows.length) return null
        return (
          <section key={group} className="k-group" aria-label={group}>
            <h2 className="k-caption">{group}</h2>
            <div className="k-card">
              <ul className="k-list">
                {rows.map((row) => (
                  <PastRow
                    key={row.id}
                    row={row}
                    asking={asking === row.id}
                    added={added.has(row.id)}
                    onOpen={() => onOpen(row.id)}
                    onAdd={() => {
                      if (add(row.id)) setAdded((now) => new Set(now).add(row.id))
                    }}
                    onAsk={() => setAsking(row.id)}
                    onKeep={() => setAsking(null)}
                    onDelete={() => {
                      setAsking(null)
                      void forget(row)
                    }}
                  />
                ))}
              </ul>
            </div>
          </section>
        )
      })}
      {!empty && <p className="work-note">{items.length} saved {items.length === 1 ? 'check' : 'checks'}.</p>}
      {hasMore && (
        <button className="k-btn" onClick={loadMore}>
          Load more checks
        </button>
      )}
      {/* What the research spent, below the checks it produced. Only a live engine has runs;
          demo mode draws no spend rather than an example number. A failed checks read still
          shows it. */}
      {spent}
    </>
  )
}

/** What each research run cost and added, and the one press that takes a run's
 *  claims back out.
 *
 *  Every figure is the engine's. A cost of `null` is "not counted", never
 *  `$0.00`: `cost()` in `engine/logformat` owns that distinction, and the
 *  sentence for *why* a column is empty is the engine's own
 *  (`/api/usage` → `metered`), so the tooltip cannot drift from the schema. */
function ResearchRuns({ runs, usage, problem, reload }: {
  runs: ResearchRun[] | null
  usage: ResearchUsage | null
  problem: string
  reload: () => Promise<void>
}) {
  const [asking, setAsking] = useState<string | null>(null)
  const [working, setWorking] = useState('')
  const [note, setNote] = useState('')

  if (!runs) {
    if (!problem) return <p className="work-note">Reading what your research cost…</p>
    return (
      <p className="error-note" role="alert">
        Your research runs could not be read. {problem}{' '}
        <button className="k-btn" data-size="sm" onClick={() => void reload()}>Try again</button>
      </p>
    )
  }

  const undo = async (run: ResearchRun) => {
    setAsking(null)
    setWorking(run.run_id)
    setNote('Starting…')
    try {
      const started = await undoResearchRun(run.run_id)
      const ended = await followJob(started.job_id, (reading) => setNote(reading.message || 'Working…'))
      if (ended?.state !== 'succeeded') throw new Error(ended?.message || 'The undo did not finish.')
      // The handler's own account ("removed 4 of 6; 2 were already absent")
      // rather than a sentence of our own.
      const said = (ended.result as { note?: string } | null)?.note
      setNote(said || ended.message || 'The run was undone.')
      await reload()
    } catch (error) {
      setNote(reason(error, 'The run could not be undone.'))
    } finally {
      setWorking('')
    }
  }

  // The sums are drawn only when the engine answered the question. A failed
  // `/api/usage` is a blank total, never a total of zero: the per-run rows are
  // still the engine's, and `cost()`/`count()` already say "not counted" for a
  // figure a plane could not meter.
  const totals = usage && [
    `${counted(usage.runs)} ${usage.runs === 1 ? 'run' : 'runs'}`,
    `${cost(usage.spent_usd)} spent`,
    `${counted(usage.tokens_used)} tokens`,
    `${counted(usage.claims)} claims still filed`,
  ].join(' · ')
  // Why the total is blank, in the engine's sentence, when it can be blank.
  const unmetered = usage?.spent_usd === null ? usage.metered.spent_usd ?? '' : ''

  return (
    <section className="k-group" aria-label="Research runs">
      <h2 className="k-caption">Research runs</h2>
      {totals && (
        <p className="work-note">
          {totals}
          {unmetered ? ` · ${unmetered}` : ''}
        </p>
      )}
      {note && <p className="work-note" role="status">{note}</p>}
      {runs.length === 0 ? (
        <p className="work-note">No research has run yet.</p>
      ) : (
        <div className="k-card">
          <ul className="k-list">
            {runs.map((run) => {
              const meta = [
                run.plane || 'research',
                run.llm,
                run.search_provider,
                cost(run.spent_usd),
                run.tokens_used === null ? '' : `${counted(run.tokens_used)} tokens`,
                `${counted(run.claims)} ${run.claims === 1 ? 'claim' : 'claims'} still filed`,
                run.removed > 0 ? `${counted(run.removed)} taken back out` : '',
                ago(run.started_at),
                run.outcome,
              ].filter(Boolean).join(' · ')
              return (
                <li className="k-row work-run" key={run.run_id} data-asking={asking === run.run_id} aria-busy={working === run.run_id}>
                  <span className="k-row-main" title={run.spent_usd === null ? usage?.metered.spent_usd ?? '' : ''}>
                    <span className="k-row-title">{run.plane || 'Research'} run</span>
                    <span className="k-row-note">{meta}</span>
                  </span>
                  {asking === run.run_id ? (
                    <span className="k-row-control work-confirm">
                      <span>Undo this run? It takes the {counted(run.claims)} {run.claims === 1 ? 'claim' : 'claims'} it filed back out of the catalogs that hold them. Those claims cannot be put back.</span>
                      <button className="k-btn" data-size="sm" data-kind="danger" onClick={() => void undo(run)}>
                        Undo it
                      </button>
                      <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => setAsking(null)}>
                        Keep them
                      </button>
                    </span>
                  ) : run.claims > 0 ? (
                    <span className="k-row-control">
                      <button className="k-btn" data-size="sm" onClick={() => setAsking(run.run_id)} disabled={working === run.run_id}>
                        {working === run.run_id ? 'Undoing…' : 'Undo this run'}
                      </button>
                    </span>
                  ) : null}
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </section>
  )
}

function PastRow({
  row,
  asking,
  added,
  onOpen,
  onAdd,
  onAsk,
  onKeep,
  onDelete,
}: {
  row: Past
  asking: boolean
  added: boolean
  onOpen: () => void
  onAdd: () => void
  onAsk: () => void
  onKeep: () => void
  onDelete: () => void
}) {
  // The check's category is what the history holds; the leading finding is not in the history list.
  const note = [row.category || 'Quick look', row.source].filter(Boolean).join(' · ')
  const risks = row.risks === 0 ? 'No sourced problems' : `${row.risks} ${row.risks === 1 ? 'risk' : 'risks'}`
  return (
    <li className="k-row work-check" data-asking={asking}>
      <button type="button" className="work-check-open" onClick={onOpen}>
        {glyphFor(row.name) ? (
          <span className="k-row-icon">
            <ProductGlyph name={row.name} size={22} />
          </span>
        ) : (
          <span className="work-slot" aria-hidden="true" />
        )}
        <span className="k-row-main">
          <span className="k-row-title">{row.name}</span>
          <span className="k-row-note">{note}</span>
        </span>
      </button>
      {asking ? (
        <span className="k-row-control work-confirm">
          <span>Delete this check?</span>
          <button className="k-btn" data-size="sm" data-kind="danger" onClick={onDelete}>
            Delete
          </button>
          <button className="k-btn" data-size="sm" data-kind="quiet" onClick={onKeep}>
            Keep
          </button>
        </span>
      ) : (
        <span className="k-row-control work-check-side">
          <span className="k-row-value">
            {risks}
            <span className="work-when"> · {row.when}</span>
          </span>
          <button
            type="button"
            className="k-btn"
            data-size="sm"
            data-kind="quiet"
            onClick={onAdd}
            disabled={added}
            aria-label={`Add ${row.name} to Compare`}
          >
            {added ? 'In Compare' : 'Compare'}
          </button>
          <button type="button" className="k-btn" data-size="sm" data-kind="quiet" onClick={onAsk} aria-label={`Delete ${row.name}`}>
            Delete
          </button>
        </span>
      )}
    </li>
  )
}

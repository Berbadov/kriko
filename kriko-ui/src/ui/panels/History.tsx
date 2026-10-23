import { useMemo, useState } from 'react'
import { useCompare } from '../../compare'
import { ago, dayGroup, useHistory, type Past, type Undoable } from '../../engine/history'
import { useResearchRuns, undoResearchRun, type ResearchRun, type ResearchUsage } from '../../engine/research'
import { followJob } from '../../engine/jobs'
import { cost, count as counted } from '../../engine/logformat'
import { Icon } from '../Icon'
import { useEngine } from '../../engine/Engine'

const GROUPS = ['Today', 'Yesterday', 'This week', 'Earlier']

const reason = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback)

/** Every saved check, and the research runs that wrote into the catalogs.
 *  Open one, put it in Compare, or delete it; undo a run that filed claims the
 *  reader no longer wants. */
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
      <div className="panel-body">
        {spent}
        <p className="error-note" role="alert">
          Your checks could not be read. {problem} <button className="btn" onClick={retry}>Try again</button>
        </p>
      </div>
    )
  }
  if (!items) {
    return (
      <div className="panel-body">
        {spent}
        <p className="panel-note">Reading the history…</p>
      </div>
    )
  }
  const empty = !items.length && !query

  return (
    <div className="panel-body">
      {/* The runs are the history of what was spent to know what is below them.
          Only a live engine has runs; demo mode draws no spend rather than an
          example number. */}
      {spent}

      <label className="search-field">
        <Icon name="search" size={15} />
        <input type="search" placeholder="Search your checks" aria-label="Search your checks" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      {problem && <p className="error-note">{problem} <button className="btn" onClick={retry}>Try again</button></p>}

      {/* The undo, where the delete happened. A confirm dialog is the wrong
          shape for this: the reader has already said yes, and what they need
          is the next few seconds in which they can say "not that one". The
          engine hands the deleted row back for exactly this (`DELETE
          /api/history/{id}` returns `undo`), so nothing is kept in a trash
          table nobody empties. */}
      {undone && (
        <div className="past-undo" role="status">
          <span>
            Deleted {undone.name}.{' '}
            <button className="link" onClick={() => void undoLast()}>Undo</button>
          </span>
          <button className="icon-btn sm" onClick={() => setUndone(null)} aria-label="Dismiss">
            <Icon name="x" size={14} />
          </button>
        </div>
      )}

      {empty && <p className="panel-note">No checks yet. Your checks are kept here.</p>}
      {!empty && shown.length === 0 && <p className="panel-note">Nothing matches.</p>}
      {GROUPS.map((group) => {
        const rows = shown.filter((row) => dayGroup(row.at) === group)
        if (!rows.length) return null
        return (
          <section key={group} className="panel-group">
            <h3>{group}</h3>
            <ul className="past-list">
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
          </section>
        )
      })}
      {!empty && <p className="panel-note">{items.length} saved {items.length === 1 ? 'check' : 'checks'}.</p>}
      {hasMore && <button className="btn" onClick={loadMore}>Load more checks</button>}
    </div>
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
    if (!problem) return <p className="panel-note">Reading what your research cost…</p>
    return (
      <p className="error-note" role="alert">
        Your research runs could not be read. {problem}{' '}
        <button className="btn" onClick={() => void reload()}>Try again</button>
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
    <section className="panel-group">
      <h3>Research runs</h3>
      {totals && (
        <p className="panel-note">
          {totals}
          {unmetered ? ` — ${unmetered}` : ''}
        </p>
      )}
      {note && <p className="panel-note" role="status">{note}</p>}
      {runs.length === 0 ? (
        <p className="panel-note">No research has run yet.</p>
      ) : (
        <ul className="past-list">
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
              <li className="past run" key={run.run_id} data-asking={asking === run.run_id} aria-busy={working === run.run_id}>
                <span className="past-main">
                  <strong>{run.plane || 'Research'} run</strong>
                  <small title={run.spent_usd === null ? usage?.metered.spent_usd ?? '' : ''}>{meta}</small>
                  {asking === run.run_id ? (
                    <span className="past-ask run-ask">
                      <span>Undo this run? It takes the {counted(run.claims)} {run.claims === 1 ? 'claim' : 'claims'} it filed back out of the catalogs that hold them. Those claims cannot be put back.</span>
                      <button onClick={() => void undo(run)}>Undo it</button>
                      <button onClick={() => setAsking(null)}>Keep them</button>
                    </span>
                  ) : run.claims > 0 ? (
                    <button className="run-undo" onClick={() => setAsking(run.run_id)} disabled={working === run.run_id}>
                      {working === run.run_id ? 'Undoing…' : 'Undo this run'}
                    </button>
                  ) : null}
                </span>
              </li>
            )
          })}
        </ul>
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
  const meta = [row.category || 'Quick look', row.risks === 0 ? 'No sourced problems recorded' : `${row.risks} ${row.risks === 1 ? 'risk' : 'risks'}`, row.when].filter(Boolean).join(' · ')
  return (
    <li className="past" data-asking={asking}>
      <button className="past-main" onClick={onOpen}>
        <strong>{row.name}</strong>
        <small>{meta}</small>
      </button>
      {asking ? (
        <span className="past-ask">
          <span>Delete?</span>
          <button onClick={onDelete}>Delete</button>
          <button onClick={onKeep}>Keep</button>
        </span>
      ) : (
        <span className="past-actions">
          <button className="icon-btn sm" onClick={onAdd} aria-label={`Add ${row.name} to Compare`} title={added ? 'In Compare' : 'Add to Compare'} disabled={added}>
            <Icon name={added ? 'check' : 'compare'} size={15} />
          </button>
          <button className="icon-btn sm" onClick={onAsk} aria-label={`Delete ${row.name}`} title="Delete">
            <Icon name="x" size={15} />
          </button>
        </span>
      )}
    </li>
  )
}

import { useMemo, useState } from 'react'
import { useCompare } from '../../compare'
import { dayGroup, useHistory, type Past, type Undoable } from '../../engine/history'
import { Icon } from '../Icon'
import { useEngine } from '../../engine/Engine'

const GROUPS = ['Today', 'Yesterday', 'This week', 'Earlier']

/** Every saved check. Open one, put it in Compare, or delete it. */
export function HistoryPanel({ onOpen }: { onOpen: (id: string) => void }) {
  const [query, setQuery] = useState('')
  const { items, problem, remove, restore, hasMore, loadMore, retry } = useHistory(query)
  const { mode } = useEngine()
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
  if (!items && problem) {
    return (
      <p className="error-note" role="alert">
        Your checks could not be read. {problem} <button className="btn" onClick={retry}>Try again</button>
      </p>
    )
  }
  if (!items) return <p className="panel-note">Reading the history…</p>
  if (!items.length && !query) return <p className="panel-note">No checks yet. Your checks are kept here.</p>

  return (
    <div className="panel-body">
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

      {shown.length === 0 && <p className="panel-note">Nothing matches.</p>}
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
      <p className="panel-note">{items.length} saved {items.length === 1 ? 'check' : 'checks'}.</p>
      {hasMore && <button className="btn" onClick={loadMore}>Load more checks</button>}
    </div>
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

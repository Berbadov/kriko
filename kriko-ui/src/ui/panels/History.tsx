import { useMemo, useState } from 'react'
import { useCompare } from '../../compare'
import { dayGroup, useHistory, type Past } from '../../engine/history'
import { Icon } from '../Icon'

const GROUPS = ['Today', 'Yesterday', 'This week', 'Earlier']

/** Every saved check. Open one, put it in Compare, or delete it. */
export function HistoryPanel({ onOpen }: { onOpen: (id: string) => void }) {
  const { items, problem, remove } = useHistory()
  const { add } = useCompare()
  const [query, setQuery] = useState('')
  const [asking, setAsking] = useState<string | null>(null)
  const [added, setAdded] = useState<Set<string>>(new Set())

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (items ?? []).filter((row) => !needle || `${row.name} ${row.category}`.toLowerCase().includes(needle))
  }, [items, query])

  if (!items) return <p className="panel-note">{problem || 'Reading the history…'}</p>
  if (!items.length) return <p className="panel-note">No checks yet. Your checks are kept here.</p>

  return (
    <div className="panel-body">
      <label className="search-field">
        <Icon name="search" size={15} />
        <input type="search" placeholder="Search your checks" aria-label="Search your checks" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      {problem && <p className="error-note">{problem}</p>}

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
                    void remove(row.id)
                  }}
                />
              ))}
            </ul>
          </section>
        )
      })}
      <p className="panel-note">{items.length} saved {items.length === 1 ? 'check' : 'checks'}.</p>
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
  const meta = [row.category || 'Quick look', row.risks === 0 ? 'No risks' : `${row.risks} ${row.risks === 1 ? 'risk' : 'risks'}`, row.when].filter(Boolean).join(' · ')
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

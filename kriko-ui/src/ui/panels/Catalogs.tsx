import { useState } from 'react'
import { useCatalogs, type Catalog, type Draft } from '../../engine/catalogs'
import { Switch } from '../controls'

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** What Kriko knows. A catalog is on or off, and a draft from an agent waits for the reader to install it. */
export function CatalogsPanel() {
  const { catalogs, drafts, problem, busy, setEnabled, stepBack, install, discard } = useCatalogs()
  const [asking, setAsking] = useState<string | null>(null)

  // A failed read is not a wait. `{problem || 'Reading the catalogs…'}` rendered
  // both in the muted note style, so a refusal looked like a slow screen.
  if (!catalogs && problem) {
    return (
      <p className="error-note" role="alert">
        Your catalogs could not be read. {problem}
      </p>
    )
  }
  if (!catalogs) return <p className="panel-note">Reading the catalogs…</p>

  const waiting = drafts.filter((row) => !row.installed)

  return (
    <div className="panel-body">
      {problem && <p className="error-note">{problem}</p>}

      <section className="panel-group">
        <h3>Installed</h3>
        {catalogs.length === 0 && <p className="panel-note">No catalogs yet. Kriko still checks a product from what it finds on the page.</p>}
        <ul className="past-list">
          {catalogs.map((row) => (
            <CatalogRow
              key={row.id}
              row={row}
              working={busy === row.id}
              asking={asking === `back:${row.id}`}
              onToggle={(on) => void setEnabled(row.id, on)}
              onAsk={() => setAsking(`back:${row.id}`)}
              onKeep={() => setAsking(null)}
              onBack={() => {
                setAsking(null)
                void stepBack(row.id)
              }}
            />
          ))}
        </ul>
      </section>

      {waiting.length > 0 && (
        <section className="panel-group">
          <h3>Drafted for you</h3>
          <ul className="past-list">
            {waiting.map((row) => (
              <DraftRow
                key={row.slug}
                row={row}
                working={busy === row.slug}
                asking={asking === `drop:${row.slug}`}
                onInstall={() => void install(row.slug)}
                onAsk={() => setAsking(`drop:${row.slug}`)}
                onKeep={() => setAsking(null)}
                onDiscard={() => {
                  setAsking(null)
                  void discard(row.slug)
                }}
              />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function CatalogRow({
  row,
  working,
  asking,
  onToggle,
  onAsk,
  onKeep,
  onBack,
}: {
  row: Catalog
  working: boolean
  asking: boolean
  onToggle: (on: boolean) => void
  onAsk: () => void
  onKeep: () => void
  onBack: () => void
}) {
  const meta = [`v${row.version}`, count(row.products, 'product', 'products'), count(row.risks, 'risk', 'risks')].join(' · ')
  return (
    <li className="past catalog" data-asking={asking} data-off={!row.enabled} aria-busy={working}>
      <span className="past-main">
        <strong>{row.name}</strong>
        <small>{meta}</small>
        {row.previous && !asking && (
          <button className="step-back" onClick={onAsk} disabled={working}>
            Go back to v{row.previous}
          </button>
        )}
      </span>
      {asking ? (
        <span className="past-ask calm">
          <span>Go back?</span>
          <button className="install" onClick={onBack}>Go back</button>
          <button onClick={onKeep}>Keep</button>
        </span>
      ) : (
        <Switch on={row.enabled} onChange={onToggle} label={`Use ${row.name}`} />
      )}
    </li>
  )
}

function DraftRow({
  row,
  working,
  asking,
  onInstall,
  onAsk,
  onKeep,
  onDiscard,
}: {
  row: Draft
  working: boolean
  asking: boolean
  onInstall: () => void
  onAsk: () => void
  onKeep: () => void
  onDiscard: () => void
}) {
  return (
    <li className="past" data-asking={asking} aria-busy={working}>
      <span className="past-main">
        <strong>{row.name}</strong>
        <small>{row.error || (row.version ? `v${row.version}` : 'Draft')}</small>
      </span>
      {asking ? (
        <span className="past-ask">
          <span>Discard?</span>
          <button onClick={onDiscard}>Discard</button>
          <button onClick={onKeep}>Keep</button>
        </span>
      ) : (
        <span className="past-ask calm">
          {!row.error && (
            <button className="install" onClick={onInstall} disabled={working}>
              {working ? 'Installing…' : 'Install'}
            </button>
          )}
          <button onClick={onAsk} disabled={working}>
            Discard
          </button>
        </span>
      )}
    </li>
  )
}

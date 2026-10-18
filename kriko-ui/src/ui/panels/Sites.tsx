import { useState } from 'react'
import { useSites, type Origin, type Site, type Wanted } from '../../engine/sites'
import { Switch } from '../controls'

const ORIGIN: Record<Origin, string> = {
  catalog: 'From a catalog',
  agent: 'Learned by an agent',
  reader: 'Added by you',
  inferred: 'Worked out on this computer',
}

const STATUS: Record<Site['status'], string> = {
  ready: 'Ready',
  permission: 'Needs permission in the browser',
  off: 'Off',
  waiting: 'Waiting for the browser',
  refused: 'The browser refused it',
}

/** The pages that Kriko can read, and the sites that someone asked for. */
export function SitesPanel() {
  const { sites, wanted, problem, turn, forget, learn } = useSites()
  const [asking, setAsking] = useState<string | null>(null)

  if (!sites) return <p className="panel-note">{problem || 'Reading the sites…'}</p>

  return (
    <div className="panel-body">
      {problem && <p className="error-note">{problem}</p>}

      <section className="panel-group">
        <h3>Kriko can read</h3>
        {sites.length === 0 && <p className="panel-note">No sites yet. Install a catalog, or ask for a site below.</p>}
        <ul className="past-list">
          {sites.map((row) => (
            <SiteRow
              key={row.host}
              row={row}
              asking={asking === row.host}
              onAsk={() => setAsking(row.host)}
              onKeep={() => setAsking(null)}
              onTurn={(on) => void turn(row.host, on)}
              onForget={() => {
                setAsking(null)
                void forget(row.host)
              }}
            />
          ))}
        </ul>
      </section>

      {wanted.length > 0 && (
        <section className="panel-group">
          <h3>Asked for</h3>
          <p className="panel-note">You pressed the button on these pages, and nothing reads them yet.</p>
          <ul className="past-list">
            {wanted.map((row) => (
              <WantedRow key={row.host} row={row} onLearn={() => void learn(row.host)} />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function SiteRow({ row, asking, onAsk, onKeep, onTurn, onForget }: { row: Site; asking: boolean; onAsk: () => void; onKeep: () => void; onTurn: (on: boolean) => void; onForget: () => void }) {
  const status = row.origin === 'inferred' && !row.enabled ? STATUS.off : STATUS[row.status]
  const forgettable = row.origin === 'agent' || row.origin === 'reader'
  return (
    <li className="past site" data-asking={asking} data-status={row.origin === 'inferred' && !row.enabled ? 'off' : row.status}>
      <span className="past-main">
        <strong>{row.host}</strong>
        <small>{[ORIGIN[row.origin], status].join(' · ')}</small>
        {row.status === 'permission' && row.detail && <small className="site-hint">{row.detail}</small>}
      </span>
      {asking ? (
        <span className="past-ask">
          <span>Forget?</span>
          <button onClick={onForget}>Forget</button>
          <button onClick={onKeep}>Keep</button>
        </span>
      ) : row.origin === 'inferred' ? (
        <Switch on={row.enabled} onChange={onTurn} label={`Read ${row.host}`} />
      ) : forgettable ? (
        <span className="past-ask calm">
          <button onClick={onAsk} aria-label={`Forget ${row.host}`}>
            Forget
          </button>
        </span>
      ) : null}
    </li>
  )
}

function WantedRow({ row, onLearn }: { row: Wanted; onLearn: () => void }) {
  const working = row.state === 'working'
  const meta = [row.asks === 1 ? 'Asked once' : `Asked ${row.asks} times`, row.title].filter(Boolean).join(' · ')
  return (
    <li className="past" aria-busy={working}>
      <span className="past-main">
        <strong>{row.host}</strong>
        <small>{meta}</small>
        {(working || row.state === 'failed') && row.detail && <small className={row.state === 'failed' ? 'site-fail' : undefined}>{row.detail}</small>}
      </span>
      <span className="past-ask calm">
        <button className="install" onClick={onLearn} disabled={working}>
          {working ? 'Learning…' : row.state === 'failed' ? 'Try again' : 'Learn this site'}
        </button>
      </span>
    </li>
  )
}

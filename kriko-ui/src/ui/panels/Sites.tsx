import { useState } from 'react'
import { useSites, type Origin, type Site, type Wanted } from '../../engine/sites'
import { Icon } from '../Icon'

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

  // A failed read is not a wait — see the same fix in Catalogs and History.
  if (!sites && problem) {
    return (
      <aside className="k-notice" data-tone="risk" role="alert">
        Your sites could not be read. {problem}
      </aside>
    )
  }
  if (!sites) return <p className="library-note">Reading the sites…</p>

  return (
    <>
      {problem && <aside className="k-notice" data-tone="risk" role="alert">{problem}</aside>}

      <section className="k-group" aria-labelledby="sites-readable">
        <h3 className="k-caption" id="sites-readable">Kriko can read</h3>
        {sites.length === 0 ? (
          <div className="k-empty">
            <strong>No sites yet</strong>
            <p>A catalog brings the sites it knows how to read. Install one to bring its sites here, or teach Kriko a site below.</p>
            <button
              className="k-btn"
              data-kind="primary"
              onClick={() => window.dispatchEvent(new CustomEvent('kriko:navigate', { detail: { screen: 'catalogs' } }))}
            >
              Install a catalog
            </button>
          </div>
        ) : (
          <ul className="k-card k-list">
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
        )}
      </section>

      <section className="k-group" aria-labelledby="sites-teach">
        <h3 className="k-caption" id="sites-teach">Teach Kriko a site</h3>
        <p className="library-note">
          You pressed the button on these pages in the browser extension, and nothing reads them yet. An agent learns a site from one page, which takes about a minute.
        </p>
        {wanted.length === 0 ? (
          <div className="k-card k-list">
            <p className="k-row library-note">No site is waiting. Press the button in the browser extension on a page Kriko cannot read, and it appears here.</p>
          </div>
        ) : (
          <ul className="k-card k-list">
            {wanted.map((row) => (
              <WantedRow key={row.host} row={row} onLearn={() => void learn(row.host)} />
            ))}
          </ul>
        )}
      </section>
    </>
  )
}

function SiteRow({ row, asking, onAsk, onKeep, onTurn, onForget }: { row: Site; asking: boolean; onAsk: () => void; onKeep: () => void; onTurn: (on: boolean) => void; onForget: () => void }) {
  const off = row.origin === 'inferred' && !row.enabled
  const status = off ? STATUS.off : STATUS[row.status]
  const forgettable = row.origin === 'agent' || row.origin === 'reader'
  // Only a way worked out on this computer can be turned off here, so only that
  // origin is drawn with a switch. A catalog's way stays on while the catalog is
  // installed, and an agent's or a reader's way has no off switch in the engine.
  const tone = off ? undefined : row.status === 'ready' ? 'ok' : row.status === 'permission' ? 'warn' : row.status === 'refused' ? 'risk' : undefined
  return (
    <li className="k-row sites-row" data-asking={asking} data-status={off ? 'off' : row.status}>
      <span className="k-row-icon" data-tone={tone} aria-hidden="true"><Icon name="globe" size={16} /></span>
      <span className="k-row-main">
        <span className="k-row-title">{row.host}</span>
        <span className="k-row-note">{[ORIGIN[row.origin], status].join(' · ')}</span>
        {row.status === 'permission' && row.detail && <span className="k-row-note sites-hint">{row.detail}</span>}
      </span>
      {asking ? (
        <span className="k-row-control library-ask">
          <span>Forget?</span>
          <button className="k-btn" data-size="sm" data-kind="danger" onClick={onForget}>Forget</button>
          <button className="k-btn" data-size="sm" data-kind="quiet" onClick={onKeep}>Keep</button>
        </span>
      ) : (
        <span className="k-row-control">
          {row.origin === 'inferred' ? (
            <span className="k-seg" role="group" aria-label={`Read ${row.host}`}>
              <button type="button" aria-pressed={row.enabled} onClick={() => onTurn(true)}>On</button>
              <button type="button" aria-pressed={!row.enabled} onClick={() => onTurn(false)}>Off</button>
            </span>
          ) : null}
          {forgettable && (
            <button className="k-btn" data-size="sm" data-kind="quiet" onClick={onAsk} aria-label={`Forget ${row.host}`}>
              Forget
            </button>
          )}
        </span>
      )}
    </li>
  )
}

function WantedRow({ row, onLearn }: { row: Wanted; onLearn: () => void }) {
  const working = row.state === 'working'
  const meta = [row.asks === 1 ? 'Asked once' : `Asked ${row.asks} times`, row.title].filter(Boolean).join(' · ')
  return (
    <li className="k-row" aria-busy={working}>
      <span className="k-row-icon" aria-hidden="true"><Icon name="globe" size={16} /></span>
      <span className="k-row-main">
        <span className="k-row-title">{row.host}</span>
        <span className="k-row-note">{meta}</span>
        {(working || row.state === 'failed') && row.detail && <span className={row.state === 'failed' ? 'k-row-note sites-fail' : 'k-row-note'}>{row.detail}</span>}
      </span>
      <span className="k-row-control">
        <button className="k-btn" onClick={onLearn} disabled={working}>
          {working ? 'Learning…' : row.state === 'failed' ? 'Try again' : 'Learn this site'}
        </button>
      </span>
    </li>
  )
}

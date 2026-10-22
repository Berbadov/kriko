import { useState } from 'react'
import { useProxies } from '../../engine/proxies'
import { Switch } from '../controls'
import '../../styles/providers.css'

/** Rotating proxies for pages that refuse to be read. Off by default, and honest about what it does. */
export function ProxiesGroup() {
  const { doc, problem, checked, save, check, reload } = useProxies()
  if (!doc) return problem ? <p className="error-note" role="alert">Could not read proxy settings. {problem} <button className="btn" onClick={() => void reload()}>Try again</button></p> : null
  const pool = doc.pool.join('\n')
  const learned = doc.learned

  return (
    <section className="panel-group" data-tour="proxies">
      <h3>Proxies</h3>
      <p className="panel-note">
        Off. When on, a page that refuses a direct read (blocked, rate-limited or asking for a bot check) is read again through these proxies, one after another. Kriko does not solve
        CAPTCHAs, sign in or get past paywalls, it follows robots.txt, and a page that stays blocked is reported as could not be read. A site&apos;s terms may forbid this; the choice is
        yours. The proxy sees which pages you read. Hosted search services are not routed through it, and OpenSERP uses its own network settings.
      </p>
      {problem && <p className="error-note">{problem}</p>}
      <div className="setting">
        <span>
          Use proxies for blocked pages
          <small>{doc.active ? 'On. Only a site that has refused a read is sent through the pool.' : doc.enabled ? 'On, but no address is listed yet.' : 'Off. Every page is read directly.'}</small>
        </span>
        <Switch label="Use proxies for blocked pages" on={doc.enabled} onChange={(on) => void save({ proxy_enabled: on ? '1' : '0' })} />
      </div>
      <div className="setting stack">
        <span>
          Proxy addresses
          <small>One per line, like http://host:8080, or a single rotating gateway. No login in the address.</small>
        </span>
        <PoolField key={pool} saved={pool} onSave={(next) => void save({ proxy_pool: next })} />
      </div>
      <div className="setting">
        <span>
          Login
          <small>{doc.login_saved ? 'Saved under Keys.' : 'None saved. Add "Proxy login" under Keys if the proxies ask for one.'}</small>
        </span>
        <button className="btn" onClick={() => void check()} disabled={checked === 'checking' || doc.pool.length === 0}>
          {checked === 'checking' ? 'Checking…' : 'Check the proxies'}
        </button>
      </div>
      {Array.isArray(checked) && (
        <ul className="plain-list" aria-label="Proxy check">
          {checked.map((row) => (
            <li key={row.address}>
              <strong>{row.address}</strong>
              <small>{row.ok ? `Answers in ${(row.ms / 1000).toFixed(1)} s.` : row.error || 'Does not answer.'}</small>
            </li>
          ))}
        </ul>
      )}
      {learned && (
        <p className="panel-note">
          Read through the pool {learned.proxied_reads} {learned.proxied_reads === 1 ? 'time' : 'times'}; {learned.unreadable} could not be read; {learned.retirements} {learned.retirements === 1 ? 'proxy' : 'proxies'} set aside
          after failing ({learned.healthy} of {learned.pool} ready).
          {learned.blocked_hosts.length > 0 && ` Sites that refused a direct read: ${learned.blocked_hosts.map((one) => one.host).join(', ')}.`}
        </p>
      )}
    </section>
  )
}

function PoolField({ saved, onSave }: { saved: string; onSave: (value: string) => void }) {
  const [draft, setDraft] = useState(saved)
  return (
    <textarea
      className="field"
      aria-label="Proxy addresses"
      rows={3}
      spellCheck={false}
      autoComplete="off"
      placeholder={'http://proxy-1.example:8080\nhttp://proxy-2.example:8080'}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        if (draft.trim() !== saved.trim()) onSave(draft)
      }}
    />
  )
}

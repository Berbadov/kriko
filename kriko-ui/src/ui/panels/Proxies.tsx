import { useState } from 'react'
import { useProxies } from '../../engine/proxies'
import { Switch } from '../controls'
import '../../styles/providers.css'

/** Rotating proxies for pages that refuse to be read. Off by default. The one note says who sees the pages. */
export function ProxiesGroup() {
  const { doc, problem, checked, save, check, reload } = useProxies()
  if (!doc) return problem ? <p className="error-note" role="alert">Could not read proxy settings. {problem} <button className="btn" onClick={() => void reload()}>Try again</button></p> : null
  const pool = doc.pool.join('\n')
  const learned = doc.learned

  return (
    <section className="panel-group" data-tour="proxies">
      <h3>Proxies</h3>
      {problem && <p className="error-note">{problem}</p>}
      <div className="setting">
        <span>Use proxies for blocked pages</span>
        <Switch label="Use proxies for blocked pages" on={doc.enabled} onChange={(on) => void save({ proxy_enabled: on ? '1' : '0' })} />
      </div>
      {doc.enabled && !doc.active && <p className="panel-note" data-kind="warn">Add an address below to use them.</p>}
      <p className="panel-note" data-kind="data">A proxy sees which pages you read, and a site&apos;s terms may forbid it. The choice is yours.</p>
      <div className="setting stack">
        <span>Proxy addresses</span>
        <PoolField key={pool} saved={pool} onSave={(next) => void save({ proxy_pool: next })} />
      </div>
      <div className="setting">
        <span>Proxy login</span>
        <span className="state" data-tone={doc.login_saved ? 'ok' : 'none'}>{doc.login_saved ? 'Saved in Keys' : 'None saved'}</span>
      </div>
      <div className="setting">
        <span>Check the proxies</span>
        <button className="btn" onClick={() => void check()} disabled={checked === 'checking' || doc.pool.length === 0}>
          {checked === 'checking' ? 'Checking…' : 'Check now'}
        </button>
      </div>
      {Array.isArray(checked) && (
        <ul className="plain-list" aria-label="Proxy check">
          {checked.map((row) => (
            <li key={row.address}>
              <strong>{row.address}</strong>
              <span className="state" data-tone={row.ok ? 'ok' : 'risk'}>{row.ok ? `Answers in ${(row.ms / 1000).toFixed(1)} s` : row.error || 'Does not answer'}</span>
            </li>
          ))}
        </ul>
      )}
      {learned && (
        <div className="tiles">
          <div>
            <strong>{learned.proxied_reads}</strong>
            <small>read through the pool</small>
          </div>
          <div>
            <strong>{learned.unreadable}</strong>
            <small>could not be read</small>
          </div>
          <div>
            <strong>
              {learned.healthy} of {learned.pool}
            </strong>
            <small>proxies ready</small>
          </div>
        </div>
      )}
      {learned && learned.blocked_hosts.length > 0 && (
        <div className="setting">
          <span>Sites that refused a direct read</span>
          <span className="value">{learned.blocked_hosts.map((one) => one.host).join(', ')}</span>
        </div>
      )}
      <details className="disclosure">
        <summary>What proxies do here</summary>
        <p className="panel-note">
          A page that refuses a direct read (blocked, rate-limited or asking for a bot check) is read again through these proxies, one after another. Kriko does not solve CAPTCHAs, sign in or get past paywalls,
          and it follows robots.txt. A page that stays blocked is reported as could not be read. Hosted search services are not routed through the pool, and OpenSERP uses its own network settings.
        </p>
      </details>
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

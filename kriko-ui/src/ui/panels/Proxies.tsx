import { useState } from 'react'
import { useProxies } from '../../engine/proxies'
import { Switch } from '../controls'
import { Icon } from '../Icon'
import { Group, Hint, IconButton, Row, State } from './settingsParts'
import '../../styles/providers.css'

/** Rotating proxies for pages that refuse to be read. Off by default. The one note says who sees the pages. */
export function ProxiesGroup() {
  const { doc, problem, checked, save, check, reload } = useProxies()
  if (!doc) return problem ? <p className="error-note" role="alert">Could not read proxy settings. {problem} <button className="btn" onClick={() => void reload()}>Try again</button></p> : null
  const pool = doc.pool.join('\n')
  const learned = doc.learned

  return (
    <Group
      icon="server"
      title="Proxies"
      tour="proxies"
      hint={
        <Hint icon="cloudup" title="Who sees pages">
          A proxy sees which pages you read, and a site&apos;s terms may forbid it. The choice is yours.
        </Hint>
      }
    >
      {problem && <p className="error-note">{problem}</p>}
      <Row icon="swap" label="Use proxies" state={doc.enabled && !doc.active ? <State tone="warn" icon="alert">Needs an address</State> : undefined}>
        <Switch label="Use proxies for blocked pages" on={doc.enabled} onChange={(on) => void save({ proxy_enabled: on ? '1' : '0' })} />
      </Row>
      <Row icon="link" label="Addresses" stack>
        <PoolField key={pool} saved={pool} onSave={(next) => void save({ proxy_pool: next })} />
      </Row>
      <Row icon="lock" label="Login" state={<State tone={doc.login_saved ? 'ok' : 'none'}>{doc.login_saved ? 'In Keys' : 'None'}</State>}>
        <IconButton icon="retry" label={checked === 'checking' ? 'Checking the proxies' : 'Check the proxies'} onClick={() => void check()} disabled={checked === 'checking' || doc.pool.length === 0} />
      </Row>
      {Array.isArray(checked) && (
        <ul className="plain-list" aria-label="Proxy check">
          {checked.map((row) => (
            <li key={row.address}>
              <strong>{row.address}</strong>
              <State tone={row.ok ? 'ok' : 'risk'} icon={row.ok ? 'check' : 'x'}>{row.ok ? `${(row.ms / 1000).toFixed(1)} s` : row.error || 'No answer'}</State>
            </li>
          ))}
        </ul>
      )}
      {learned && (
        <div className="tiles">
          <div>
            <Icon name="swap" size={18} />
            <strong>{learned.proxied_reads}</strong>
            <small>read</small>
          </div>
          <div>
            <Icon name="alert" size={18} />
            <strong>{learned.unreadable}</strong>
            <small>unreadable</small>
          </div>
          <div>
            <Icon name="server" size={18} />
            <strong>
              {learned.healthy} of {learned.pool}
            </strong>
            <small>ready</small>
          </div>
        </div>
      )}
      {learned && learned.blocked_hosts.length > 0 && (
        <Row icon="alert" label="Refused">
          <span className="value">{learned.blocked_hosts.map((one) => one.host).join(', ')}</span>
        </Row>
      )}
      <details className="disclosure">
        <summary>
          <span className="row-label">
            <span className="row-icon" aria-hidden="true">
              <Icon name="info" size={20} />
            </span>
            <span className="row-name">How it works</span>
          </span>
        </summary>
        <p className="panel-note">
          A page that refuses a direct read (blocked, rate-limited or asking for a bot check) is read again through these proxies, one after another. Kriko does not solve CAPTCHAs, sign in or get past paywalls,
          and it follows robots.txt. A page that stays blocked is reported as could not be read. Hosted search services are not routed through the pool, and OpenSERP uses its own network settings.
        </p>
      </details>
    </Group>
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

import { useId, useState, type FormEvent } from 'react'
import { addressState, useProxies, type ProxyCheck } from '../../engine/proxies'
import { Section, Setting, State, Toggle } from './settingsParts'

/** Rotating proxies for pages that refuse to be read. Off by default. One switch
 *  turns the pool on or off; each address is a row with its state from the last check. */
export function ProxiesGroup() {
  const { doc, problem, checked, save, check, reload } = useProxies()
  const [address, setAddress] = useState('')
  const addressId = useId()
  if (!doc) return problem ? <p className="error-note" role="alert">Could not read proxy settings. {problem} <button type="button" className="k-btn" data-size="sm" onClick={() => void reload()}>Try again</button></p> : null
  const pool = doc.pool.join('\n')
  const learned = doc.learned
  const answers: ProxyCheck[] = Array.isArray(checked) ? checked : []

  const add = (event: FormEvent) => {
    event.preventDefault()
    const next = address.trim()
    if (!next) return
    setAddress('')
    void save({ proxy_pool: [...doc.pool, next].join('\n') })
  }

  return (
    <Section
      title="Proxies"
      tour="proxies"
      note="A proxy sees which pages you read, and a site's terms may forbid it. The choice is yours."
    >
      {problem && <p className="error-note">{problem}</p>}

      <Setting
        label="Use proxies"
        note="Off by default. Pages that refuse a direct read are read again through the addresses below."
        state={doc.enabled && !doc.active ? <State tone="warn" icon="alert">Needs an address</State> : undefined}
        control={<Toggle label="Use proxies for blocked pages" on={doc.enabled} onChange={(on) => void save({ proxy_enabled: on ? '1' : '0' })} />}
      />

      {doc.pool.length === 0 && <Setting label="No addresses yet" note="Add one below. Use the address your proxy gives you." />}
      {doc.pool.map((one) => {
        const state = addressState(one, checked)
        const answer = answers.find((row) => row.address === one)
        const note = answer ? (answer.ok ? `Answered in ${(answer.ms / 1000).toFixed(1)} s.` : answer.error || 'No answer.') : undefined
        return (
          <Setting
            key={one}
            label={one}
            note={note}
            state={<State tone={state.tone === 'none' ? undefined : state.tone}>{state.text}</State>}
            control={
              <button type="button" className="k-btn" data-size="sm" data-kind="danger" aria-label={`Remove ${one}`} onClick={() => void save({ proxy_pool: doc.pool.filter((x) => x !== one).join('\n') })}>
                Remove
              </button>
            }
          />
        )
      })}

      <Setting
        stack
        label="Add an address"
        note="Paste the address your proxy gives you, such as http://host:port."
        control={
          <form className="settings-add" onSubmit={add}>
            <div className="k-field">
              <label htmlFor={addressId}>Proxy address</label>
              <input id={addressId} className="k-input" type="text" autoComplete="off" spellCheck={false} placeholder="http://host:port" value={address} onChange={(event) => setAddress(event.target.value)} />
            </div>
            <button type="submit" className="k-btn" disabled={!address.trim()}>
              Add the address
            </button>
          </form>
        }
      />

      <details className="settings-fold">
        <summary>Edit all addresses at once</summary>
        <div className="settings-fold-body">
          <PoolField key={pool} saved={pool} onSave={(next) => void save({ proxy_pool: next })} />
        </div>
      </details>

      <Setting
        label="Login"
        note="The login for the proxies is kept under Keys and models."
        state={<State tone={doc.login_saved ? 'ok' : undefined}>{doc.login_saved ? 'In Keys' : 'None'}</State>}
        control={
          <button type="button" className="k-btn" disabled={checked === 'checking' || doc.pool.length === 0} onClick={() => void check()}>
            {checked === 'checking' ? 'Checking the proxies…' : 'Check the proxies'}
          </button>
        }
      />

      {learned && (
        <>
          <Setting label="Read through a proxy" note="Pages that were read this way." value={learned.proxied_reads} />
          <Setting label="Still unreadable" note="Pages that stayed blocked, and are reported as could not be read." value={learned.unreadable} />
          <Setting label="Addresses ready" note="Addresses that answered lately." value={`${learned.healthy} of ${learned.pool}`} />
        </>
      )}
      {learned && learned.blocked_hosts.length > 0 && (
        <Setting label="Refused" note="Sites that refused a read through a proxy." value={learned.blocked_hosts.map((one) => one.host).join(', ')} />
      )}

      <details className="settings-fold">
        <summary>How it works</summary>
        <div className="settings-fold-body">
          <p className="settings-note">
            A page that refuses a direct read (blocked, rate-limited or asking for a bot check) is read again through these proxies, one after another. Kriko does not solve CAPTCHAs, sign in or get past paywalls,
            and it follows robots.txt. A page that stays blocked is reported as could not be read. Hosted search services are not routed through the pool, and OpenSERP uses its own network settings.
          </p>
        </div>
      </details>
    </Section>
  )
}

/** Every address at once, one per line, for pasting a list. Saved when the field loses focus. */
function PoolField({ saved, onSave }: { saved: string; onSave: (value: string) => void }) {
  const [draft, setDraft] = useState(saved)
  return (
    <textarea
      className="k-input settings-field"
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

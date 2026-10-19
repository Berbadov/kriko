import { useEffect, useState } from 'react'
import { PRIORITIES, useBuyerProfile, useHoldings, useLedger, useWatches, type BuyerProfile, type Priority } from '../../engine/buyer'
import { useRelay } from '../../engine/cloud'
import { ago } from '../../engine/history'

const WORD: Record<Priority, string> = { price: 'Price', quality: 'Quality', durability: 'Lasting', repairability: 'Repairable', support: 'Support' }
const lines = (items: string[]) => items.join(', ')
const split = (text: string) =>
  text
    .split(/[\n,;]/)
    .map((one) => one.trim())
    .filter(Boolean)
const money = (amount: number | null | undefined, currency: string) => (amount == null ? '' : `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}${currency ? ` ${currency}` : ''}`)

/** What Kriko knows about you as a buyer, and everything it keeps. The profile
 *  reaches every question your agent is asked, and the ledger teaches it what
 *  you regret. All of it stays in a file on this computer. */
export function ForYouPanel(_: { onOpen?: (lookupId: string) => void }) {
  const profile = useBuyerProfile()
  const ledger = useLedger()
  const watching = useWatches()
  const kept = useHoldings()
  const relay = useRelay()

  if (profile.checking) return <p className="panel-note">Looking for the engine…</p>
  if (!profile.live) return <p className="panel-note">This needs the engine, because it is kept on this computer. Start Kriko and open it again.</p>

  return (
    <div className="panel-body">
      <Due ledger={ledger} />
      <Need profile={profile} />
      <Bought ledger={ledger} />
      <Watching watching={watching} relay={relay} />
      <Relay relay={relay} />
      <Kept
        kept={kept}
        onForgot={() => {
          void profile.reload()
          void ledger.reload()
          void watching.reload()
        }}
      />
    </div>
  )
}

function Due({ ledger }: { ledger: ReturnType<typeof useLedger> }) {
  const [regretFor, setRegretFor] = useState('')
  const [why, setWhy] = useState('')
  if (!ledger.due.length) return null
  return (
    <section className="panel-group" aria-label="Did it hold up?">
      <h3>Did it hold up?</h3>
      <ul className="plain-list">
        {ledger.due.map((one) => (
          <li key={one.purchase_id} className="buy-due">
            <strong>{one.name}</strong>
            <small>Bought {ago(one.bought_at)}</small>
            {regretFor === one.purchase_id ? (
              <form
                className="key-form"
                onSubmit={(event) => {
                  event.preventDefault()
                  void ledger.answer(one.purchase_id, 'regret', why)
                  setRegretFor('')
                  setWhy('')
                }}
              >
                <input value={why} onChange={(event) => setWhy(event.target.value)} placeholder="What went wrong? (optional)" aria-label="What went wrong" maxLength={300} />
                <button className="btn" type="submit">
                  Save
                </button>
              </form>
            ) : (
              <span className="buy-actions">
                <button className="btn" onClick={() => void ledger.answer(one.purchase_id, 'glad')}>
                  Glad I did
                </button>
                <button className="btn" onClick={() => void ledger.answer(one.purchase_id, 'fine')}>
                  It is fine
                </button>
                <button className="btn" onClick={() => setRegretFor(one.purchase_id)}>
                  Regret it
                </button>
                <button className="btn ghost" onClick={() => void ledger.snooze(one.purchase_id)}>
                  Ask later
                </button>
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

function Need({ profile }: { profile: ReturnType<typeof useBuyerProfile> }) {
  const [draft, setDraft] = useState<BuyerProfile>(profile.profile)
  useEffect(() => setDraft(profile.profile), [profile.profile])
  const change = (patch: Partial<BuyerProfile>) => setDraft((now) => ({ ...now, ...patch }))
  const list = (key: 'must' | 'avoid' | 'prefer' | 'distrust', label: string, hint: string) => (
    <label className="need-field">
      <span>
        {label}
        <small>{hint}</small>
      </span>
      <input value={lines(draft[key])} onChange={(event) => change({ [key]: split(event.target.value) })} aria-label={label} />
    </label>
  )
  return (
    <section className="panel-group">
      <h3>What you need</h3>
      <p className="panel-note">Kriko tells your agent this with every question, so its advice is for you and not for everyone.</p>
      <label className="need-field">
        <span>
          How you buy and use things
          <small>A sentence or two, in your words.</small>
        </span>
        <textarea value={draft.about} onChange={(event) => change({ about: event.target.value })} rows={3} maxLength={1200} aria-label="How you buy and use things" />
      </label>
      <div className="need-row">
        <label className="need-field">
          <span>Budget</span>
          <input
            inputMode="decimal"
            value={draft.budget.max ?? ''}
            onChange={(event) => change({ budget: { ...draft.budget, max: event.target.value === '' ? null : Number(event.target.value.replace(',', '.')) || null } })}
            aria-label="Budget"
          />
        </label>
        <label className="need-field">
          <span>Currency</span>
          <input value={draft.budget.currency} onChange={(event) => change({ budget: { ...draft.budget, currency: event.target.value.toUpperCase().slice(0, 3) } })} aria-label="Currency" maxLength={3} />
        </label>
      </div>
      {list('must', 'Must have', 'Separate with commas.')}
      {list('avoid', 'Avoid', 'Brands, features, anything.')}
      {list('prefer', 'Would like', 'Nice to have.')}
      {list('distrust', 'Do not trust', 'Shops and brands.')}
      <div className="need-priorities" role="group" aria-label="What matters to you">
        {PRIORITIES.map((name) => (
          <label key={name} className="need-weight">
            <span>{WORD[name]}</span>
            <input type="range" min={0} max={5} value={draft.priorities[name] ?? 3} onChange={(event) => change({ priorities: { ...draft.priorities, [name]: Number(event.target.value) } })} aria-label={`${WORD[name]}, 0 to 5`} />
            <span className="mono">{draft.priorities[name] ?? 3}</span>
          </label>
        ))}
      </div>
      <button className="btn" onClick={() => void profile.save(draft)}>
        Save
      </button>
      {profile.saved && <p className="panel-note" data-ok="true">Saved. Kriko will use it from the next question.</p>}
      {profile.problem && <p className="error-note">{profile.problem}</p>}
    </section>
  )
}

function Bought({ ledger }: { ledger: ReturnType<typeof useLedger> }) {
  const [name, setName] = useState('')
  const [price, setPrice] = useState('')
  const [asking, setAsking] = useState('')
  const { tally } = ledger
  return (
    <section className="panel-group">
      <h3>What you bought</h3>
      <p className="panel-note">
        {tally.answered === 0
          ? 'Say what you bought and Kriko will ask in a few weeks how it went. Your regrets make its next advice better.'
          : `${tally.answered} answered: ${tally.glad + tally.fine} held up, ${tally.regret} regretted.${tally.waiting ? ` ${tally.waiting} still to ask.` : ''}`}
      </p>
      {ledger.record && ledger.record.followed_and_answered > 0 && (
        <p className="panel-note">
          You followed {ledger.record.followed_and_answered} of Kriko's picks: {ledger.record.held_up} held up, {ledger.record.regretted} did not.
          {ledger.record.rate == null ? ` ${ledger.record.note}.` : ` That is ${Math.round(ledger.record.rate * 100)}%.`}
        </p>
      )}
      <form
        className="key-form"
        onSubmit={(event) => {
          event.preventDefault()
          if (!name.trim()) return
          void ledger.add(name.trim(), price.trim(), '')
          setName('')
          setPrice('')
        }}
      >
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="What did you buy?" aria-label="What did you buy" />
        <input value={price} onChange={(event) => setPrice(event.target.value)} placeholder="Price" aria-label="Price paid" inputMode="decimal" style={{ maxWidth: 90 }} />
        <button className="btn" type="submit">
          Add
        </button>
      </form>
      {ledger.items.length > 0 && (
        <ul className="plain-list">
          {ledger.items.slice(0, 12).map((one) => (
            <li key={one.purchase_id} className="buy-row">
              <strong>{one.name}</strong>
              <small>
                {[one.verdict ? { glad: 'Glad', fine: 'Fine', regret: 'Regret' }[one.verdict] : 'Waiting', money(one.price, one.currency), ago(one.bought_at), one.reason].filter(Boolean).join(' · ')}
              </small>
              {asking === one.purchase_id ? (
                <span className="past-ask">
                  <span>Delete?</span>
                  <button onClick={() => void ledger.forget(one.purchase_id)}>Delete</button>
                  <button onClick={() => setAsking('')}>Keep</button>
                </span>
              ) : (
                <button className="btn ghost" onClick={() => setAsking(one.purchase_id)}>
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {ledger.problem && <p className="error-note">{ledger.problem}</p>}
    </section>
  )
}

function Watching({ watching, relay }: { watching: ReturnType<typeof useWatches>; relay: ReturnType<typeof useRelay> }) {
  return (
    <section className="panel-group">
      <h3>Watching</h3>
      {watching.alerts.length > 0 && (
        <div className="watch-alerts" role="status">
          {watching.alerts.map((one) => (
            <p key={one.alert_id}>
              <strong>{one.name || 'A page you watch'}</strong> is {money(one.price, one.currency)}
              {one.was_price ? ` (was ${money(one.was_price, one.currency)})` : ''}.
            </p>
          ))}
          <button className="btn ghost" onClick={() => void watching.read()}>
            Got it
          </button>
        </div>
      )}
      {watching.watches.length === 0 ? (
        <p className="panel-note">Press Watch this price on a product page, and Kriko will tell you when it falls to what you choose.</p>
      ) : (
        <ul className="plain-list">
          {watching.watches.map((one) => (
            <li key={one.watch_id} className="buy-row">
              <strong>{one.name || one.url}</strong>
              <small>
                {[
                  one.last_price != null ? `Now ${money(one.last_price, one.currency)}` : 'Not read yet',
                  one.target != null ? `alert at ${money(one.target, one.currency)} or less` : '',
                  one.last_error ? one.last_error : one.last_checked ? `read ${ago(one.last_checked)}` : '',
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </small>
              {relay.status?.connected && (
                <button
                  className="btn ghost"
                  aria-pressed={one.cloud === 1}
                  disabled={relay.busy}
                  title={one.cloud ? 'The relay watches this page while this computer is off. Press to stop that.' : 'Let the relay watch this page while this computer is off. It will be told the page.'}
                  onClick={() => void relay.toggleWatch(one.watch_id, !one.cloud).then(() => watching.reload())}
                >
                  {one.cloud ? 'Watched in the cloud' : 'Watch in the cloud'}
                </button>
              )}
              <button className="btn ghost" onClick={() => void watching.stop(one.watch_id)}>
                Stop
              </button>
            </li>
          ))}
        </ul>
      )}
      {watching.problem && <p className="error-note">{watching.problem}</p>}
    </section>
  )
}

function Relay({ relay }: { relay: ReturnType<typeof useRelay> }) {
  const [server, setServer] = useState('')
  const [pairing, setPairing] = useState('')
  const [privateLabels, setPrivateLabels] = useState(true)
  const status = relay.status
  useEffect(() => {
    if (status?.suggested_server && !server) setServer(status.suggested_server)
  }, [status?.suggested_server, server])
  if (!status) return relay.problem ? <p className="error-note">{relay.problem}</p> : null
  return (
    <section className="panel-group">
      <h3>Phone and relay</h3>
      <p className="panel-note">
        A relay is a small server of your own. It keeps sealed copies of your profile, purchases and watches that only your devices can open, so your phone and this computer agree, and
        it can watch a price while this computer is off. Alerts reach a phone through ntfy.
      </p>
      {!status.connected ? (
        <>
          <form
            className="key-form"
            onSubmit={(event) => {
              event.preventDefault()
              void relay.connect(server.trim(), privateLabels)
            }}
          >
            <input value={server} onChange={(event) => setServer(event.target.value)} placeholder="https://relay.example" aria-label="The relay's address" />
            <button className="btn" type="submit" disabled={relay.busy || !server.trim()}>
              Connect
            </button>
          </form>
          <label className="inline-switch">
            <input type="checkbox" checked={privateLabels} onChange={(event) => setPrivateLabels(event.target.checked)} /> Do not tell the relay what a watched product is called
          </label>
          <form
            className="key-form"
            onSubmit={(event) => {
              event.preventDefault()
              void relay.join(pairing.trim())
            }}
          >
            <input value={pairing} onChange={(event) => setPairing(event.target.value)} placeholder="Or paste a pairing code" aria-label="A pairing code" />
            <button className="btn" type="submit" disabled={relay.busy || !pairing.trim()}>
              Join
            </button>
          </form>
        </>
      ) : (
        <>
          <p className="panel-note" data-ok="true">
            Connected to {status.server}. {status.watching} {status.watching === 1 ? 'page is' : 'pages are'} watched in the cloud.{status.synced_at ? ` Synced ${ago(status.synced_at)}.` : ''}
          </p>
          <div className="buy-actions">
            <button className="btn" disabled={relay.busy} onClick={() => void relay.sync()}>
              Sync now
            </button>
            {relay.code ? (
              <button className="btn ghost" onClick={relay.hide}>
                Hide the code
              </button>
            ) : (
              <button className="btn ghost" disabled={relay.busy} onClick={() => void relay.reveal()}>
                Pair a phone
              </button>
            )}
            <button className="btn ghost" disabled={relay.busy} onClick={() => void relay.disconnect()}>
              Disconnect
            </button>
          </div>
          {relay.code && (
            <>
              <p className="panel-note">This code is the key to your sealed copies. Give it only to your own devices.</p>
              <p className="panel-path">{relay.code}</p>
              <p className="panel-note">
                For alerts on a phone today: install the ntfy app and subscribe to the topic <span className="mono">{status.topic}</span>.
              </p>
            </>
          )}
        </>
      )}
      {relay.problem && <p className="error-note">{relay.problem}</p>}
    </section>
  )
}

function Kept({ kept, onForgot }: { kept: ReturnType<typeof useHoldings>; onForgot: () => void }) {
  const [asking, setAsking] = useState('')
  const holdings = kept.holdings
  if (!holdings) return kept.problem ? <p className="error-note">{kept.problem}</p> : null
  const rows = Object.entries(holdings.labels).map(([key, label]) => ({ key, label, count: holdings[key as keyof typeof holdings] as number }))
  return (
    <section className="panel-group">
      <h3>Kept on this computer</h3>
      <p className="panel-note">{holdings.note}</p>
      <ul className="plain-list">
        {rows.map((row) => (
          <li key={row.key} className="buy-row">
            <strong>{row.label}</strong>
            <small>{row.key === 'profile' ? (row.count ? 'Saved' : 'Nothing') : row.count === 0 ? 'Nothing' : String(row.count)}</small>
            {asking === row.key ? (
              <span className="past-ask">
                <span>Forget?</span>
                <button
                  onClick={() => {
                    setAsking('')
                    void kept.forget(row.key).then(onForgot)
                  }}
                >
                  Forget
                </button>
                <button onClick={() => setAsking('')}>Keep</button>
              </span>
            ) : (
              <button className="btn ghost" disabled={row.count === 0} onClick={() => setAsking(row.key)}>
                Forget
              </button>
            )}
          </li>
        ))}
      </ul>
      <p className="panel-path">{holdings.where}</p>
    </section>
  )
}

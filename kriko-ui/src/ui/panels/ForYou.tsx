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
 *  you regret. All of it stays in a file on this computer. Drawn inside the
 *  For you page, which has its title. Its groups are in the order the reader
 *  acts: what needs an answer first, then what is watched, then the rest. */
export function ForYouPanel(_: { onOpen?: (lookupId: string) => void }) {
  const profile = useBuyerProfile()
  const ledger = useLedger()
  const watching = useWatches()
  const kept = useHoldings()
  const relay = useRelay()

  if (profile.checking) return <p className="work-note">Looking for the engine…</p>
  if (!profile.live)
    return (
      <section className="k-empty work-empty">
        <strong>The engine is not running</strong>
        <p>This needs the engine, because it is kept on this computer. Start Kriko and open it again.</p>
      </section>
    )

  return (
    <>
      <Due ledger={ledger} />
      <Watch watching={watching} relay={relay} />
      <Bought ledger={ledger} />
      <Need profile={profile} />
      <Relay relay={relay} />
      <Kept
        kept={kept}
        onForgot={() => {
          void profile.reload()
          void ledger.reload()
          void watching.reload()
        }}
      />
    </>
  )
}

/** Each purchase the ledger is due to ask about. Nothing is due, no group. */
function Due({ ledger }: { ledger: ReturnType<typeof useLedger> }) {
  const [regretFor, setRegretFor] = useState('')
  const [why, setWhy] = useState('')
  if (!ledger.due.length) return null
  return (
    <section className="k-group" aria-label="Did it hold up?">
      <h2 className="k-caption">Needs your answer</h2>
      <p className="work-note">Did it hold up? Say how it went, and Kriko learns from it.</p>
      <div className="k-card">
        <ul className="k-list">
          {ledger.due.map((one) => (
            <li key={one.purchase_id} className="k-row work-due">
              <span className="k-row-main">
                <span className="k-row-title">{one.name}</span>
                <span className="k-row-note">Bought {ago(one.bought_at)}</span>
              </span>
              {regretFor === one.purchase_id ? (
                <form
                  className="k-row-control work-inline"
                  onSubmit={(event) => {
                    event.preventDefault()
                    void ledger.answer(one.purchase_id, 'regret', why)
                    setRegretFor('')
                    setWhy('')
                  }}
                >
                  <input className="k-input" value={why} onChange={(event) => setWhy(event.target.value)} placeholder="What went wrong? (optional)" aria-label="What went wrong" maxLength={300} />
                  <button className="k-btn" data-size="sm" data-kind="primary" type="submit">
                    Save
                  </button>
                </form>
              ) : (
                <span className="k-row-control">
                  <button className="k-btn" data-size="sm" onClick={() => void ledger.answer(one.purchase_id, 'glad')}>
                    Glad I did
                  </button>
                  <button className="k-btn" data-size="sm" onClick={() => void ledger.answer(one.purchase_id, 'fine')}>
                    It is fine
                  </button>
                  <button className="k-btn" data-size="sm" onClick={() => setRegretFor(one.purchase_id)}>
                    Regret it
                  </button>
                  <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => void ledger.snooze(one.purchase_id)}>
                    Ask later
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

/** Price alerts the watches raised, and the watches themselves. */
function Watch({ watching, relay }: { watching: ReturnType<typeof useWatches>; relay: ReturnType<typeof useRelay> }) {
  return (
    <section className="k-group" aria-label="Watching">
      <h2 className="k-caption">Watching</h2>
      {watching.alerts.length > 0 && (
        <div className="k-card" role="status">
          <ul className="k-list">
            {watching.alerts.map((one) => (
              <li key={one.alert_id} className="k-row">
                <span className="k-row-main">
                  <span className="k-row-title">{one.name || 'A page you watch'}</span>
                  <span className="k-row-note">
                    is {money(one.price, one.currency)}
                    {one.was_price ? ` (was ${money(one.was_price, one.currency)})` : ''}.
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <div className="work-card-foot">
            <button className="k-btn" data-size="sm" onClick={() => void watching.read()}>
              Got it
            </button>
          </div>
        </div>
      )}
      <div className="k-card">
        {watching.watches.length === 0 ? (
          <p className="work-note work-note-in">Press Watch this price on a product page, and Kriko will tell you when it falls to what you choose.</p>
        ) : (
          <ul className="k-list">
            {watching.watches.map((one) => (
              <li key={one.watch_id} className="k-row">
                <span className="k-row-main">
                  <span className="k-row-title">{one.name || one.url}</span>
                  <span className="k-row-note">
                    {[
                      one.last_price != null ? `Now ${money(one.last_price, one.currency)}` : 'Not read yet',
                      one.target != null ? `alert at ${money(one.target, one.currency)} or less` : '',
                      one.last_error ? one.last_error : one.last_checked ? `read ${ago(one.last_checked)}` : '',
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </span>
                <span className="k-row-control">
                  {relay.status?.connected && (
                    <button
                      className="k-btn"
                      data-size="sm"
                      aria-pressed={one.cloud === 1}
                      disabled={relay.busy}
                      title={one.cloud ? 'The relay watches this page while this computer is off. Press to stop that.' : 'Let the relay watch this page while this computer is off. It will be told the page.'}
                      onClick={() => void relay.toggleWatch(one.watch_id, !one.cloud).then(() => watching.reload())}
                    >
                      {one.cloud ? 'Watched in the cloud' : 'Watch in the cloud'}
                    </button>
                  )}
                  <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => void watching.stop(one.watch_id)}>
                    Stop
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {watching.problem && <p className="error-note">{watching.problem}</p>}
    </section>
  )
}

function Need({ profile }: { profile: ReturnType<typeof useBuyerProfile> }) {
  const [draft, setDraft] = useState<BuyerProfile>(profile.profile)
  // What the reader has typed, as typed. The profile holds lists and a number; showing those back
  // while they type removes the comma, the space and the decimal point the moment they press it.
  const [typed, setTyped] = useState<Record<string, string>>({})
  useEffect(() => {
    setDraft(profile.profile)
    setTyped({})
  }, [profile.profile])
  const change = (patch: Partial<BuyerProfile>) => setDraft((now) => ({ ...now, ...patch }))
  const list = (key: 'must' | 'avoid' | 'prefer' | 'distrust', label: string, hint: string) => (
    <label className="k-field">
      <span className="k-field-label">
        {label} <span className="work-hint">{hint}</span>
      </span>
      <input
        className="k-input"
        value={typed[key] ?? lines(draft[key])}
        onChange={(event) => {
          setTyped((now) => ({ ...now, [key]: event.target.value }))
          change({ [key]: split(event.target.value) })
        }}
        aria-label={label}
      />
    </label>
  )
  return (
    <section className="k-group" aria-label="What you need">
      <h2 className="k-caption">What you need</h2>
      <div className="k-card work-form" data-pad>
        <p className="work-note">Kriko tells your agent this with every question, so its advice is for you and not for everyone.</p>
        <label className="k-field">
          <span className="k-field-label">
            How you buy and use things <span className="work-hint">A sentence or two, in your words.</span>
          </span>
          <textarea
            className="k-input work-area"
            value={draft.about}
            onChange={(event) => change({ about: event.target.value })}
            rows={3}
            maxLength={1200}
            aria-label="How you buy and use things"
          />
        </label>
        <div className="work-pair">
          <label className="k-field">
            <span className="k-field-label">Budget</span>
            <input
              className="k-input"
              inputMode="decimal"
              value={typed.budget ?? draft.budget.max ?? ''}
              onChange={(event) => {
                const text = event.target.value
                const amount = Number(text.replace(',', '.'))
                setTyped((now) => ({ ...now, budget: text }))
                // "12." and "0." are on the way to a number: keep what was typed, change the budget
                // only when it reads as one.
                if (text.trim() === '') change({ budget: { ...draft.budget, max: null } })
                else if (Number.isFinite(amount) && amount >= 0) change({ budget: { ...draft.budget, max: amount } })
              }}
              aria-label="Budget"
            />
          </label>
          <label className="k-field">
            <span className="k-field-label">Currency</span>
            <input
              className="k-input"
              value={draft.budget.currency}
              onChange={(event) => change({ budget: { ...draft.budget, currency: event.target.value.toUpperCase().slice(0, 3) } })}
              aria-label="Currency"
              maxLength={3}
            />
          </label>
        </div>
        {list('must', 'Must have', 'Separate with commas.')}
        {list('avoid', 'Avoid', 'Brands, features, anything.')}
        {list('prefer', 'Would like', 'Nice to have.')}
        {list('distrust', 'Do not trust', 'Shops and brands.')}
        <div className="work-weights" role="group" aria-label="What matters to you">
          {PRIORITIES.map((name) => (
            <label key={name} className="work-weight">
              <span>{WORD[name]}</span>
              <input
                type="range"
                min={0}
                max={5}
                value={draft.priorities[name] ?? 3}
                onChange={(event) => change({ priorities: { ...draft.priorities, [name]: Number(event.target.value) } })}
                aria-label={`${WORD[name]}, 0 to 5`}
              />
              <span className="mono">{draft.priorities[name] ?? 3}</span>
            </label>
          ))}
        </div>
        <div className="work-card-foot">
          <button className="k-btn" data-kind="primary" onClick={() => void profile.save(draft)}>
            Save
          </button>
          {profile.saved && <span className="work-note" data-ok="true">Saved. Kriko will use it from the next question.</span>}
        </div>
        {profile.problem && <p className="error-note">{profile.problem}</p>}
      </div>
    </section>
  )
}

function Bought({ ledger }: { ledger: ReturnType<typeof useLedger> }) {
  const [name, setName] = useState('')
  const [price, setPrice] = useState('')
  const [asking, setAsking] = useState('')
  const { tally } = ledger
  return (
    <section className="k-group" aria-label="What you bought">
      <h2 className="k-caption">What you bought</h2>
      <p className="work-note">
        {tally.answered === 0
          ? 'Say what you bought and Kriko will ask in a few weeks how it went. Your regrets make its next advice better.'
          : `${tally.answered} answered: ${tally.glad + tally.fine} held up, ${tally.regret} regretted.${tally.waiting ? ` ${tally.waiting} still to ask.` : ''}`}
        {ledger.record && ledger.record.followed_and_answered > 0 && (
          <>
            {' '}
            You followed {ledger.record.followed_and_answered} of Kriko's picks: {ledger.record.held_up} held up, {ledger.record.regretted} did not.
            {ledger.record.rate == null ? ` ${ledger.record.note}.` : ` That is ${Math.round(ledger.record.rate * 100)}%.`}
          </>
        )}
      </p>
      <div className="k-card">
        <form
          className="work-add"
          onSubmit={(event) => {
            event.preventDefault()
            if (!name.trim()) return
            void ledger.add(name.trim(), price.trim(), '')
            setName('')
            setPrice('')
          }}
        >
          <input className="k-input" value={name} onChange={(event) => setName(event.target.value)} placeholder="What did you buy?" aria-label="What did you buy" />
          <input className="k-input work-price" value={price} onChange={(event) => setPrice(event.target.value)} placeholder="Price" aria-label="Price paid" inputMode="decimal" />
          <button className="k-btn" data-size="sm" type="submit">
            Add
          </button>
        </form>
        {ledger.items.length > 0 && (
          <ul className="k-list">
            {ledger.items.slice(0, 12).map((one) => (
              <li key={one.purchase_id} className="k-row">
                <span className="k-row-main">
                  <span className="k-row-title">{one.name}</span>
                  <span className="k-row-note">
                    {[one.verdict ? { glad: 'Glad', fine: 'Fine', regret: 'Regret' }[one.verdict] : 'Waiting', money(one.price, one.currency), ago(one.bought_at), one.reason].filter(Boolean).join(' · ')}
                  </span>
                </span>
                {asking === one.purchase_id ? (
                  <span className="k-row-control work-confirm">
                    <span>Delete this purchase?</span>
                    <button className="k-btn" data-size="sm" data-kind="danger" onClick={() => void ledger.forget(one.purchase_id)}>
                      Delete
                    </button>
                    <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => setAsking('')}>
                      Keep
                    </button>
                  </span>
                ) : (
                  <span className="k-row-control">
                    <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => setAsking(one.purchase_id)}>
                      Delete
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      {ledger.problem && <p className="error-note">{ledger.problem}</p>}
    </section>
  )
}

function Relay({ relay }: { relay: ReturnType<typeof useRelay> }) {
  const [server, setServer] = useState('')
  const [setup, setSetup] = useState('')
  const [pairing, setPairing] = useState('')
  const [privateLabels, setPrivateLabels] = useState(true)
  const status = relay.status
  useEffect(() => {
    if (status?.suggested_server && !server) setServer(status.suggested_server)
  }, [status?.suggested_server, server])
  if (!status) return relay.problem ? <p className="error-note">{relay.problem}</p> : null
  return (
    <section className="k-group" aria-label="Phone and relay">
      <h2 className="k-caption">Phone and relay</h2>
      <div className="k-card work-form" data-pad>
        <p className="work-note">
          A relay is a small server of your own, for you alone. It keeps sealed copies of your profile, purchases and watches that only your devices can open, so your phone and this computer agree, and
          it can watch a price while this computer is off. Alerts reach a phone through ntfy.
        </p>
        {!status.connected ? (
          <>
            <form
              className="work-inline-wide"
              onSubmit={(event) => {
                event.preventDefault()
                void relay.connect(server.trim(), setup.trim(), privateLabels)
              }}
            >
              <input className="k-input" value={server} onChange={(event) => setServer(event.target.value)} placeholder="https://relay.example" aria-label="The relay's address" />
              <input
                className="k-input work-short"
                type="password"
                value={setup}
                onChange={(event) => setSetup(event.target.value)}
                placeholder="Setup word"
                aria-label="The relay's setup word"
                autoComplete="off"
              />
              <button className="k-btn" type="submit" disabled={relay.busy || !server.trim() || !setup.trim()}>
                Connect
              </button>
            </form>
            <label className="work-check-line">
              <input type="checkbox" checked={privateLabels} onChange={(event) => setPrivateLabels(event.target.checked)} /> Do not tell the relay what a watched product is called
            </label>
            <form
              className="work-inline-wide"
              onSubmit={(event) => {
                event.preventDefault()
                void relay.join(pairing.trim())
              }}
            >
              <input className="k-input" value={pairing} onChange={(event) => setPairing(event.target.value)} placeholder="Or paste a pairing code" aria-label="A pairing code" />
              <button className="k-btn" type="submit" disabled={relay.busy || !pairing.trim()}>
                Join
              </button>
            </form>
          </>
        ) : (
          <>
            <p className="work-note" data-ok="true">
              Connected to {status.server}. {status.watching} {status.watching === 1 ? 'page is' : 'pages are'} watched in the cloud.{status.synced_at ? ` Synced ${ago(status.synced_at)}.` : ''}
            </p>
            <div className="work-card-foot">
              <button className="k-btn" disabled={relay.busy} onClick={() => void relay.sync()}>
                Sync now
              </button>
              {relay.code ? (
                <button className="k-btn" data-kind="quiet" onClick={relay.hide}>
                  Hide the code
                </button>
              ) : (
                <button className="k-btn" disabled={relay.busy} onClick={() => void relay.reveal()}>
                  Pair a phone
                </button>
              )}
              <button className="k-btn" data-kind="quiet" disabled={relay.busy} onClick={() => void relay.disconnect()}>
                Disconnect
              </button>
            </div>
            {relay.code && (
              <>
                <p className="work-note">This code is the key to your sealed copies. Give it only to your own devices.</p>
                <p className="work-path">{relay.code}</p>
                <p className="work-note">
                  For alerts on a phone today: install the ntfy app and subscribe to the topic <span className="mono">{status.topic}</span>.
                </p>
              </>
            )}
          </>
        )}
        {relay.problem && <p className="error-note">{relay.problem}</p>}
      </div>
    </section>
  )
}

function Kept({ kept, onForgot }: { kept: ReturnType<typeof useHoldings>; onForgot: () => void }) {
  const [asking, setAsking] = useState('')
  const holdings = kept.holdings
  if (!holdings) return kept.problem ? <p className="error-note">{kept.problem}</p> : null
  const rows = Object.entries(holdings.labels).map(([key, label]) => ({ key, label, count: holdings[key as keyof typeof holdings] as number }))
  return (
    <section className="k-group" aria-label="Kept on this computer">
      <h2 className="k-caption">Kept on this computer</h2>
      <p className="work-note">{holdings.note}</p>
      <div className="k-card">
        <ul className="k-list">
          {rows.map((row) => (
            <li key={row.key} className="k-row">
              <span className="k-row-main">
                <span className="k-row-title">{row.label}</span>
                <span className="k-row-note">{row.key === 'profile' ? (row.count ? 'Saved' : 'Nothing') : row.count === 0 ? 'Nothing' : String(row.count)}</span>
              </span>
              {asking === row.key ? (
                <span className="k-row-control work-confirm">
                  <span>Forget this?</span>
                  <button
                    className="k-btn"
                    data-size="sm"
                    data-kind="danger"
                    onClick={() => {
                      setAsking('')
                      void kept.forget(row.key).then(onForgot)
                    }}
                  >
                    Forget
                  </button>
                  <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => setAsking('')}>
                    Keep
                  </button>
                </span>
              ) : (
                <span className="k-row-control">
                  <button className="k-btn" data-size="sm" data-kind="quiet" disabled={row.count === 0} onClick={() => setAsking(row.key)}>
                    Forget
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
      <p className="work-path">{holdings.where}</p>
    </section>
  )
}

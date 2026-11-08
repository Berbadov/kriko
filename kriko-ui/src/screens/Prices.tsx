import { useState, type CSSProperties, type FormEvent } from 'react'
import { useWatches, type Watch } from '../engine/buyer'
import { ago } from '../engine/history'
import { DustField } from '../dust/DustField'
import { cloud } from '../dust/engine'
import { Icon } from '../ui/Icon'
import { openLink } from '../ui/ExternalLink'

const money = (amount: number | null | undefined, currency: string) =>
  amount == null ? '–' : `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}${currency ? ` ${currency}` : ''}`

/** How far the page's price moved since the watch began, as a signed share, or null. */
export function change(watch: Pick<Watch, 'started_price' | 'last_price'>): number | null {
  const { started_price: from, last_price: now } = watch
  if (from == null || now == null || from <= 0) return null
  return (now - from) / from
}

const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

/** The thin dust over the head of the page, as on the other screens. */
const SKY = cloud({ x: 0.5, y: 0.2, r: 0.3 })

/** The price checker: pages the reader watches, what each costs now, and the
 *  move since they started watching. A price is the page's own figure on the
 *  day it was read; nothing is converted or estimated. */
export function PricesScreen() {
  const watching = useWatches()
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!/^https?:\/\//i.test(url.trim())) {
      setNote('Paste the full address of a product page, starting with https://')
      return
    }
    setBusy(true)
    setNote('')
    const ok = await watching.add(url.trim(), name.trim(), target)
    setBusy(false)
    if (ok) {
      setUrl('')
      setName('')
      setTarget('')
      setNote('Watching. The first price arrives after the next read.')
    }
  }

  const checkNow = async () => {
    setBusy(true)
    const due = await watching.sweep()
    setBusy(false)
    setNote(due ? `Reading ${due} ${due === 1 ? 'page' : 'pages'} now.` : 'Every page was read recently. Kriko reads each at most every few hours.')
  }

  const fell = watching.watches.filter((one) => (change(one) ?? 0) < 0).length

  return (
    <section className="prices">
      <div className="prices-sky" aria-hidden="true">
        <DustField className="dust-sky" scene={SKY} cap={5000} />
      </div>
      <header className="prices-head">
        <div className="hello-index mono" aria-hidden="true">03 / prices</div>
        <h1>Price checker</h1>
        <p className="muted">Watch a product page. Kriko re-reads it and tells you when the price falls to what you choose.</p>
      </header>

      <form className="prices-add" onSubmit={(event) => void submit(event)}>
        <input className="prices-url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://shop.example/product…" aria-label="Product page address" />
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Name (optional)" aria-label="Name" />
        <input value={target} onChange={(event) => setTarget(event.target.value)} placeholder="Alert at or below" aria-label="Alert price" inputMode="decimal" />
        <button className="btn primary" type="submit" disabled={busy || !url.trim()}>
          <Icon name="eye" size={16} />
          Watch
        </button>
      </form>
      {(note || watching.problem) && <p className={watching.problem ? 'error-note' : 'prices-note'}>{watching.problem || note}</p>}

      {watching.alerts.length > 0 && (
        <div className="prices-alerts" role="status">
          <Icon name="bell" size={16} />
          <div>
            {watching.alerts.map((one) => (
              <p key={one.alert_id}>
                <strong>{one.name || host(one.url)}</strong> is now {money(one.price, one.currency)}
                {one.was_price ? <span className="muted"> (was {money(one.was_price, one.currency)})</span> : null}
              </p>
            ))}
          </div>
          <button className="btn ghost" onClick={() => void watching.read()}>Got it</button>
        </div>
      )}

      <div className="prices-bar">
        <h2>
          Watching <span className="mono">{watching.watches.length}</span>
          {fell > 0 && <span className="prices-fell mono">{fell} down</span>}
        </h2>
        <button className="btn ghost" onClick={() => void checkNow()} disabled={busy || !watching.watches.length}>
          <Icon name="retry" size={15} />
          Check now
        </button>
      </div>

      {watching.watches.length === 0 ? (
        <p className="prices-empty muted">
          Nothing watched yet. Paste a product page above, or press <em>Watch this price</em> on a product page in your browser.
        </p>
      ) : (
        <ul className="prices-list">
          {watching.watches.map((one, index) => {
            const moved = change(one)
            const hit = one.target != null && one.last_price != null && one.last_price <= one.target
            return (
              <li key={one.watch_id} className="price-card rise" style={{ '--i': index } as CSSProperties} data-hit={hit || undefined}>
                <button className="price-main" onClick={() => void openLink(one.url)} title={one.url}>
                  <strong>{one.name || host(one.url)}</strong>
                  <small className="mono">{host(one.url)}</small>
                </button>
                <div className="price-now">
                  <span className="price-figure mono">{money(one.last_price, one.currency)}</span>
                  {moved !== null && moved !== 0 && (
                    <span className="price-move mono" data-dir={moved < 0 ? 'down' : 'up'}>
                      {moved < 0 ? '▼' : '▲'} {Math.abs(moved * 100).toFixed(1)}%
                    </span>
                  )}
                </div>
                <small className="price-meta">
                  {[
                    one.started_price != null ? `from ${money(one.started_price, one.currency)}` : '',
                    one.target != null ? `alert at ${money(one.target, one.currency)}` : '',
                    one.last_error ? one.last_error : one.last_checked ? `read ${ago(one.last_checked)}` : 'not read yet',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </small>
                <button className="icon-btn" onClick={() => void watching.stop(one.watch_id)} aria-label={`Stop watching ${one.name || host(one.url)}`} title="Stop watching">
                  <Icon name="x" size={15} />
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

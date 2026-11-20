import { useState, type FormEvent } from 'react'
import { useWatches, type Watch } from '../engine/buyer'
import { ago } from '../engine/history'
import { moneyText, moveOf, targetReached } from '../compare/figures'
import { count } from '../ui/format'
import { Icon } from '../ui/Icon'
import { openLink } from '../ui/ExternalLink'

const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

/** The price checker: the pages the reader watches, what each costs now, and
 *  the move since they started. A price is the page's own figure on the day it
 *  was read; nothing is converted or estimated. */
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
    setNote(due ? `Reading ${count(due, 'page')} now.` : 'Every page was read recently. Kriko reads each at most every few hours.')
  }

  const watches = watching.watches
  const reached = watches.filter(targetReached).length
  let biggest: { watch: Watch; move: number } | null = null
  for (const one of watches) {
    const move = moveOf(one)
    if (move != null && move < 0 && (biggest == null || move < biggest.move)) biggest = { watch: one, move }
  }
  const fell = watches.filter((one) => (moveOf(one) ?? 0) < 0).length

  return (
    <section className="k-screen prices">
      <header className="k-head">
        <h1 className="k-title">Prices</h1>
        <div className="k-head-actions">
          <button type="button" className="k-btn" data-kind="quiet" onClick={() => void checkNow()} disabled={busy || !watches.length}>
            <Icon name="retry" size={15} />
            Check now
          </button>
        </div>
      </header>

      <section className="k-group" aria-labelledby="prices-best">
        <h2 className="k-caption" id="prices-best">Best deals</h2>
        <div className="k-kpis">
          <div className="k-kpi">
            <span className="k-kpi-value">{watches.length}</span>
            <span className="k-kpi-label">Watches</span>
          </div>
          <div className="k-kpi" data-tone={reached > 0 ? 'ok' : undefined}>
            <span className="k-kpi-value">{reached}</span>
            <span className="k-kpi-label">Targets reached</span>
          </div>
          <div className="k-kpi" data-tone={biggest ? 'ok' : undefined}>
            <span className="k-kpi-value">{biggest ? `−${Math.abs(biggest.move * 100).toFixed(1)}%` : '–'}</span>
            <span className="k-kpi-label">Biggest fall</span>
            <span className="k-kpi-fact">{biggest ? (biggest.watch.name || host(biggest.watch.url)) : 'Nothing has fallen yet'}</span>
          </div>
        </div>
      </section>

      <section className="k-group" aria-labelledby="prices-add">
        <h2 className="k-caption" id="prices-add">Watch a page</h2>
        <form className="k-card prices-form" data-pad onSubmit={(event) => void submit(event)}>
          <div className="prices-fields">
            <div className="k-field prices-field-url">
              <label htmlFor="prices-url">Page address</label>
              <input id="prices-url" className="k-input" type="text" inputMode="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://shop.example/product" />
            </div>
            <div className="k-field">
              <label htmlFor="prices-name">Name</label>
              <input id="prices-name" className="k-input" value={name} onChange={(event) => setName(event.target.value)} placeholder="Optional" />
            </div>
            <div className="k-field">
              <label htmlFor="prices-target">Target price</label>
              <input id="prices-target" className="k-input" value={target} onChange={(event) => setTarget(event.target.value)} inputMode="decimal" placeholder="At or below" />
            </div>
          </div>
          <div className="prices-form-actions">
            <button type="submit" className="k-btn" data-kind="primary" disabled={busy || !url.trim()}>
              <Icon name="eye" size={16} />
              Watch this page
            </button>
          </div>
        </form>
        {(note || watching.problem) && (
          <p className={watching.problem ? 'k-notice' : 'prices-note'} data-tone={watching.problem ? 'risk' : undefined} role={watching.problem ? 'alert' : undefined}>
            {watching.problem || note}
          </p>
        )}
      </section>

      {watching.alerts.length > 0 && (
        <div className="k-notice prices-alerts" role="status">
          <Icon name="bell" size={16} />
          <div className="prices-alerts-text">
            {watching.alerts.map((one) => (
              <p key={one.alert_id}>
                <strong>{one.name || host(one.url)}</strong> is now {moneyText(one.price, one.currency)}
                {one.was_price ? <span className="muted"> (was {moneyText(one.was_price, one.currency)})</span> : null}
              </p>
            ))}
          </div>
          <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => void watching.read()}>Got it</button>
        </div>
      )}

      <section className="k-group" aria-labelledby="prices-watching">
        <h2 className="k-caption" id="prices-watching">
          Watching <span className="mono">{watches.length}</span>
          {fell > 0 && <span className="mono prices-fell">{fell} down</span>}
        </h2>
        {watches.length === 0 ? (
          <div className="k-empty">
            <p>Nothing watched yet. Paste a product page above, or press Watch this price on a product page in your browser.</p>
          </div>
        ) : (
          <ul className="k-card k-list">
            {watches.map((one) => (
              <PriceRow key={one.watch_id} watch={one} onStop={() => void watching.stop(one.watch_id)} />
            ))}
          </ul>
        )}
      </section>
    </section>
  )
}

function PriceRow({ watch, onStop }: { watch: Watch; onStop: () => void }) {
  const label = watch.name || host(watch.url)
  const moved = moveOf(watch)
  const dropped = moved != null && moved < 0
  const hit = targetReached(watch)
  const meta = [
    watch.started_price != null ? `From ${moneyText(watch.started_price, watch.currency)}` : '',
    watch.target != null ? `Target ${moneyText(watch.target, watch.currency)}` : '',
    watch.last_error ? watch.last_error : watch.last_checked ? `Read ${ago(watch.last_checked)}` : 'Not read yet',
  ].filter(Boolean)
  return (
    <li className="prices-row" data-hit={hit || undefined}>
      <div className="prices-main">
        <span className="prices-name">{label}</span>
        <span className="prices-host">{host(watch.url)}</span>
        <span className="prices-meta">{meta.join(' · ')}</span>
      </div>
      <div className="prices-figure">
        <span className="prices-now">{moneyText(watch.last_price, watch.currency)}</span>
        {moved != null && moved !== 0 && (
          <span className="prices-move" data-dir={dropped ? 'down' : 'up'}>
            {`${dropped ? '−' : '+'}${Math.abs(moved * 100).toFixed(1)}% ${dropped ? 'down' : 'up'}`}
          </span>
        )}
        {hit && <span className="k-pill" data-tone="ok">Target reached</span>}
      </div>
      <div className="prices-row-actions">
        <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => void openLink(watch.url)} title={watch.url}>Open page</button>
        <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={onStop} aria-label={`Stop watching ${label}`}>Stop watching</button>
      </div>
    </li>
  )
}

import type { CSSProperties } from 'react'
import { useDodged } from '../engine/buyer'
import { moneyText } from '../engine/dodged'
import { ago } from '../engine/history'
import { DustField } from '../dust/DustField'
import { cloud } from '../dust/engine'
import { Icon } from '../ui/Icon'
import { openLink } from '../ui/ExternalLink'

const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

/** The thin dust over the head of the page, as on the other screens. */
const SKY = cloud({ x: 0.5, y: 0.2, r: 0.3 })

/** The products a check talked the reader out of, and the money that decision
 *  kept. A price is the listing's own figure on the day the reader decided, so
 *  the total is what they did not spend, not what the product was worth. */
export function DodgedScreen() {
  const dodged = useDodged()
  const priced = dodged.totals.filter((one) => one.priced > 0)

  return (
    <section className="dodged">
      <div className="dodged-sky" aria-hidden="true">
        <DustField className="dust-sky" scene={SKY} cap={5000} />
      </div>
      <header className="dodged-head">
        <div className="hello-index mono" aria-hidden="true">06 / dodged</div>
        <h1>Dodged bullets</h1>
        <p className="muted">Products a check talked you out of. The money is what their listings asked, not a promise about what they were worth.</p>
      </header>

      <div className="dodged-total" role="group" aria-labelledby="dodged-total-label">
        <span id="dodged-total-label" className="dodged-total-label mono">Money saved</span>
        {priced.length > 0 ? (
          <div className="dodged-sums">
            {priced.map((one) => (
              <div key={one.currency || 'none'} className="dodged-sum">
                <strong className="dodged-figure mono">{moneyText(one.amount, one.currency)}</strong>
                <small>{one.count} {one.count === 1 ? 'product' : 'products'} not bought</small>
              </div>
            ))}
            {dodged.priced < dodged.count && (
              <small className="dodged-caveat">{dodged.count - dodged.priced} without a price, so they add nothing to the total.</small>
            )}
          </div>
        ) : (
          <p className="dodged-nothing">
            {dodged.count > 0
              ? 'No price was recorded for these, so there is no total to show. Nothing is guessed.'
              : 'Nothing kept yet. The first product a check talks you out of appears here, with the price it asked.'}
          </p>
        )}
      </div>

      <div className="dodged-bar">
        <h2>
          Decided against <span className="mono">{dodged.count}</span>
        </h2>
      </div>

      {dodged.problem && <p className="error-note" role="alert">{dodged.problem}</p>}
      {!dodged.ready && dodged.live && <span className="work-line">Reads what you decided against</span>}
      {(!dodged.live || dodged.ready) && dodged.items.length === 0 && (
        <p className="dodged-empty muted">
          Nothing dodged yet. On a product page, press <em>Not buying this</em> and the check's strongest concern becomes the reason here.
        </p>
      )}
      {dodged.items.length > 0 && (
        <ul className="dodged-list">
          {dodged.items.map((one, index) => (
            <li key={one.dodge_id} className="dodge-card rise" style={{ '--i': index } as CSSProperties}>
              <div className="dodge-main">
                {one.url ? (
                  <button className="dodge-name" onClick={() => void openLink(one.url)} title={one.url}>{one.name}</button>
                ) : (
                  <strong className="dodge-name">{one.name}</strong>
                )}
                <small className="mono">{[host(one.url), ago(one.decided_at)].filter(Boolean).join(' · ')}</small>
                {one.reason && <p className="dodge-reason">{one.reason}</p>}
              </div>
              {one.price != null && <span className="dodge-price mono">{moneyText(one.price, one.currency)}</span>}
              <button className="icon-btn" onClick={() => void dodged.forget(one.dodge_id)} aria-label={`Remove ${one.name} from dodged`} title="Remove from dodged">
                <Icon name="x" size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

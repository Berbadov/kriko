import { useMemo } from 'react'
import type { Check } from '../compare/checks'
import { beforeYouBuyUsed, type UsedItem } from '../used/inspection'
import { Icon } from './Icon'

function Items({ items, from }: { items: UsedItem[]; from?: boolean }) {
  return (
    <ul className="used-items">
      {items.map((one) => (
        <li key={one.text}>
          <span>{one.text}</span>
          {from && one.from && one.from !== one.text && <small className="mono">{one.from}</small>}
        </li>
      ))}
    </ul>
  )
}

/** A calm card on a secondhand listing: what to put your hands on, what to ask
 *  the seller, and a repair price only when the check already quotes one. It
 *  draws nothing on a new-product page or when the check carries no finding and
 *  no identity to work from. */
export function UsedCard({ check }: { check: Check }) {
  const card = useMemo(() => beforeYouBuyUsed({
    url: check.url ?? '',
    name: check.name,
    risks: check.risks,
    identity: check.identity,
    assumed: check.assumed,
    subjects: check.subjects,
  }), [check])

  if (!card) return null
  return (
    <section className="used-card" aria-labelledby="used-title">
      <header className="used-head">
        <span className="used-mark"><Icon name="shieldcheck" size={18} /></span>
        <div>
          <h2 id="used-title">Before you buy used</h2>
          <p className="muted">A {card.market.name} listing. The check points at what to look at, not at a verdict on this unit.</p>
        </div>
      </header>
      <div className="used-grid">
        {card.inspect.length > 0 && (
          <div className="used-group">
            <h3>What to inspect</h3>
            <Items items={card.inspect} from />
          </div>
        )}
        {card.ask.length > 0 && (
          <div className="used-group">
            <h3>What to ask</h3>
            <Items items={card.ask} />
          </div>
        )}
        {card.leverage.length > 0 && (
          <div className="used-group">
            <h3>Negotiation leverage</h3>
            <Items items={card.leverage} from />
            <p className="used-quote-note">Quoted repair or part costs from the finding's own source. They are historical quotes, not this seller's price.</p>
          </div>
        )}
      </div>
    </section>
  )
}

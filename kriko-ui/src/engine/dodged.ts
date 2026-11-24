import type { Risk } from '../compare/checks'

/** What the reader decided *not* to buy, and the money that decision kept. Kept
 *  in `app.sqlite` beside the purchases: a dodge is the reader's own record,
 *  never page content, so no pack update can touch it. */

export interface Dodge {
  dodge_id: string
  name: string
  url: string
  price: number | null
  currency: string
  reason: string
  decided_at: string
}

/** One currency's running total. `count` includes dodges that carried no price. */
export interface DodgeTotal {
  currency: string
  amount: number
  count: number
  /** How many of `count` carried a price; a zero-priced row still counts here. */
  priced: number
}

export interface DodgedListing {
  items: Dodge[]
  totals: DodgeTotal[]
  /** Every dodged product, priced or not. */
  count: number
  /** How many of them carried a price, so the total can say how much it is based on. */
  priced: number
}

const LEVEL_RANK: Record<Risk['level'], number> = { critical: 4, high: 3, medium: 2, low: 1, unrated: 0 }

/** The finding to prefill the reason with: the gravest one the reader saw. */
export function strongestConcern(risks: Risk[]): string {
  let best: Risk | null = null
  for (const risk of risks) {
    if (!best || LEVEL_RANK[risk.level] > LEVEL_RANK[best.level]) best = risk
  }
  return best?.title.trim() ?? ''
}

/** A total as the screen writes it, with the currency only when the row had one. */
export function moneyText(amount: number, currency: string): string {
  const figure = amount.toLocaleString(undefined, { maximumFractionDigits: 2 })
  return currency ? `${figure} ${currency}` : figure
}

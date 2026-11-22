import type { Watch } from '../../engine/buyer'
import { quoteFromWatch } from '../../engine/procurement'
import type { WatchSubject } from './watchSubjects'

/** What "Add as a quote" will create, and when it cannot. Pure. */

export const QUOTE_CURRENCIES = ['TRY', 'EUR', 'USD'] as const
export const NEW_ESTIMATE = '__new'
export const DEFAULT_ESTIMATE_NAME = 'Untitled estimate'

/** The plain reason the button is disabled, or an empty string when it is not. */
export function whyNotQuote(watch: Pick<Watch, 'last_price'>, live: boolean): string {
  if (!live) return 'Needs the engine.'
  if (watch.last_price == null) return 'This page has no price yet. Check it first.'
  return ''
}

export interface QuoteChoice {
  watch: Watch
  subject: WatchSubject | null
  /** An estimate's id, or NEW_ESTIMATE. */
  estimate: string
  newName: string
  quantity: string
  /** The currency typed in the dialog; only used when the watch has none. */
  currency: string
}

export const quantityOf = (text: string): number | null => {
  const n = Number(text.trim().replace(',', '.'))
  return Number.isFinite(n) && n > 0 && n <= 100000 ? n : null
}

/** The currency the quote will carry: the watch's own, else the reader's pick, else none yet. */
export const currencyFor = (watch: Pick<Watch, 'currency'>, picked: string) => (watch.currency || picked || '').toUpperCase()

/** What is still missing before the quote can be added, in words. Empty means ready. */
export function missingFor(choice: QuoteChoice): string {
  if (choice.watch.last_price == null) return 'This page has no price yet. Check it first.'
  if (!choice.subject) return 'Choose the product this price is for.'
  if (!currencyFor(choice.watch, choice.currency)) return 'Choose the currency of the price.'
  if (!choice.estimate) return 'Choose an estimate.'
  if (quantityOf(choice.quantity) == null) return 'Quantity is a number above zero.'
  return ''
}

/** The arguments for `addToEstimate`: the watch's page as the vendor, its last price and currency, today's date. */
export function quoteRequest(choice: QuoteChoice) {
  const quote = { ...quoteFromWatch(choice.watch), currency: currencyFor(choice.watch, choice.currency) }
  const base = {
    subject: choice.subject as WatchSubject,
    quote,
    quantity: quantityOf(choice.quantity) ?? 1,
  }
  return choice.estimate === NEW_ESTIMATE
    ? { ...base, newName: choice.newName.trim() || DEFAULT_ESTIMATE_NAME }
    : { ...base, estimateId: choice.estimate }
}

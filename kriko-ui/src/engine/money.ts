/** Currency arithmetic for the Estimate screen.
 *
 *  One direction, everywhere: a rate is **TRY per one unit** of a currency,
 *  which is how TCMB publishes its bulletin. Converting A to B is
 *  `amount * rate[A] / rate[B]`, so the table needs no second copy and an
 *  estimate in EUR, TRY or USD reads the same numbers.
 *
 *  A missing rate is missing: `convert` returns null and the screen says the
 *  quote cannot be compared. It never falls back to 1. The one exception is an
 *  amount already in the target currency, which converts at 1 by definition.
 */

export type Rates = Record<string, number | string | undefined>

export function rateOf(currency: string, rates: Rates): number | null {
  const raw = rates[String(currency || '').toUpperCase()]
  const value = typeof raw === 'number' ? raw : Number(raw)
  return Number.isFinite(value) && value > 0 ? value : null
}

export function convert(amount: number | null, from: string, to: string, rates: Rates): number | null {
  if (amount == null || !Number.isFinite(amount)) return null
  // The same currency on both sides cancels: no rate is needed, and none is invented.
  if (String(from || '').toUpperCase() === String(to || '').toUpperCase()) return amount
  const source = rateOf(from, rates)
  const target = rateOf(to, rates)
  if (source == null || target == null) return null
  return (amount * source) / target
}

export interface QuoteMoney {
  /** What the vendor's number means before conversion. */
  typed: number | null
  currency: string
  net: number | null
  vat: number | null
  gross: number | null
  /** Gross, in the estimate's currency; null when no rate is known. */
  landed: number | null
}

/** One quote's net, VAT and gross at its own rate and the estimate's currency. */
export function quoteMoney(
  quote: { unit_price: number | null; currency?: string; vat_rate?: number | null; vat_included?: boolean | null },
  estimateCurrency: string,
  rates: Rates,
): QuoteMoney {
  const currency = (quote.currency || estimateCurrency || '').toUpperCase()
  const typed = quote.unit_price
  const rate = Math.max(0, Number(quote.vat_rate ?? 0)) / 100
  let net: number | null = null
  let vat: number | null = null
  let gross: number | null = null
  if (typed != null) {
    if (quote.vat_included) {
      gross = typed
      net = typed / (1 + rate)
      vat = typed - net
    } else {
      net = typed
      vat = typed * rate
      gross = typed + vat
    }
  }
  return {
    typed, currency, net, vat, gross,
    landed: convert(gross, currency, estimateCurrency, rates),
  }
}

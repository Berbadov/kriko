import type { EstimateLine, EstimateQuote } from '../engine/estimates'
import { quoteMoney, type Rates } from '../engine/money'

/** The vendor quotes under one Estimate line.
 *
 *  Each row is typed by the reader. The engine computes a risk level and a
 *  landed-cost order when it reads the estimate; until then the row shows the
 *  same arithmetic the engine will use, so nothing is promised before it is
 *  saved and nothing disappears after.
 *
 *  The number in `unit_price` is whatever the reader typed. `vat_included`
 *  says whether it already carries the line's VAT rate, and the two amounts
 *  beside it are the net and gross reading of that one number.
 */

const CURRENCIES = ['TRY', 'EUR', 'USD']

const RISK_WORDS: Record<string, string> = {
  red: 'High risk',
  amber: 'Check seller',
  green: 'Known site',
  unknown: 'Unverified',
}

const money = (amount: number | null | undefined, currency: string) =>
  amount == null ? '—' : `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`

interface Props {
  line: EstimateLine
  index: number
  currency: string
  rates: Rates
  onChange: (index: number, patch: Partial<EstimateLine>) => void
  onRemoveLine: (index: number) => void
}

export function QuoteRows({ line, index, currency, rates, onChange, onRemoveLine }: Props) {
  const quotes = line.quotes ?? []
  const patchQuote = (quoteIndex: number, patch: Partial<EstimateQuote>) => {
    onChange(index, {
      quotes: quotes.map((quote, i) => (i === quoteIndex ? { ...quote, ...patch } : quote)),
    })
  }
  const select = (quoteIndex: number) => {
    onChange(index, { quotes: quotes.map((quote, i) => ({ ...quote, selected: i === quoteIndex })) })
  }
  const add = () => {
    onChange(index, {
      quotes: [...quotes, {
        vendor: '', seller: '', url: '', unit_price: null, currency,
        vat_rate: 20, vat_included: false, delivery_days: null, warranty_months: null,
        quote_date: '', valid_until: '', note: '',
        selected: quotes.length === 0,
      }],
    })
  }
  const remove = (quoteIndex: number) => {
    const kept = quotes.filter((_, i) => i !== quoteIndex)
    if (quotes[quoteIndex]?.selected && kept.length) kept[0] = { ...kept[0], selected: true }
    onChange(index, { quotes: kept })
  }

  return (
    <div className="quote-block">
      <div className="quote-head">
        <span className="quote-title">Quotes</span>
        <button type="button" className="btn ghost" onClick={add}>Add quote</button>
        <button type="button" className="btn ghost" onClick={() => onRemoveLine(index)}>Remove line</button>
      </div>
      {quotes.length === 0 && (
        <p className="muted quote-empty">No quote yet. The price is entered on the line and counts as one quote.</p>
      )}
      {(line.ranking?.length ?? 0) > 1 && (
        <p className="quote-rank">
          Landed order: {line.ranking!.map((row) => {
            const quote = quotes.find((one) => one.quote_id === row.quote_id)
            const name = quote?.vendor || 'unnamed'
            return row.landed == null ? `${name} (unranked)` : `#${row.rank} ${name} ${money(row.landed, currency)}`
          }).join(' · ')}
        </p>
      )}
      {quotes.map((quote, quoteIndex) => {
        const read = quoteMoney(quote, currency, rates)
        const risk = quote.risk
        return (
          <div className={`quote-row${quote.selected ? ' is-selected' : ''}`} key={quote.quote_id || `draft-${quoteIndex}`}>
            <label className="quote-pick" title="This quote drives the line total">
              <input type="radio" name={`pick-${line.line_id || index}`} checked={quote.selected} onChange={() => select(quoteIndex)} aria-label={`Use ${quote.vendor || `quote ${quoteIndex + 1}`} for this line`} />
            </label>
            <div className="quote-fields">
              <input value={quote.vendor} onChange={(event) => patchQuote(quoteIndex, { vendor: event.target.value })} placeholder="Vendor" aria-label="Vendor" />
              <input value={quote.seller} onChange={(event) => patchQuote(quoteIndex, { seller: event.target.value })} placeholder="Seller on the page" aria-label="Seller" />
              <input value={quote.url} onChange={(event) => patchQuote(quoteIndex, { url: event.target.value })} placeholder="Quote URL" aria-label="Quote URL" />
              <span className="quote-money">
                <input inputMode="decimal" value={quote.unit_price == null ? '' : String(quote.unit_price)} onChange={(event) => {
                  const parsed = Number.parseFloat(event.target.value)
                  patchQuote(quoteIndex, { unit_price: event.target.value.trim() === '' || !Number.isFinite(parsed) ? null : parsed })
                }} placeholder="—" aria-label="Quoted unit price" />
                <select value={quote.currency || currency} onChange={(event) => patchQuote(quoteIndex, { currency: event.target.value })} aria-label="Quote currency">
                  {CURRENCIES.map((code) => <option key={code} value={code}>{code}</option>)}
                </select>
              </span>
              <label className="quote-check">
                <input type="checkbox" checked={quote.vat_included} onChange={(event) => patchQuote(quoteIndex, { vat_included: event.target.checked })} />
                gross
              </label>
              <label className="quote-vat">
                VAT <input inputMode="decimal" value={String(quote.vat_rate)} onChange={(event) => {
                  const parsed = Number.parseFloat(event.target.value)
                  patchQuote(quoteIndex, { vat_rate: Number.isFinite(parsed) ? parsed : 0 })
                }} aria-label="VAT rate" />%
              </label>
              <label className="quote-small">Delivery <input inputMode="numeric" value={quote.delivery_days ?? ''} onChange={(event) => {
                const parsed = Number.parseInt(event.target.value, 10)
                patchQuote(quoteIndex, { delivery_days: Number.isFinite(parsed) ? parsed : null })
              }} aria-label="Delivery days" />d</label>
              <label className="quote-small">Warranty <input inputMode="numeric" value={quote.warranty_months ?? ''} onChange={(event) => {
                const parsed = Number.parseInt(event.target.value, 10)
                patchQuote(quoteIndex, { warranty_months: Number.isFinite(parsed) ? parsed : null })
              }} aria-label="Warranty months" />mo</label>
              <label className="quote-small">Valid until <input type="date" value={quote.valid_until} onChange={(event) => patchQuote(quoteIndex, { valid_until: event.target.value })} aria-label="Valid until" /></label>
            </div>
            <div className="quote-figures">
              <span title="Before VAT">Net {money(read.net, read.currency)}</span>
              <span title="VAT at this line's rate">VAT {money(read.vat, read.currency)}</span>
              <strong title="What is paid">Gross {money(read.gross, read.currency)}</strong>
              {read.currency !== currency && (
                <span className={read.landed == null ? 'quote-warn' : ''} title={read.landed == null ? 'Enter this currency\u2019s rate above to compare it' : `Converted at the stated rate`}>
                  {read.landed == null ? `No ${read.currency} rate` : `= ${money(read.landed, currency)}`}
                </span>
              )}
              {risk && (
                <span className="quote-risk" data-level={risk.level} title={risk.reasons.join(' · ')}>{RISK_WORDS[risk.level] ?? risk.level}</span>
              )}
              {risk && <span className="quote-why">{risk.reasons[0]}</span>}
            </div>
            <button type="button" className="icon-btn" onClick={() => remove(quoteIndex)} aria-label={`Remove quote ${quote.vendor || quoteIndex + 1}`} title="Remove quote">
              ×
            </button>
          </div>
        )
      })}
    </div>
  )
}


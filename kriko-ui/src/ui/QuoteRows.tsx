import { useState } from 'react'
import type { EstimateLine, EstimateQuote } from '../engine/estimates'
import type { Rates } from '../engine/money'
import { expiryWord, quoteViews, verdictOf, verdictText, type QuoteView } from '../engine/quotes'
import { RiskMark, type RiskLevel } from './RiskMark'

/** The vendor quotes under one line, compared.
 *
 *  One row per quote: the price as typed, its net, VAT and gross in its own
 *  currency, the landed cost in the estimate's currency with its rank, and the
 *  terms. A quote with no rate says "No rate" and is left out of the ranking.
 *  The verdict above the table is computed from those same numbers. A quote is
 *  edited in a labelled form under the table, one at a time.
 */

const CURRENCIES = ['TRY', 'EUR', 'USD']
const MAX_QUOTES = 20
/** Each column's share of the card, in table order; the table is fixed-layout so it fits the card. */
const QUOTE_COLUMN_SHARE = [11, 10, 10, 9, 10, 10, 7, 8, 10, 15]

const amount = (value: number | null | undefined, currency: string) =>
  value == null ? '–' : `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`

interface Props {
  line: EstimateLine
  index: number
  currency: string
  rates: Rates
  onChange: (index: number, patch: Partial<EstimateLine>) => void
}

const BLANK_QUOTE = (currency: string): EstimateQuote => ({
  vendor: '', seller: '', url: '', unit_price: null, currency,
  vat_rate: 20, vat_included: false, delivery_days: null, warranty_months: null,
  quote_date: '', valid_until: '', note: '', selected: false,
})

const numberOrNull = (value: string) => {
  const parsed = Number.parseFloat(value)
  return value.trim() === '' || !Number.isFinite(parsed) ? null : parsed
}

const wholeOrNull = (value: string) => {
  const parsed = Number.parseInt(value, 10)
  return value.trim() === '' || !Number.isFinite(parsed) ? null : parsed
}

export function QuoteRows({ line, index, currency, rates, onChange }: Props) {
  const quotes = line.quotes ?? []
  const views = quoteViews(line, currency, rates)
  const verdict = verdictOf(views)
  const [editing, setEditing] = useState<number | null>(null)

  const patchQuote = (quoteIndex: number, patch: Partial<EstimateQuote>) => {
    onChange(index, { quotes: quotes.map((quote, i) => (i === quoteIndex ? { ...quote, ...patch } : quote)) })
  }
  const select = (quoteIndex: number) => {
    onChange(index, { quotes: quotes.map((quote, i) => ({ ...quote, selected: i === quoteIndex })) })
  }
  const add = () => {
    if (quotes.length >= MAX_QUOTES) return
    const next = [...quotes, { ...BLANK_QUOTE(currency), selected: quotes.length === 0 }]
    onChange(index, { quotes: next })
    setEditing(next.length - 1)
  }
  const remove = (quoteIndex: number) => {
    const kept = quotes.filter((_, i) => i !== quoteIndex)
    if (quotes[quoteIndex]?.selected && kept.length) kept[0] = { ...kept[0], selected: true }
    onChange(index, { quotes: kept })
    setEditing(null)
  }

  const editingQuote = editing != null ? quotes[editing] : undefined

  return (
    <div className="procurement-quotes">
      <p className="procurement-verdict" data-state={verdict.best ? 'ready' : 'none'}>
        {verdictText(verdict, currency)}
      </p>

      {quotes.length === 0 ? (
        <p className="procurement-quotes-empty">No quote yet. Add a quote from a vendor to compare it with the others.</p>
      ) : (
        <div className="procurement-quotes-scroll">
          <table className="k-table procurement-quote-table">
            <caption className="procurement-visually-hidden">Quotes for {line.label}, compared in {currency}</caption>
            <colgroup>
              {QUOTE_COLUMN_SHARE.map((share, at) => <col key={at} style={{ width: `${share}%` }} />)}
            </colgroup>
            <thead>
              <tr>
                <th scope="col">Vendor</th>
                <th scope="col" data-num>Price as typed</th>
                <th scope="col" data-num>Net</th>
                <th scope="col" data-num>VAT</th>
                <th scope="col" data-num>Gross</th>
                <th scope="col" data-num>Landed, {currency}</th>
                <th scope="col" data-num>Delivery</th>
                <th scope="col" data-num>Warranty</th>
                <th scope="col">Valid until</th>
                <th scope="col">Risk</th>
              </tr>
            </thead>
            <tbody>
              {views.map((view) => (
                <QuoteTableRow
                  key={view.quote.quote_id || `draft-${view.index}`}
                  view={view}
                  currency={currency}
                  comparable={verdict.comparable}
                  editing={editing === view.index}
                  onSelect={() => select(view.index)}
                  onEdit={() => setEditing(editing === view.index ? null : view.index)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editingQuote && editing != null && (
        <form className="procurement-quote-form" aria-label={`Edit quote ${editingQuote.vendor || editing + 1} for ${line.label}`} onSubmit={(event) => event.preventDefault()}>
          <div className="procurement-fields">
            <label className="k-field">
              <span>Vendor</span>
              <input className="k-input" value={editingQuote.vendor} onChange={(event) => patchQuote(editing, { vendor: event.target.value })} />
            </label>
            <label className="k-field">
              <span>Seller on the page</span>
              <input className="k-input" value={editingQuote.seller} onChange={(event) => patchQuote(editing, { seller: event.target.value })} />
            </label>
            <label className="k-field procurement-field-wide">
              <span>Quote link</span>
              <input className="k-input" type="url" value={editingQuote.url} onChange={(event) => patchQuote(editing, { url: event.target.value })} />
            </label>
            <label className="k-field">
              <span>Price as typed</span>
              <input className="k-input" inputMode="decimal" value={editingQuote.unit_price == null ? '' : String(editingQuote.unit_price)} onChange={(event) => patchQuote(editing, { unit_price: numberOrNull(event.target.value) })} placeholder="No price yet" />
            </label>
            <label className="k-field">
              <span>Price currency</span>
              <select className="k-input" value={editingQuote.currency || currency} onChange={(event) => patchQuote(editing, { currency: event.target.value })}>
                {CURRENCIES.map((code) => <option key={code} value={code}>{code}</option>)}
              </select>
            </label>
            <label className="procurement-check">
              <input type="checkbox" checked={editingQuote.vat_included} onChange={(event) => patchQuote(editing, { vat_included: event.target.checked })} />
              <span>The price includes VAT</span>
            </label>
            <label className="k-field">
              <span>VAT rate, %</span>
              <input className="k-input" inputMode="decimal" value={String(editingQuote.vat_rate)} onChange={(event) => {
                const parsed = Number.parseFloat(event.target.value)
                patchQuote(editing, { vat_rate: Number.isFinite(parsed) ? parsed : 0 })
              }} />
            </label>
            <label className="k-field">
              <span>Delivery, days</span>
              <input className="k-input" inputMode="numeric" value={editingQuote.delivery_days == null ? '' : String(editingQuote.delivery_days)} onChange={(event) => patchQuote(editing, { delivery_days: wholeOrNull(event.target.value) })} />
            </label>
            <label className="k-field">
              <span>Warranty, months</span>
              <input className="k-input" inputMode="numeric" value={editingQuote.warranty_months == null ? '' : String(editingQuote.warranty_months)} onChange={(event) => patchQuote(editing, { warranty_months: wholeOrNull(event.target.value) })} />
            </label>
            <label className="k-field">
              <span>Valid until</span>
              <input className="k-input" type="date" value={editingQuote.valid_until} onChange={(event) => patchQuote(editing, { valid_until: event.target.value })} />
            </label>
            <label className="k-field">
              <span>Quote date</span>
              <input className="k-input" type="date" value={editingQuote.quote_date} onChange={(event) => patchQuote(editing, { quote_date: event.target.value })} />
            </label>
            <label className="k-field procurement-field-wide">
              <span>Note</span>
              <input className="k-input" value={editingQuote.note} onChange={(event) => patchQuote(editing, { note: event.target.value })} />
            </label>
          </div>
          <div className="procurement-form-actions">
            <button type="button" className="k-btn" data-kind="danger" data-size="sm" onClick={() => remove(editing)}>Remove this quote</button>
            <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => setEditing(null)}>Done</button>
          </div>
        </form>
      )}

      <div className="procurement-quote-actions">
        <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={add} disabled={quotes.length >= MAX_QUOTES}>
          Add a quote
        </button>
        {quotes.length >= MAX_QUOTES && <span className="procurement-quote-limit">A line holds at most {MAX_QUOTES} quotes.</span>}
      </div>
    </div>
  )
}

function QuoteTableRow({ view, currency, comparable, editing, onSelect, onEdit }: {
  view: QuoteView
  currency: string
  comparable: number
  editing: boolean
  onSelect: () => void
  onEdit: () => void
}) {
  const { quote, read } = view
  const level: RiskLevel = quote.risk?.level ?? 'unknown'
  const expiry = expiryWord(view.expiresInDays)
  const expired = view.expiresInDays != null && view.expiresInDays < 0
  const name = quote.vendor?.trim() || 'Unnamed vendor'
  return (
    <tr className={view.selected ? 'procurement-quote-selected' : undefined} data-selected={view.selected ? 'true' : 'false'}>
      <td>
        <strong>{name}</strong>
        {quote.seller && <span className="procurement-quote-sub">{quote.seller}</span>}
        <span className="procurement-quote-row-actions">
          {view.selected ? (
            <span className="k-pill" data-tone="ok">Selected</span>
          ) : (
            <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={onSelect}>Use this quote</button>
          )}
          <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={onEdit} aria-expanded={editing}>
            {editing ? 'Close' : 'Edit'}
          </button>
        </span>
      </td>
      <td data-num>
        {view.unpriced ? '–' : <>{amount(quote.unit_price, quote.currency || currency)}<span className="procurement-quote-sub">{quote.vat_included ? 'gross' : 'net'}</span></>}
      </td>
      <td data-num>{view.unpriced ? '–' : amount(read.net, read.currency)}</td>
      <td data-num>{view.unpriced ? '–' : amount(read.vat, read.currency)}</td>
      <td data-num>{view.unpriced ? '–' : amount(read.gross, read.currency)}</td>
      <td data-num>
        {view.unpriced && '–'}
        {view.noRate && <span className="procurement-warn">No rate</span>}
        {view.landed != null && (
          <>
            {amount(view.landed, currency)}
            {view.rank != null && <span className="procurement-quote-sub">#{view.rank} of {comparable}</span>}
          </>
        )}
      </td>
      <td data-num>{quote.delivery_days != null ? `${quote.delivery_days} days` : '–'}</td>
      <td data-num>{quote.warranty_months != null ? `${quote.warranty_months} mo` : '–'}</td>
      <td>
        {quote.valid_until ? (
          <>
            <span className="procurement-nowrap">{quote.valid_until}</span>
            <span className={expired ? 'procurement-warn' : 'procurement-quote-sub'}>{expiry}</span>
          </>
        ) : '–'}
      </td>
      <td>
        <RiskMark level={level}>{quote.risk?.reasons?.length ? quote.risk.reasons.join(' · ') : undefined}</RiskMark>
      </td>
    </tr>
  )
}

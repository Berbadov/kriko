import { useEffect, useMemo, useState } from 'react'
import { useEngine } from '../../engine/Engine'
import { useProcurement } from '../../engine/procurement'
import { expiryWord } from '../../engine/quotes'
import { foldText, vendorKey, vendorQuotes, vendorSentence, vendorStats, type VendorQuote, type VendorStats } from '../../engine/vendors'
import { copyText } from '../../ui/clipboard'
import { RiskMark, type RiskLevel } from '../../ui/RiskMark'
import { EMPTY, money } from './format'

/** The vendor scorecard: the vendors across the reader's estimates, each with
 *  its sentence and its quotes. Every number comes from `vendorStats`; this
 *  screen only draws it and sends the reader to the estimate a quote is on.
 */

/** `useProcurement` reads the most recently updated estimates, this many at most. */
const RECENT_ESTIMATES = 12

const plural = (count: number, one: string, many: string) => (count === 1 ? one : many)

const priceOf = (quote: VendorQuote['quote']) => (quote.unit_price == null ? EMPTY : money(quote.unit_price, quote.currency))

function landedWord(row: VendorQuote): string {
  if (row.quote.unit_price == null) return 'No price'
  if (row.landed == null) return 'No rate'
  return money(row.landed, row.currency)
}

const riskWord = (level: RiskLevel | undefined) => ({ green: 'Low', amber: 'Medium', red: 'High', unknown: 'Not rated' })[level ?? 'unknown']

/** The quotes as plain text: the sentence, then one tab-separated line per quote. */
function summaryOf(stat: VendorStats, rows: VendorQuote[]): string {
  const lines = [stat.vendor, vendorSentence(stat), '']
  lines.push(['Product', 'Estimate', 'Price as typed', 'Landed', 'Delivery', 'Warranty', 'Valid until', 'Risk'].join('\t'))
  for (const row of rows) {
    lines.push([
      row.label,
      row.estimateName,
      priceOf(row.quote),
      landedWord(row),
      row.quote.delivery_days != null ? `${row.quote.delivery_days} ${plural(row.quote.delivery_days, 'day', 'days')}` : EMPTY,
      row.quote.warranty_months != null ? `${row.quote.warranty_months} ${plural(row.quote.warranty_months, 'month', 'months')}` : EMPTY,
      row.quote.valid_until ? `${row.quote.valid_until}, ${expiryWord(row.expiresInDays)}` : 'No date',
      riskWord(row.quote.risk?.level),
    ].join('\t'))
  }
  return lines.join('\n')
}

export function VendorScorecard() {
  const { mode } = useEngine()
  const { loading, problem, estimates } = useProcurement()
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [copied, setCopied] = useState('')

  const stats = useMemo(() => vendorStats(estimates), [estimates])
  const rowsByKey = useMemo(() => {
    const groups = new Map<string, VendorQuote[]>()
    for (const row of vendorQuotes(estimates)) {
      const group = groups.get(row.key)
      if (group) group.push(row)
      else groups.set(row.key, [row])
    }
    return groups
  }, [estimates])

  // The "Copied" word goes back to "Copy summary" after a moment.
  useEffect(() => {
    if (!copied) return undefined
    const timer = window.setTimeout(() => setCopied(''), 1600)
    return () => window.clearTimeout(timer)
  }, [copied])

  if (mode !== 'live') {
    return (
      <div className="k-empty vendors-empty">
        <strong>Vendors need the engine</strong>
        <p>Connect Kriko&rsquo;s engine to see how each vendor&rsquo;s quotes compare across your estimates.</p>
      </div>
    )
  }

  const needle = foldText(query.trim())
  const shown = needle ? stats.filter((stat) => foldText(stat.vendor).includes(needle)) : stats

  const toggle = (key: string) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const openEstimate = (estimateId: string) => {
    // The Procurement screen is already the one on show; the event asks it to open the estimate.
    window.dispatchEvent(new CustomEvent('kriko:navigate', { detail: { screen: 'estimate' } }))
    window.dispatchEvent(new CustomEvent('kriko:open-estimate', { detail: { estimateId } }))
  }

  const copy = async (stat: VendorStats) => {
    const ok = await copyText(summaryOf(stat, rowsByKey.get(vendorKey(stat.vendor)) ?? []))
    setCopied(ok ? stat.vendor : '')
  }

  return (
    <div className="vendors">
      <label className="k-field vendors-search">
        <span>Find a vendor</span>
        <input
          className="k-input"
          type="search"
          value={query}
          placeholder="A vendor's name"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {estimates.length === RECENT_ESTIMATES && (
        <p className="vendors-basis">Based on your {RECENT_ESTIMATES} most recent estimates</p>
      )}
      {problem && <p className="k-notice" role="status">{problem}</p>}

      {stats.length === 0 ? (
        loading ? (
          <p className="vendors-loading" role="status">Reading estimates…</p>
        ) : (
          <div className="k-empty">
            <strong>No vendors yet</strong>
            <p>No vendors yet. Add a quote to a line and its vendor appears here.</p>
          </div>
        )
      ) : shown.length === 0 ? (
        <div className="k-empty">
          <strong>No vendor matches</strong>
          <p>No vendor is called &ldquo;{query.trim()}&rdquo;. Try part of the name.</p>
        </div>
      ) : (
        <div className="k-card k-list vendors-list">
          {shown.map((stat) => {
            const key = vendorKey(stat.vendor)
            const isOpen = expanded.has(key)
            const rows = rowsByKey.get(key) ?? []
            const panel = `vendors-panel-${key.replace(/[^a-z0-9]+/g, '-')}`
            return (
              <div className="vendors-item" key={stat.vendor}>
                <div className="k-row vendors-row" data-on={isOpen ? 'true' : undefined}>
                  <span className="k-row-icon vendors-tile" aria-hidden="true">{stat.vendor.trim().charAt(0).toUpperCase() || '?'}</span>
                  <div className="k-row-main">
                    <span className="k-row-title">{stat.vendor}</span>
                    <span className="k-row-note">{vendorSentence(stat)}</span>
                  </div>
                  <span className="k-row-value">{stat.quotes} {plural(stat.quotes, 'quote', 'quotes')}</span>
                  <span className="k-row-control">
                    <button
                      type="button"
                      className="k-btn"
                      data-kind="quiet"
                      data-size="sm"
                      aria-expanded={isOpen}
                      aria-controls={panel}
                      onClick={() => toggle(key)}
                    >
                      {isOpen ? 'Hide quotes' : 'Show quotes'}
                    </button>
                  </span>
                </div>
                {isOpen && (
                  <div className="vendors-detail" id={panel} role="region" aria-label={`Quotes from ${stat.vendor}`}>
                    <div className="vendors-detail-head">
                      <span className="k-caption">Quotes from {stat.vendor}</span>
                      <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => void copy(stat)}>
                        {copied === stat.vendor ? 'Copied' : 'Copy summary'}
                      </button>
                    </div>
                    <div className="vendors-table-scroll">
                      <table className="k-table vendors-quote-table">
                        <thead>
                          <tr>
                            <th scope="col">Product</th>
                            <th scope="col" data-num>Price as typed</th>
                            <th scope="col" data-num>Landed</th>
                            <th scope="col" data-num>Delivery</th>
                            <th scope="col" data-num>Warranty</th>
                            <th scope="col">Valid until</th>
                            <th scope="col">Risk</th>
                            <th scope="col"><span className="vendors-visually-hidden">Open</span></th>
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((row, index) => (
                            <tr key={`${row.estimateId}:${row.lineKey}:${index}`}>
                              <td>
                                <span className="vendors-product">{row.label}</span>
                                <span className="vendors-estimate">
                                  {row.estimateName || 'Untitled estimate'}
                                  {row.won && ' · Best landed cost'}
                                </span>
                              </td>
                              <td data-num>
                                {priceOf(row.quote)}
                                {row.quote.unit_price != null && (
                                  <span className="vendors-estimate">{row.quote.vat_included ? 'with VAT' : 'without VAT'}</span>
                                )}
                              </td>
                              <td data-num>{landedWord(row)}</td>
                              <td data-num>{row.quote.delivery_days != null ? `${row.quote.delivery_days} ${plural(row.quote.delivery_days, 'day', 'days')}` : EMPTY}</td>
                              <td data-num>{row.quote.warranty_months != null ? `${row.quote.warranty_months} ${plural(row.quote.warranty_months, 'month', 'months')}` : EMPTY}</td>
                              <td>
                                {row.quote.valid_until ? row.quote.valid_until : 'No date'}
                                {row.quote.valid_until && (
                                  <span className="vendors-estimate" data-state={row.expiresInDays != null && row.expiresInDays < 0 ? 'expired' : undefined}>
                                    {expiryWord(row.expiresInDays)}
                                  </span>
                                )}
                              </td>
                              <td><RiskMark level={(row.quote.risk?.level ?? 'unknown') as RiskLevel} /></td>
                              <td>
                                <button
                                  type="button"
                                  className="k-btn"
                                  data-kind="quiet"
                                  data-size="sm"
                                  onClick={() => openEstimate(row.estimateId)}
                                >
                                  Open the estimate
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

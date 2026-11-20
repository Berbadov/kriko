import { useProcurement, type ProcurementLine } from '../../engine/procurement'
import { RiskMark, type RiskLevel } from '../../ui/RiskMark'
import { EMPTY, money } from './format'

/** The headline figures across every saved estimate, and the lines that need
 *  the reader's eye. Every figure comes from `summarize`; gross is kept per
 *  currency and never added across currencies. */

const daysWord = (days: number | null) => {
  if (days == null) return EMPTY
  if (days < 0) return `Expired ${-days} ${-days === 1 ? 'day' : 'days'} ago`
  if (days === 0) return 'Expires today'
  return `${days} ${days === 1 ? 'day' : 'days'} left`
}

const reasonsOf = (item: ProcurementLine) => item.reasons.filter(Boolean)

export function ProcurementOverview({ onOpen }: { onOpen: (estimateId: string) => void }) {
  const { loading, problem, summary } = useProcurement()

  // A line can be expiring and at risk at once: it is listed once.
  const seen = new Set<string>()
  const attention: ProcurementLine[] = []
  for (const item of [...summary.expired, ...summary.expiring, ...summary.atRisk]) {
    const key = `${item.estimateId}:${item.lineId ?? item.subjectId}`
    if (seen.has(key)) continue
    seen.add(key)
    attention.push(item)
  }

  const currencies = Object.keys(summary.gross).sort()
  const redLines = summary.atRisk.some((item) => item.risk === 'red')

  return (
    <section className="procurement-overview" aria-label="Procurement overview">
      <div className="k-kpis">
        <div className="k-kpi">
          <span className="k-kpi-value">{summary.estimates}</span>
          <span className="k-kpi-label">Estimates</span>
        </div>
        <div className="k-kpi">
          <span className="k-kpi-value">{summary.lines}</span>
          <span className="k-kpi-label">Lines</span>
          <span className="k-kpi-fact">{summary.quotedLines} with a quote</span>
        </div>
        {currencies.length === 0 ? (
          <div className="k-kpi">
            <span className="k-kpi-value">{EMPTY}</span>
            <span className="k-kpi-label">Gross committed</span>
            <span className="k-kpi-fact">{loading ? 'Reading estimates…' : 'No priced lines yet'}</span>
          </div>
        ) : currencies.map((code) => (
          <div className="k-kpi" key={code}>
            <span className="k-kpi-value procurement-money">{money(summary.gross[code], code)}</span>
            <span className="k-kpi-label">Gross committed, {code}</span>
            <span className="k-kpi-fact">Selected quotes, times quantity</span>
          </div>
        ))}
        <div className="k-kpi" data-tone={summary.expiring.length > 0 ? 'warn' : undefined}>
          <span className="k-kpi-value">{summary.expiring.length}</span>
          <span className="k-kpi-label">Quotes expiring in 14 days</span>
        </div>
        <div className="k-kpi" data-tone={redLines ? 'risk' : undefined}>
          <span className="k-kpi-value">{summary.atRisk.length}</span>
          <span className="k-kpi-label">Lines at risk</span>
          <span className="k-kpi-fact">{redLines ? 'Some are high risk' : 'Medium risk or none'}</span>
        </div>
        <div className="k-kpi" data-tone={summary.unpricedLines > 0 ? 'warn' : undefined}>
          <span className="k-kpi-value">{summary.unpricedLines}</span>
          <span className="k-kpi-label">Lines without a price</span>
          <span className="k-kpi-fact">Not counted in gross</span>
        </div>
        {summary.uncomparable > 0 && (
          <div className="k-kpi" data-tone="warn">
            <span className="k-kpi-value">{summary.uncomparable}</span>
            <span className="k-kpi-label">Lines without a rate</span>
            <span className="k-kpi-fact">Quoted in a currency with no rate</span>
          </div>
        )}
      </div>
      {problem && <p className="k-notice" role="status">{problem}</p>}

      {attention.length > 0 && (
        <div className="k-group procurement-attention">
          <span className="k-caption">Needs attention</span>
          <div className="k-card k-list">
            {attention.slice(0, 12).map((item) => {
              const reasons = reasonsOf(item)
              return (
                <div className="k-row procurement-attention-row" key={`${item.estimateId}:${item.lineId ?? item.subjectId}`}>
                  <div className="k-row-main">
                    <span className="k-row-title">{item.label}</span>
                    <span className="k-row-note">
                      {item.estimateName}
                      {reasons.length > 0 && ` · ${reasons.join(' · ')}`}
                    </span>
                  </div>
                  <span className="k-row-value">{daysWord(item.expiresInDays)}</span>
                  <span className="k-row-control procurement-attention-control">
                    <RiskMark level={item.risk as RiskLevel} />
                    <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => onOpen(item.estimateId)}>
                      Open
                    </button>
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}

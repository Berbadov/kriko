import { useEffect, useState } from 'react'
import { CAP_ORDER, CAP_WORDS, usedToday, useCaps, type CapResource } from '../../engine/caps'
import { useSpent } from '../../engine/settings'
import { useUsage } from '../../engine/usage'
import { Section, Setting, State } from '../panels/settingsParts'
import type { IconName } from '../Icon'

/** What the reader can cap a day, and what research has spent. A cap only warns. */

const CAP_ICONS: Record<CapResource, IconName> = {
  cli_agent: 'cpu',
  llm_api: 'coins',
  web_search: 'search',
  local_model: 'server',
}

export function Usage() {
  const { caps, setCap } = useCaps()
  const { meters, demo: demoMeters } = useUsage()
  const spent = useSpent()
  return (
    <>
      <Section title="Daily caps" aside={demoMeters ? <State tone="warn" icon="alert">Example numbers</State> : undefined}>
        {CAP_ORDER.map((id) => (
          <CapField key={id} id={id} cap={caps[id]} today={usedToday(meters, id)} onChange={(value) => setCap(id, value)} />
        ))}
      </Section>

      {spent && (
        <section className="k-group settings-section">
          <div className="settings-section-head">
            <h3 className="k-caption">Spent</h3>
            <State>{spent.days} days</State>
          </div>
          <div className="k-kpis">
            <div className="k-kpi">
              <span className="k-kpi-value">{spent.runs}</span>
              <span className="k-kpi-label">Runs</span>
              <span className="k-kpi-fact">in {spent.days} days</span>
            </div>
            <div className="k-kpi">
              <span className="k-kpi-value">{spent.tokens >= 1000 ? `${Math.round(spent.tokens / 1000)}k` : spent.tokens}</span>
              <span className="k-kpi-label">Tokens</span>
            </div>
            <div className="k-kpi" data-tone={spent.unpriced_runs ? 'warn' : undefined}>
              <span className="k-kpi-value">${spent.usd.toFixed(2)}</span>
              <span className="k-kpi-label">Spend</span>
              {!!spent.unpriced_runs && (
                <span className="k-kpi-fact">
                  Partial: {spent.unpriced_runs} {spent.unpriced_runs === 1 ? 'run has' : 'runs have'} no price
                </span>
              )}
            </div>
          </div>
        </section>
      )}
    </>
  )
}

/** One resource's daily cap: a number field, what is used today, and the one
 *  sentence that says a cap only warns. An empty field is no cap. */
function CapField({ id, cap, today, onChange }: { id: CapResource; cap: number | null; today: number | null; onChange: (value: number | null) => void }) {
  const word = CAP_WORDS[id]
  const [draft, setDraft] = useState(cap === null ? '' : String(cap))
  useEffect(() => setDraft(cap === null ? '' : String(cap)), [cap])
  const commit = () => {
    const text = draft.trim()
    if (!text) {
      if (cap !== null) onChange(null)
      return
    }
    const value = Number(text.replace(',', '.'))
    if (!Number.isFinite(value) || value < 0) {
      setDraft(cap === null ? '' : String(cap))
      return
    }
    if (value === 0) {
      if (cap !== null) onChange(null)
      setDraft('')
      return
    }
    if (value !== cap) onChange(value)
  }
  const used = today === null ? '' : `${word.money ? `$${today.toFixed(today < 0.01 ? 4 : 2)}` : today.toLocaleString('en-GB')} today`
  return (
    <Setting
      icon={CAP_ICONS[id]}
      label={word.title}
      state={used ? <State>{used}</State> : undefined}
      note="A cap only warns. Nothing is blocked."
      control={
        <label className="cap-field">
          <input
            type="number"
            min="0"
            step={word.money ? '0.01' : '1'}
            inputMode={word.money ? 'decimal' : 'numeric'}
            placeholder="No cap"
            aria-label={`${word.title} a day`}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={commit}
            onKeyDown={(event) => {
              if (event.key === 'Enter') event.currentTarget.blur()
            }}
          />
          <span className="cap-unit">{word.money ? '$' : word.unit}/day</span>
        </label>
      }
    />
  )
}

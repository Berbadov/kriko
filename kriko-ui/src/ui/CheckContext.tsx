import { useState } from 'react'
import type { Check, Risk } from '../compare/checks'
import { ExternalLink } from './ExternalLink'

export function CheckContext({ check }: { check: Check }) {
  const [openedAt] = useState(() => Date.now())
  const checked = check.checkedAt ? new Date(check.checkedAt) : null
  const old = checked && openedAt - checked.getTime() > 7 * 86400000
  return <div className="check-context">
    {checked && <p className="muted">Saved {checked.toLocaleString()}{old ? ' · Evidence may have changed; research again for current prices and availability.' : ''}</p>}
    {check.assumed && <p>Variant assumption: {check.assumed}</p>}
    {check.diagnostic && <p role="status">{check.diagnostic}</p>}
    {check.coverage && Object.keys(check.coverage).length > 0 && <details><summary>Research coverage</summary><dl>{Object.entries(check.coverage).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl></details>}
    {check.context && Object.keys(check.context).length > 0 && <p>Recorded use: {Object.entries(check.context).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${String(value)} ${check.contextUnits?.[key] || ''}`).join(' · ')}</p>}
    {check.risks.length === 0 && <p>No sourced problems are recorded. Coverage and variant assumptions determine how much this tells us.</p>}
  </div>
}

export function RiskEvidence({ risk }: { risk: Risk }) {
  return <>
    {risk.applicability && <p>Applies: {risk.applicability}</p>}
    {risk.disputed && <p>Sources disagree about this finding.</p>}
    {risk.advice && <p>{risk.advice}</p>}
    {risk.sources.length > 0 && <details><summary>Evidence · {risk.sources.length} sources</summary><ul className="sources">{risk.sources.map((s, i) => <li key={i}>
      <ExternalLink href={s.url || undefined}>{s.host || s.url}</ExternalLink>
      {s.stance && s.stance !== 'supports' && <span> · {s.stance}</span>}
      {s.quote && <blockquote>{s.quote}</blockquote>}
    </li>)}</ul></details>}
  </>
}

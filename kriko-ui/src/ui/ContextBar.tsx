import { formatTokens, formatUsd, toneOf, type ThreadUsage } from '../chat/view'

/** How much of the model's window this chat now uses, and what it has spent.
 *  Every number was reported by the plane that ran the turn. Where a plane
 *  reported none, this says "not reported"; it never works one out from the
 *  length of the text. */
export function ContextBar({ usage }: { usage: ThreadUsage }) {
  const latest = usage.latest
  if (!latest) return null
  const tone = toneOf(latest.fill)
  const percent = latest.fill === null ? null : Math.min(100, Math.round(latest.fill * 100))
  const spent = [
    usage.tokensIn + usage.tokensOut > 0 ? `${formatTokens(usage.tokensIn)} in · ${formatTokens(usage.tokensOut)} out` : '',
    usage.usd > 0 ? formatUsd(usage.usd) : '',
  ].filter(Boolean)

  let line: string
  if (latest.state === 'measured' && latest.used !== null && latest.window !== null) {
    line = `${formatTokens(latest.used)} of ${formatTokens(latest.window)} tokens`
  } else if (latest.state === 'measured' && latest.used !== null) {
    line = `${formatTokens(latest.used)} tokens in the largest prompt · window unknown for ${latest.model || 'this model'}`
  } else if (latest.state === 'not_reported') {
    line = 'not reported by this agent'
  } else {
    line = 'waiting for the first reply'
  }

  return (
    <div className="ctx" data-tone={tone} data-state={latest.state}>
      <span className="ctx-label">Context</span>
      <span
        className="ctx-track"
        role="meter"
        aria-label="Context window used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent ?? undefined}
        aria-valuetext={percent === null ? line : `${percent}% of the window, ${line}`}
      >
        {percent !== null && <i style={{ width: `${Math.max(percent, 2)}%` }} />}
      </span>
      <span className="ctx-text mono">
        {percent !== null ? `${percent}% · ` : ''}
        {line}
      </span>
      {spent.length > 0 && (
        <span className="ctx-spent mono muted" title="What this chat has spent, from the turns that reported it">
          {spent.join(' · ')}
          {usage.partial || usage.usdPartial ? ' · some turns did not report' : ''}
        </span>
      )}
      {usage.trimmed && (
        <span className="ctx-trim" role="note">
          Long chat: older replies and some earlier requests are no longer sent to the agent.
        </span>
      )}
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import { advise, decide, type AdviceMode, type Pick } from '../engine/buyer'
import { EngineError } from '../engine/api'
import { useEngine } from '../engine/Engine'
import { Markdown } from './Markdown'
import { PixelGlyph } from './PixelGlyph'

const CONFIDENCE: Record<string, string> = { clear: 'A clear pick', close: 'A close call', toss_up: 'Nearly a toss-up', thin: 'Little to go on' }
const MODES: { mode: AdviceMode; label: string; hint: string }[] = [
  { mode: 'pick', label: 'Say it well', hint: 'Your agent writes the recommendation and checks the web.' },
  { mode: 'debate', label: 'Debate it', hint: 'A sceptic, a bargain hunter and a durability fanatic argue, then it decides.' },
  { mode: 'tco', label: 'Cost to own', hint: 'What each costs over three years, beyond the price.' },
  { mode: 'timing', label: 'Is now the time?', hint: 'The price history against a successor or a sale.' },
]

const money = (amount: number | null, currency: string) => (amount == null ? '' : `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}${currency ? ` ${currency}` : ''}`)

/** The shortlist ranked for you, with one product named and what it costs to
 *  pick it. The ranking is computed on this computer from what Kriko holds, so
 *  it is the same whichever agent is connected; the agent only says it well. */
export function Decide({ lookupIds }: { lookupIds: string[] }) {
  const { mode: engine } = useEngine()
  const [result, setResult] = useState<Pick | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const [advice, setAdvice] = useState<{ mode: AdviceMode; text: string; waiting: string } | null>(null)
  const alive = useRef(true)
  const key = lookupIds.join(',')

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  // A different shortlist is a different decision.
  useEffect(() => {
    setResult(null)
    setAdvice(null)
    setProblem('')
  }, [key])

  if (engine !== 'live' || lookupIds.length < 2) return null

  const rank = async () => {
    setBusy(true)
    setProblem('')
    setAdvice(null)
    try {
      const got = await decide(lookupIds)
      if (alive.current) setResult(got)
    } catch (error) {
      if (alive.current) setProblem(error instanceof EngineError ? error.message : 'Could not rank them.')
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  const ask = async (mode: AdviceMode) => {
    setAdvice({ mode, text: '', waiting: 'Starting your agent' })
    try {
      const text = await advise(mode, lookupIds, (waiting) => alive.current && setAdvice({ mode, text: '', waiting }), () => alive.current)
      if (alive.current) setAdvice({ mode, text, waiting: '' })
    } catch (error) {
      if (alive.current) {
        setAdvice(null)
        setProblem(error instanceof EngineError ? error.message : 'The agent did not finish.')
      }
    }
  }

  const picked = result?.picked
  return (
    <section className="decide rise" aria-label="Decide">
      <header>
        <h2>Decide for me</h2>
        {!result && (
          <button className="btn" onClick={() => void rank()} disabled={busy}>
            {busy ? 'Ranking…' : 'Rank these for me'}
          </button>
        )}
        {result && (
          <button className="btn ghost" onClick={() => void rank()} disabled={busy}>
            Rank again
          </button>
        )}
      </header>
      {!result && !problem && <p className="panel-note">Kriko weighs risks, price history, the seller and what you told it you need, then names one.</p>}
      {problem && <p className="error-note">{problem}</p>}
      {picked && result && (
        <div className="decide-body">
          <p className="decide-winner">
            <strong>{picked.name}</strong>
            <span className="decide-chip" data-tone={result.confidence === 'clear' ? 'good' : result.confidence === 'close' ? 'neutral' : 'warn'}>
              {CONFIDENCE[result.confidence] ?? ''}
            </span>
            {picked.price != null && <span className="muted">{money(picked.price, picked.currency)}</span>}
          </p>
          {!result.profile_used && <p className="panel-note">Kriko does not know what you need yet. Tell it under More, For you, and this gets sharper.</p>}
          {picked.strengths.length > 0 && (
            <ul className="decide-list" data-kind="for">
              {picked.strengths.map((one) => (
                <li key={one}>{one}</li>
              ))}
            </ul>
          )}
          {[
            ['It costs you', result.gave_up],
            ['Switch if', result.switch_if],
            ['Check first', result.check_first],
          ].map(([title, rows]) =>
            (rows as string[]).length ? (
              <div key={title as string}>
                <h3>{title as string}</h3>
                <ul className="decide-list">
                  {(rows as string[]).map((one) => (
                    <li key={one}>{one}</li>
                  ))}
                </ul>
              </div>
            ) : null,
          )}
          <details>
            <summary>The ranking</summary>
            <ol className="decide-rank">
              {result.ranked.map((one) => (
                <li key={one.lookup_id || one.name}>
                  <strong>{one.name}</strong> <span className="mono muted">{one.score}</span>
                  {one.breaks.length > 0 && <small> Breaks what you need: {one.breaks.join(', ')}</small>}
                </li>
              ))}
            </ol>
          </details>
          <div className="decide-actions">
            {MODES.map((one) => (
              <button key={one.mode} className="btn" title={one.hint} onClick={() => void ask(one.mode)} disabled={Boolean(advice && !advice.text)}>
                {one.label}
              </button>
            ))}
          </div>
          {advice && !advice.text && (
            <p className="work-line" role="status">
              <PixelGlyph size={13} active />
              {advice.waiting || 'Your agent is working'}
            </p>
          )}
          {advice?.text && (
            <div className="decide-answer">
              <Markdown text={advice.text} />
            </div>
          )}
        </div>
      )}
      {result && !picked && <p className="panel-note">Add at least two products that Kriko has read, and it will name one.</p>}
    </section>
  )
}

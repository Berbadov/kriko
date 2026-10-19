import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useCompare, MAX_SLOTS, type Question } from '../compare'
import { riskRows, specRows, riskKey, type Check, type Level, type Risk } from '../compare/checks'
import { useEngine } from '../engine/Engine'
import { useHistory } from '../engine/history'
import { usePrefs } from '../prefs'
import { useQueue } from '../queue'
import { Composer } from '../ui/Composer'
import { Decide } from '../ui/Decide'
import { PixelBar, Switch } from '../ui/controls'
import { ExternalLink } from '../ui/ExternalLink'
import { Icon } from '../ui/Icon'
import { Markdown } from '../ui/Markdown'
import { PixelGlyph } from '../ui/PixelGlyph'
import { CheckContext } from '../ui/CheckContext'

const LEVEL_WORD: Record<Level, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', unrated: 'Unrated' }
const LEVEL_ORDER: Record<Level, number> = { critical: 0, high: 1, medium: 2, low: 3, unrated: 4 }

/** Products are columns. Each column leads with what the agents found that can
 *  go wrong with it, in words, because that is what the reader came for; the
 *  specifications are a table under the columns, folded until they are wanted.
 *  A product still in research is a working column: one line and a bar. */
export function CompareScreen() {
  const { motion: m } = usePrefs()
  const { items } = useQueue()
  const { slots, checks, questions, remove, retry, ask, stop, problem, saveAgain } = useCompare()
  const [only, setOnly] = useState(false)
  const [picker, setPicker] = useState(false)
  const [specsOpen, setSpecsOpen] = useState(false)

  const working = items.filter((i) => i.state !== 'done')
  const ready = slots.flatMap((id) => {
    const found = checks[id]
    return found?.status === 'ready' ? [found.check] : []
  })
  const risks = useMemo(() => riskRows(ready), [ready])
  const specs = useMemo(() => specRows(ready), [ready])
  // How many of the columns carry each risk: "also in 2 of 3" is the one thing
  // lining the columns up still has to say.
  const shared = useMemo(() => new Map(risks.map((r) => [r.key, r.cells.filter(Boolean).length])), [risks])
  const differing = useMemo(() => new Set(risks.filter((r) => r.differs).map((r) => r.key)), [risks])
  const shownSpecs = only ? specs.filter((r) => r.differs) : specs
  const empty = slots.length === 0 && working.length === 0
  // With no problems to read, the specifications are all there is: show them.
  const specsShown = specsOpen || (ready.length > 0 && risks.length === 0)

  return (
    <section className="compare">
      <header className="page-head rise" style={{ '--i': 0 } as CSSProperties}>
        <h1>Compare</h1>
        <span className="mono muted">
          {slots.length} products · {working.length} in research
        </span>
        <div className="head-tools">
          <label className="inline-switch">
            <span>Differences only</span>
            <Switch on={only} onChange={setOnly} label="Differences only" />
          </label>
          <button className="btn" onClick={() => setPicker((v) => !v)} disabled={slots.length >= MAX_SLOTS} aria-expanded={picker}>
            <Icon name="plus" size={14} /> Add
          </button>
        </div>
      </header>

      <AnimatePresence>{picker && <Picker onClose={() => setPicker(false)} />}</AnimatePresence>

      <Decide lookupIds={ready.map((one) => one.lookupId)} />

      <div className="compare-body">
        {problem && <p className="error-note" role="alert">{problem} <button className="btn" onClick={saveAgain}>{problem.startsWith('Could not load') ? 'Retry loading' : 'Retry saving'}</button></p>}
        {empty ? (
          <div className="empty rise" style={{ '--i': 1 } as CSSProperties}>
            <PixelGlyph size={34} active />
            <p>Add two checks to compare them.</p>
            <button className="btn" onClick={() => setPicker(true)}>
              <Icon name="plus" size={14} /> Add a check
            </button>
          </div>
        ) : (
          <>
            <div className="matrix rise" style={{ '--i': 1 } as CSSProperties}>
              <AnimatePresence initial={false}>
                {slots.map((id) => {
                  const found = checks[id]
                  if (found?.status === 'ready') {
                    const list = found.check.risks
                      .filter((r) => !only || differing.has(riskKey(r)))
                      .sort((a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level])
                    return (
                      <Column key={id} check={found.check} onRemove={() => remove(id)} transition={m.tx.spring}>
                        {list.length === 0 ? (
                          <p className="mx-none">
                            {found.check.risks.length === 0
                              ? 'The agents found no sourced problems. That is not proof there are none.'
                              : 'Nothing here differs from the others.'}
                          </p>
                        ) : (
                          <ul className="mx-risks">
                            {list.map((risk) => (
                              <RiskCard key={riskKey(risk)} risk={risk} also={(shared.get(riskKey(risk)) ?? 1) - 1} of={ready.length} />
                            ))}
                          </ul>
                        )}
                      </Column>
                    )
                  }
                  return (
                    <motion.div key={id} layout className="mx-col is-working" initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} transition={m.tx.spring}>
                      <div className="mx-head">
                        {found?.status === 'error' ? (
                          <>
                            <strong>Not read</strong>
                            <span className="muted">{found.message}</span>
                            <div className="card-actions">
                              <button className="btn" onClick={() => retry(id)}>
                                Try again
                              </button>
                              <button className="btn ghost" onClick={() => remove(id)}>
                                Remove
                              </button>
                            </div>
                          </>
                        ) : (
                          <span className="work-line">
                            <PixelGlyph size={13} active />
                            Reads the check
                          </span>
                        )}
                      </div>
                    </motion.div>
                  )
                })}
                {working.slice(0, 3).map((item) => (
                  <motion.div key={item.id} layout className="mx-col is-working" initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} transition={m.tx.spring}>
                    <div className="mx-head">
                      <strong>{item.name}</strong>
                      <span className="work-line">
                        <PixelGlyph size={13} active={item.state === 'researching'} />
                        {item.line}
                      </span>
                      <PixelBar value={item.progress} active={item.state === 'researching'} cells={18} />
                    </div>
                    <div className="mx-risks">
                      {[0, 1, 2].map((n) => (
                        <div key={n} className="mx-skeleton">
                          <span className="skeleton" />
                        </div>
                      ))}
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>

            {ready.length > 0 && specs.length > 0 && (
              <section className="specs rise" style={{ '--i': 2 } as CSSProperties}>
                <button className="specs-toggle" onClick={() => setSpecsOpen((v) => !v)} aria-expanded={specsShown} disabled={risks.length === 0 && ready.length > 0}>
                  <span>Specs</span>
                  <span className="mono muted">{shownSpecs.length}</span>
                  <Icon name="expand" size={12} />
                </button>
                {specsShown && (
                  <div className="spec-table" style={{ '--cols': ready.length } as CSSProperties}>
                    <div className="spec-row spec-head">
                      <span />
                      {ready.map((c) => (
                        <strong key={c.lookupId} title={c.name}>
                          {c.name}
                        </strong>
                      ))}
                    </div>
                    {shownSpecs.map((row) => (
                      <div key={row.label} className="spec-row" data-differs={row.differs}>
                        <span className="spec-label">{row.label}</span>
                        {row.cells.map((cell, i) => (
                          <span key={ready[i].lookupId} className="spec-value">
                            {cell?.value ?? 'Unknown'}
                            {cell?.source && <ExternalLink href={cell.source}> Source</ExternalLink>}
                            {cell?.quote && <details><summary>Quote</summary><q>{cell.quote}</q></details>}
                          </span>
                        ))}
                      </div>
                    ))}
                    {shownSpecs.length === 0 && <p className="mx-none">The specifications do not differ.</p>}
                  </div>
                )}
              </section>
            )}
          </>
        )}

        <Talk questions={questions} />
      </div>

      <div className="compare-dock rise" style={{ '--i': 3 } as CSSProperties}>
        <Composer onSubmit={(text, agent) => ask(text, agent)} running={questions.some((q) => q.state === 'running')} onStop={stop} placeholder={slots.length ? 'Ask about these products' : 'Add a check to ask about it'} />
      </div>
    </section>
  )
}

function Column({ check, onRemove, children, transition }: { check: Check; onRemove: () => void; children: React.ReactNode; transition: object }) {
  return (
    <motion.div layout className="mx-col" initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.97 }} transition={transition}>
      <div className="mx-head">
        <div className="mx-title">
          <strong title={check.name}>{check.name}</strong>
          <button className="icon-btn sm" onClick={onRemove} aria-label={`Remove ${check.name}`}>
            <Icon name="x" size={14} />
          </button>
        </div>
        <span className="muted">{check.category || 'Quick look'}</span>
        <span className="mono muted">{check.risks.length === 1 ? '1 risk' : `${check.risks.length} risks`}</span>
      </div>
      <CheckContext check={check} />
      {children}
    </motion.div>
  )
}

/** One problem the agents found, in words. It opens to the sources and their quotes. */
function RiskCard({ risk, also, of }: { risk: Risk; also: number; of: number }) {
  const [open, setOpen] = useState(false)
  const pages = risk.sources.length
  return (
    <li className="mx-risk" data-open={open}>
      <button className="mx-risk-main" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="mx-risk-top">
          <span className="level" data-level={risk.level}>
            {LEVEL_WORD[risk.level]}
          </span>
          {risk.disputed && <span className="mx-flag">Its sources disagree</span>}
          {also > 0 && (
            <span className="mx-flag">
              Also in {also} of {of - 1} other{of - 1 === 1 ? '' : 's'}
            </span>
          )}
        </span>
        <strong className="mx-risk-title">{risk.title}</strong>
        {risk.body && <span className="mx-risk-body">{risk.body}</span>}
        {risk.applicability && <span>Applies: {risk.applicability}</span>}
        {risk.advice && <span>{risk.advice}</span>}
        <span className="mono muted mx-risk-meta">{pages === 1 ? '1 source' : `${pages} sources`}</span>
      </button>
      {open && pages > 0 && (
        <ul className="sources">
          {risk.sources.map((s, i) => (
            <li key={i} data-stance={s.stance.toLowerCase() === 'refutes' ? 'against' : 'for'}>
              {s.url ? (
                <ExternalLink href={s.url}>{s.host || s.url}</ExternalLink>
              ) : (
                <span>{s.host}</span>
              )}
              {s.quote && <q>{s.quote}</q>}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

/** The questions and the answers, above the dock. */
function Talk({ questions }: { questions: Question[] }) {
  const { motion: m } = usePrefs()
  const end = useRef<HTMLDivElement>(null)
  const size = questions.reduce((n, q) => n + q.answer.length, questions.length)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: m.on ? 'smooth' : 'auto' })
  }, [size, m.on])
  if (!questions.length) return null
  return (
    <div className="talk">
      {questions.map((q) => (
        <div key={q.id} className="talk-q">
          <p className="you">{q.text}</p>
          {q.state === 'running' && !q.answer && (
            <span className="work-line">
              <PixelGlyph size={13} active />
              {q.agent ? `${q.agent} researches` : 'Researches'}
            </span>
          )}
          {q.answer && (
            <article className="answer">
              <Markdown text={q.answer} live={q.state === 'running'} />
            </article>
          )}
          {q.state === 'failed' && (
            <p className="error-note" role="alert">
              {q.note}
            </p>
          )}
        </div>
      ))}
      <div ref={end} />
    </div>
  )
}

/** Saved checks to put on the board. */
function Picker({ onClose }: { onClose: () => void }) {
  const { mode } = useEngine()
  const { motion: m } = usePrefs()
  const { slots, add } = useCompare()
  const [rows, setRows] = useState<{ id: string; name: string; note: string }[] | null>(null)
  const [query, setQuery] = useState('')
  const history = useHistory(query)

  useEffect(() => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setRows([
        { id: 'demo:Gamma Unit 400', name: 'Gamma Unit 400', note: 'Demo' },
        { id: 'demo:Kingston A400 480 GB', name: 'Kingston A400 480 GB', note: 'Demo' },
      ])
      return
    }
  }, [mode])

  const choices = (mode === 'live' ? (history.items ?? []).map((r) => ({ id: r.id, name: r.name, note: r.category })) : rows ?? []).filter((r) => !slots.includes(r.id))
  return (
    <motion.div className="picker" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={m.tx.soft}>
      <div className="picker-inner">
        <input type="search" aria-label="Search all saved checks" placeholder="Search all checks" value={query} onChange={(event) => setQuery(event.target.value)} />
        {history.problem && <p className="error-note" role="alert">{history.problem}</p>}
        {(mode === 'live' ? history.items === null : rows === null) && <span className="muted">Reads your checks…</span>}
        {(mode === 'live' ? history.items !== null : rows !== null) && choices.length === 0 && <span className="muted">No matching checks to add.</span>}
        {choices.map((r) => (
          <button key={r.id} className="chip" onClick={() => add(r.id)} disabled={slots.length >= MAX_SLOTS} title={r.name}>
            <strong>{r.name}</strong>
            <span className="muted">{r.note}</span>
          </button>
        ))}
        {history.hasMore && <button className="btn" onClick={history.loadMore}>Load more</button>}
        <button className="icon-btn sm" onClick={onClose} aria-label="Close the list" style={{ marginLeft: 'auto' }}>
          <Icon name="x" size={14} />
        </button>
      </div>
    </motion.div>
  )
}

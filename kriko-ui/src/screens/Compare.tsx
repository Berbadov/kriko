import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useCompare, MAX_SLOTS, type Question } from '../compare'
import { riskRows, specRows, type Check, type Level, type Risk } from '../compare/checks'
import { useEngine } from '../engine/Engine'
import { get, type ApiHistoryItem } from '../engine/api'
import { usePrefs } from '../prefs'
import { useQueue } from '../queue'
import { Composer } from '../ui/Composer'
import { PixelBar, Switch } from '../ui/controls'
import { ExternalLink } from '../ui/ExternalLink'
import { Icon } from '../ui/Icon'
import { Markdown } from '../ui/Markdown'
import { PixelGlyph } from '../ui/PixelGlyph'

const LEVEL_WORD: Record<Level, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', unrated: 'Unrated' }

/** Products are columns and risks are rows. A product still in research is a
 *  working column: one line and a bar. It becomes a column when the agent finishes. */
export function CompareScreen() {
  const { motion: m } = usePrefs()
  const { items } = useQueue()
  const { slots, checks, questions, remove, retry, ask } = useCompare()
  const [only, setOnly] = useState(false)
  const [open, setOpen] = useState<{ lookupId: string; title: string } | null>(null)
  const [picker, setPicker] = useState(false)

  const working = items.filter((i) => i.state !== 'done')
  const ready = slots.flatMap((id) => {
    const found = checks[id]
    return found?.status === 'ready' ? [found.check] : []
  })
  const risks = useMemo(() => riskRows(ready), [ready])
  const specs = useMemo(() => specRows(ready), [ready])
  const shownRisks = only ? risks.filter((r) => r.differs) : risks
  const shownSpecs = only ? specs.filter((r) => r.differs) : specs
  const empty = slots.length === 0 && working.length === 0

  // The cell that was opened may leave with its column.
  const detail = open ? ready.find((c) => c.lookupId === open.lookupId)?.risks.find((r) => r.title === open.title) : undefined

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

      <div className="compare-body">
      {empty ? (
        <div className="empty rise" style={{ '--i': 1 } as CSSProperties}>
          <PixelGlyph size={34} active />
          <p>Add two checks to compare them.</p>
          <button className="btn" onClick={() => setPicker(true)}>
            <Icon name="plus" size={14} /> Add a check
          </button>
        </div>
      ) : (
        <div className="matrix rise" style={{ '--i': 1 } as CSSProperties}>
          <div className="mx-col mx-labels">
            <div className="mx-head" />
            {shownRisks.map((row) => (
              <div key={row.title} className="mx-cell label" title={row.title}>
                {row.title}
              </div>
            ))}
            {shownSpecs.length > 0 && <div className="mx-cell label mx-divider">Specs</div>}
            {shownSpecs.map((row) => (
              <div key={row.label} className="mx-cell label" title={row.label}>
                {row.label}
              </div>
            ))}
          </div>

          <AnimatePresence initial={false}>
            {slots.map((id) => {
              const found = checks[id]
              if (found?.status === 'ready') {
                const index = ready.indexOf(found.check)
                return (
                  <Column key={id} check={found.check} onRemove={() => remove(id)} transition={m.tx.spring}>
                    {shownRisks.map((row) => (
                      <RiskCell key={row.title} risk={row.cells[index]} active={open?.lookupId === id && open.title === row.title} onOpen={() => setOpen({ lookupId: id, title: row.title })} />
                    ))}
                    {shownSpecs.length > 0 && <div className="mx-cell mx-divider" />}
                    {shownSpecs.map((row) => (
                      <div key={row.label} className="mx-cell" data-differs={row.differs} title={row.cells[index]?.value}>
                        <span className="spec">{row.cells[index]?.value ?? '—'}</span>
                      </div>
                    ))}
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
                {shownRisks.map((row) => (
                  <div key={row.title} className="mx-cell">
                    <span className="skeleton" />
                  </div>
                ))}
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}

      <AnimatePresence>{detail && open && <Detail key={open.lookupId + open.title} title={open.title} risk={detail} onClose={() => setOpen(null)} />}</AnimatePresence>

      <Talk questions={questions} />
      </div>

      <div className="compare-dock rise" style={{ '--i': 3 } as CSSProperties}>
        <Composer onSubmit={(text, agent) => ask(text, agent)} running={false} onStop={() => {}} placeholder={slots.length ? 'Ask about these products' : 'Add a check to ask about it'} />
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
      {children}
    </motion.div>
  )
}

function RiskCell({ risk, active, onOpen }: { risk: Risk | null; active: boolean; onOpen: () => void }) {
  if (!risk)
    return (
      <div className="mx-cell">
        <span className="muted">—</span>
      </div>
    )
  return (
    <div className="mx-cell">
      <button className="level" data-level={risk.level} data-active={active} onClick={onOpen} aria-label={`${risk.title}: ${LEVEL_WORD[risk.level]}${risk.disputed ? ', disputed' : ''}`}>
        {LEVEL_WORD[risk.level]}
        {risk.disputed && <i className="disputed" title="Its sources disagree" />}
      </button>
    </div>
  )
}

/** The words and sources behind one cell. */
function Detail({ title, risk, onClose }: { title: string; risk: Risk; onClose: () => void }) {
  const { motion: m } = usePrefs()
  return (
    <motion.aside className="detail" initial={{ opacity: 0, y: m.d(12) }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: m.d(8) }} transition={m.tx.spring}>
      <header>
        <strong>{title}</strong>
        <span className="level" data-level={risk.level}>
          {LEVEL_WORD[risk.level]}
        </span>
        {risk.disputed && <span className="muted">Its sources disagree.</span>}
        <button className="icon-btn sm" onClick={onClose} aria-label="Close" style={{ marginLeft: 'auto' }}>
          <Icon name="x" size={14} />
        </button>
      </header>
      {risk.body && <p>{risk.body}</p>}
      {risk.sources.length > 0 && (
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
    </motion.aside>
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

  useEffect(() => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setRows([
        { id: 'demo:Gamma Unit 400', name: 'Gamma Unit 400', note: 'Demo' },
        { id: 'demo:Kingston A400 480 GB', name: 'Kingston A400 480 GB', note: 'Demo' },
      ])
      return
    }
    let live = true
    get<{ items: ApiHistoryItem[] }>('/api/history?limit=30')
      .then((reply) => live && setRows(reply.items.filter((r) => r.claim_count > 0 || r.label).map((r) => ({ id: r.lookup_id, name: r.label, note: r.category || 'Quick look' }))))
      .catch(() => live && setRows([]))
    return () => {
      live = false
    }
  }, [mode])

  const choices = (rows ?? []).filter((r) => !slots.includes(r.id))
  return (
    <motion.div className="picker" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={m.tx.soft}>
      <div className="picker-inner">
        {rows === null && <span className="muted">Reads your checks…</span>}
        {rows !== null && choices.length === 0 && <span className="muted">No more checks to add.</span>}
        {choices.map((r) => (
          <button key={r.id} className="chip" onClick={() => add(r.id)} disabled={slots.length >= MAX_SLOTS} title={r.name}>
            <strong>{r.name}</strong>
            <span className="muted">{r.note}</span>
          </button>
        ))}
        <button className="icon-btn sm" onClick={onClose} aria-label="Close the list" style={{ marginLeft: 'auto' }}>
          <Icon name="x" size={14} />
        </button>
      </div>
    </motion.div>
  )
}

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { demoCheck, loadCheck, type Check, type Level } from '../compare/checks'
import { useCompare } from '../compare'
import { useDodged } from '../engine/buyer'
import { strongestConcern } from '../engine/dodged'
import { useEngine } from '../engine/Engine'
import { EngineError, get, post, seg, type ApiFeedEvent, type ApiJob } from '../engine/api'
import { followJob } from '../engine/jobs'
import { useSensitivity } from '../engine/sensitivity'
import { hiddenLine, shown } from '../engine/thinness'
import { usePrefs } from '../prefs'
import { Composer } from '../ui/Composer'
import { DodgeDialog } from '../ui/DodgeDialog'
import { EvidenceMark } from '../ui/EvidenceMark'
import { ExternalLink } from '../ui/ExternalLink'
import { Icon } from '../ui/Icon'
import { Markdown } from '../ui/Markdown'
import { PixelGlyph } from '../ui/PixelGlyph'
import { CheckContext, RiskEvidence } from '../ui/CheckContext'
import { ProductInsights } from '../ui/ProductInsights'
import { UsedCard } from '../ui/UsedCard'
import { WorkTerminal } from '../ui/WorkTerminal'
import { DustField } from '../dust/DustField'
import { kindFor, product, reading } from '../dust/engine'

const LEVEL_WORD: Record<Level, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', unrated: 'Unrated' }
const DEMO_ANSWER = 'The maker states a limit of **40 minutes** of full load.\n\n- Short jobs are fine.\n- For long jobs, add a fan or pick another unit.'

interface Turn {
  id: string
  text: string
  answer: string
  state: 'running' | 'done' | 'failed'
  note: string
  /** The job's own words, for the work terminal. */
  stage?: string
  feed?: ApiFeedEvent[]
  jobState?: string
  jobMessage?: string
}

type Asked = ApiJob & { params?: { question?: string } }

const reasonOf = (error: unknown) => (error instanceof EngineError ? error.message : 'The engine does not answer.')
const answerOf = (job: ApiJob) => (job.result as { answer?: string } | null | undefined)?.answer ?? ''
/** How a lost research reads when the engine sends no words of its own. */
const STOPPED: Record<string, string> = {
  cancelled: 'The research was stopped.',
  interrupted: 'The research was interrupted. Ask again to continue.',
  failed: 'The research failed.',
}

/** One saved check, and the questions about it. The extension hands a product
 *  over to this page. The questions go to the engine, which answers them with a
 *  web search and names the pages it read. */
export function ProductScreen({ lookupId, onBack, onCompare }: { lookupId: string; onBack: () => void; onCompare: () => void }) {
  const { motion: m } = usePrefs()
  const { mode } = useEngine()
  const { add, slots } = useCompare()
  const [check, setCheck] = useState<Check | null>(null)
  const [problem, setProblem] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [turns, setTurns] = useState<Turn[]>([])
  const { sensitivity } = useSensitivity()
  const dodged = useDodged()
  const [dodgeOpen, setDodgeOpen] = useState(false)
  const [dodgeNote, setDodgeNote] = useState('')
  /** The reader pressed "show them", for this check at this step. A different check or step is a new question. */
  const [reveal, setReveal] = useState({ key: '', on: false })
  const revealKey = `${lookupId}|${sensitivity}`
  const revealed = reveal.on && reveal.key === revealKey
  const alive = useRef(true)
  const end = useRef<HTMLDivElement>(null)
  const stopRequested = useRef(false)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const patch = useCallback((id: string, change: Partial<Turn>) => {
    if (alive.current) setTurns((list) => list.map((t) => (t.id === id ? { ...t, ...change } : t)))
  }, [])

  const settle = useCallback(
    (id: string, job: ApiJob) => {
      if (job.state === 'succeeded') patch(id, { answer: answerOf(job) || 'No answer came back.', state: 'done' })
      else patch(id, { answer: answerOf(job), state: 'failed', note: job.message || STOPPED[job.state] || 'The research did not finish.' })
    },
    [patch],
  )

  // The check, and the questions asked before.
  useEffect(() => {
    let live = true
    setCheck(null)
    setProblem('')
    setTurns([])
    if (lookupId.startsWith('demo:')) {
      setCheck(demoCheck(lookupId, lookupId.slice(5)))
      return
    }
    loadCheck(lookupId)
      .then((c) => live && setCheck(c))
      .catch((e) => live && setProblem(reasonOf(e)))
    get<{ items: Asked[] }>(`/api/lookup/${seg(lookupId)}/questions`)
      .then((reply) => {
        if (!live) return
        setTurns(
          reply.items.map((j) => ({
            id: j.job_id,
            text: j.params?.question ?? '',
            answer: answerOf(j),
            state: j.state === 'succeeded' ? 'done' : j.done ? 'failed' : 'running',
            note: j.done && j.state !== 'succeeded' ? j.message || '' : '',
          })),
        )
        for (const j of reply.items) {
          if (j.done) continue
          followJob(j.job_id, (reading) => patch(j.job_id, { answer: answerOf(reading), jobState: reading.state, jobMessage: reading.message, feed: reading.feed }), () => live)
            .then((ended) => ended && settle(j.job_id, ended))
            .catch((e) => patch(j.job_id, { state: 'failed', note: reasonOf(e) }))
        }
      })
      .catch((error: unknown) => live && setProblem(`Could not read saved questions. ${reasonOf(error)}`))
    return () => {
      live = false
    }
  }, [lookupId, settle, patch, loadAttempt])

  const lastSize = turns.length ? turns[turns.length - 1].answer.length : 0
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: m.on ? 'smooth' : 'auto' })
  }, [turns.length, lastSize, m.on])

  const ask = async (text: string) => {
    stopRequested.current = false
    const id = `local-${Date.now()}`
    let activeId = id
    setTurns((list) => [...list, { id, text, answer: '', state: 'running', note: '', stage: 'Starting the research…' }])
    if (mode !== 'live') {
      await new Promise((resolve) => window.setTimeout(resolve, 1200))
      patch(id, { answer: DEMO_ANSWER, state: 'done' })
      return
    }
    try {
      const sent = await post<{ job_id: string }>(`/api/lookup/${seg(lookupId)}/questions`, { question: text })
      activeId = sent.job_id
      if (stopRequested.current) await post(`/api/jobs/${seg(sent.job_id)}/cancel`, {})
      setTurns((list) => list.map((t) => (t.id === id ? { ...t, id: sent.job_id } : t)))
      const ended = await followJob(sent.job_id, (reading) => patch(sent.job_id, { answer: answerOf(reading), jobState: reading.state, jobMessage: reading.message, feed: reading.feed }), () => alive.current)
      if (ended) settle(sent.job_id, ended)
    } catch (error) {
      patch(activeId, { state: 'failed', note: reasonOf(error) })
    }
  }

  const hidden = check ? check.risks.filter((risk) => !shown(risk.evidence?.level, sensitivity)) : []
  const drawn = check ? check.risks.filter((risk) => revealed || shown(risk.evidence?.level, sensitivity)) : []

  // The product rebuilt in dust: the cloud reads while the check loads, then
  // gathers into the outline of whatever kind of thing the check is about.
  const portrait = useMemo(() => (check ? product(kindFor(check.name, check.category)) : reading), [check])

  const onBoard = slots.includes(lookupId)
  const asking = turns.some((t) => t.state === 'running')
  const stop = () => {
    stopRequested.current = true
    for (const turn of turns.filter((t) => t.state === 'running')) {
      if (mode === 'live' && !turn.id.startsWith('local-')) void post(`/api/jobs/${seg(turn.id)}/cancel`, {}).then(() => patch(turn.id, { note: 'Stopping…' })).catch((error) => patch(turn.id, { note: reasonOf(error) }))
    }
  }

  return (
    <section className="product">
      <header className="page-head rise" style={{ '--i': 0 } as CSSProperties}>
        <div className="head-main">
          <button className="icon-btn" onClick={onBack} aria-label="Back to Chat">
            <Icon name="collapse" size={18} />
          </button>
          <h1 title={check?.name}>{check?.name ?? 'Check'}</h1>
        </div>
        <div className="head-tools">
          {check && <button className="btn" disabled={turns.some((turn) => turn.state === 'running')} onClick={() => void ask('Research this exact product again for current evidence, prices and availability. Keep the recorded variant and market assumptions explicit and cite the sources.')}>Ask for fresh evidence</button>}
          {check && mode === 'live' && (
            <button className="btn" onClick={() => setDodgeOpen(true)}>
              <Icon name="shieldcheck" size={14} /> Not buying this
            </button>
          )}
          {onBoard ? (
            <button className="btn" onClick={onCompare}>
              Open Compare
            </button>
          ) : (
            <button className="btn" onClick={() => add(lookupId)} disabled={!check}>
              <Icon name="plus" size={14} /> Add to Compare
            </button>
          )}
        </div>
      </header>

      <div className="product-body">
        {!problem && (
          <div className="product-dust rise" style={{ '--i': 0 } as CSSProperties}>
            <DustField scene={portrait} reading={!check} per={12} cap={9000} />
          </div>
        )}
        {problem && (
          <p className="error-note" role="alert">
            {problem}
            <button className="btn" onClick={() => setLoadAttempt((n) => n + 1)}>Read again</button>
          </p>
        )}
        {dodgeNote && (
          <p className="dodge-saved" role="status">
            <Icon name="shieldcheck" size={15} /> {dodgeNote}
            <button className="btn ghost" onClick={() => setDodgeNote('')}>Dismiss</button>
          </p>
        )}
        {!check && !problem && (
          <span className="work-line">
            <PixelGlyph size={13} active />
            Reads the check
          </span>
        )}
        {check && <CheckContext check={check} />}
        {check && <ProductInsights key={lookupId} lookupId={lookupId} live={mode === 'live' && !lookupId.startsWith('demo:')} onResearch={(question) => void ask(question)} onReload={() => setLoadAttempt((value) => value + 1)} />}
        {check && check.specs.length > 0 && <details><summary>Specifications</summary><dl>{check.specs.map((spec) => <div key={spec.label}><dt>{spec.label}</dt><dd>{spec.value} {spec.source && <ExternalLink href={spec.source}>Source</ExternalLink>}{spec.quote && <blockquote>{spec.quote}</blockquote>}</dd></div>)}</dl></details>}
        {check && (
          <ul className="risk-list rise" style={{ '--i': 1 } as CSSProperties}>
            {check.risks.length === 0 && <li className="muted">No risk is on record.</li>}
            {check.risks.length > 0 && drawn.length === 0 && <li className="muted">Every finding on record is hidden at this sensitivity.</li>}
            {drawn.map((risk) => (
              <li key={risk.title} data-thin={risk.evidence?.level === 'thin' || undefined}>
                <span className="risk-gutter">
                  <span className="level" data-level={risk.level}>
                    {LEVEL_WORD[risk.level]}
                  </span>
                  {risk.sources.length > 0 && (
                    <span className="mono risk-count">
                      {risk.sources.length} {risk.sources.length === 1 ? 'source' : 'sources'}
                    </span>
                  )}
                </span>
                <div className="risk-body">
                  <div className="risk-title">
                    <strong>{risk.title}</strong>
                    <EvidenceMark evidence={risk.evidence} />
                  </div>
                  {risk.body && <p>{risk.body}</p>}
                  <RiskEvidence risk={risk} />
                </div>
              </li>
            ))}
          </ul>
        )}
        {check && hidden.length > 0 && (
          <p className="ev-hidden" role="status">
            <span>{revealed ? 'Showing the hidden findings.' : `${hiddenLine(hidden.length, sensitivity)}.`}</span>
            <button className="btn ghost" onClick={() => setReveal({ key: revealKey, on: !revealed })} aria-pressed={revealed}>
              {revealed ? 'Hide them again' : 'Show them'}
            </button>
          </p>
        )}
        {check && <UsedCard check={{ ...check, risks: drawn }} />}

        <div className="talk wide">
          <AnimatePresence initial={false}>
            {turns.map((t) => (
              <motion.div key={t.id} className="talk-q" initial={{ opacity: 0, y: m.d(10) }} animate={{ opacity: 1, y: 0 }} transition={m.tx.spring}>
                <p className="you">{t.text}</p>
                {t.state === 'running' && (
                  <WorkTerminal title={t.text} state={t.jobState} stage={t.stage} message={t.jobMessage} feed={t.feed} />
                )}
                {t.answer && (
                  <article className="answer">
                    <Markdown text={t.answer} live={t.state === 'running'} />
                  </article>
                )}
                {t.state === 'failed' && (
                  <p className="error-note" role="alert">
                    {t.note}
                  </p>
                )}
              </motion.div>
            ))}
          </AnimatePresence>
          <div ref={end} />
        </div>
      </div>

      <div className="compare-dock">
        <Composer onSubmit={(text) => void ask(text)} running={asking} onStop={stop} placeholder="Ask about this product" agents={false} autoFocus />
      </div>
      {dodgeOpen && check && (
        <DodgeDialog
          name={check.name}
          url={check.url ?? ''}
          reason={strongestConcern(drawn)}
          add={dodged.add}
          problem={dodged.problem}
          onClose={() => setDodgeOpen(false)}
          onSaved={() => {
            setDodgeOpen(false)
            setDodgeNote(`${check.name} is in Dodged.`)
          }}
        />
      )}
    </section>
  )
}

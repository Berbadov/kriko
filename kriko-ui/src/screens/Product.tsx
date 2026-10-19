import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { demoCheck, loadCheck, type Check, type Level } from '../compare/checks'
import { useCompare } from '../compare'
import { useEngine } from '../engine/Engine'
import { EngineError, get, post, seg, type ApiJob } from '../engine/api'
import { followJob } from '../engine/jobs'
import { usePrefs } from '../prefs'
import { Composer } from '../ui/Composer'
import { ExternalLink } from '../ui/ExternalLink'
import { Icon } from '../ui/Icon'
import { Markdown } from '../ui/Markdown'
import { PixelGlyph } from '../ui/PixelGlyph'

const LEVEL_WORD: Record<Level, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', unrated: 'Unrated' }
const DEMO_ANSWER = 'The maker states a limit of **40 minutes** of full load.\n\n- Short jobs are fine.\n- For long jobs, add a fan or pick another unit.'

interface Turn {
  id: string
  text: string
  answer: string
  state: 'running' | 'done' | 'failed'
  note: string
}

type Asked = ApiJob & { params?: { question?: string } }

const reasonOf = (error: unknown) => (error instanceof EngineError ? error.message : 'The engine does not answer.')
const answerOf = (job: ApiJob) => (job.result as { answer?: string } | null | undefined)?.answer ?? ''

/** One saved check, and the questions about it. The extension hands a product
 *  over to this page. The questions go to the engine, which answers them with a
 *  web search and names the pages it read. */
export function ProductScreen({ lookupId, onBack, onCompare }: { lookupId: string; onBack: () => void; onCompare: () => void }) {
  const { motion: m } = usePrefs()
  const { mode } = useEngine()
  const { add, slots } = useCompare()
  const [check, setCheck] = useState<Check | null>(null)
  const [problem, setProblem] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const alive = useRef(true)
  const end = useRef<HTMLDivElement>(null)

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
      else patch(id, { state: 'failed', note: job.message || `The research ${job.state}.` })
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
          followJob(j.job_id, () => undefined, () => live)
            .then((ended) => ended && settle(j.job_id, ended))
            .catch((e) => patch(j.job_id, { state: 'failed', note: reasonOf(e) }))
        }
      })
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [lookupId, settle, patch])

  const lastSize = turns.length ? turns[turns.length - 1].answer.length : 0
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: m.on ? 'smooth' : 'auto' })
  }, [turns.length, lastSize, m.on])

  const ask = async (text: string) => {
    const id = `local-${Date.now()}`
    setTurns((list) => [...list, { id, text, answer: '', state: 'running', note: '' }])
    if (mode !== 'live') {
      await new Promise((resolve) => window.setTimeout(resolve, 1200))
      patch(id, { answer: DEMO_ANSWER, state: 'done' })
      return
    }
    try {
      const sent = await post<{ job_id: string }>(`/api/lookup/${seg(lookupId)}/questions`, { question: text })
      setTurns((list) => list.map((t) => (t.id === id ? { ...t, id: sent.job_id } : t)))
      const ended = await followJob(sent.job_id, () => undefined, () => alive.current)
      if (ended) settle(sent.job_id, ended)
    } catch (error) {
      patch(id, { state: 'failed', note: reasonOf(error) })
    }
  }

  const onBoard = slots.includes(lookupId)
  const asking = turns.some((t) => t.state === 'running')

  /**
   * Stop the questions that are running.
   *
   * The composer drew a stop button and was wired to `() => {}`: a reader who
   * pressed it got nothing — no cancellation and no acknowledgement — while a
   * run they are paying for kept going. Each running turn's id *is* its job id
   * (`ask` renames the turn to `sent.job_id`), so this is the same cancel the
   * queue and the local-plane panel already call.
   */
  const stopAsking = async () => {
    const running = turns.filter((t) => t.state === 'running' && !t.id.startsWith('local-'))
    if (running.length === 0) return
    for (const turn of running) {
      try {
        await post(`/api/jobs/${seg(turn.id)}/cancel`)
        patch(turn.id, { state: 'failed', note: 'Stopped.' })
      } catch (error) {
        patch(turn.id, { note: reasonOf(error) })
      }
    }
  }

  return (
    <section className="product">
      <header className="page-head rise" style={{ '--i': 0 } as CSSProperties}>
        <button className="icon-btn" onClick={onBack} aria-label="Back to Chat">
          <Icon name="collapse" size={18} />
        </button>
        <h1>{check?.name ?? 'Check'}</h1>
        {check && <span className="muted">{check.category || 'Quick look'}</span>}
        <div className="head-tools">
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
        {problem && (
          <p className="error-note" role="alert">
            {problem}
          </p>
        )}
        {!check && !problem && (
          <span className="work-line">
            <PixelGlyph size={13} active />
            Reads the check
          </span>
        )}
        {check && (
          <ul className="risk-list rise" style={{ '--i': 1 } as CSSProperties}>
            {check.risks.length === 0 && <li className="muted">No risk is on record.</li>}
            {check.risks.map((risk) => (
              <li key={risk.title}>
                <span className="level" data-level={risk.level}>
                  {LEVEL_WORD[risk.level]}
                </span>
                <div>
                  <strong>{risk.title}</strong>
                  {risk.body && <p>{risk.body}</p>}
                  {risk.sources.length > 0 && (
                    <span className="srcs">
                      {risk.sources.slice(0, 3).map((s, i) => (
                        <ExternalLink key={i} href={s.url || undefined}>
                          {s.host || s.url}
                        </ExternalLink>
                      ))}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="talk wide">
          <AnimatePresence initial={false}>
            {turns.map((t) => (
              <motion.div key={t.id} className="talk-q" initial={{ opacity: 0, y: m.d(10) }} animate={{ opacity: 1, y: 0 }} transition={m.tx.spring}>
                <p className="you">{t.text}</p>
                {t.state === 'running' && (
                  <span className="work-line">
                    <PixelGlyph size={13} active />
                    Searches the web
                  </span>
                )}
                {t.answer && (
                  <article className="answer">
                    <Markdown text={t.answer} live={false} />
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
        <Composer onSubmit={(text) => void ask(text)} running={asking} onStop={() => void stopAsking()} placeholder="Ask about this product" agents={false} autoFocus />
      </div>
    </section>
  )
}

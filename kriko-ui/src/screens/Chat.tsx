import { useEffect, useRef, useState, type CSSProperties, type UIEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { StepPill, Timeline } from '../activity/Timeline'
import type { AgentRef, Question, Run, Turn } from '../activity/run'
import { useChat } from '../chat'
import { useEngine, type Agent } from '../engine/Engine'
import { useRecents } from '../engine/recents'
import { usePrefs } from '../prefs'
import { AgentMark } from '../ui/AgentMark'
import { copyText } from '../ui/clipboard'
import { Composer } from '../ui/Composer'
import { Icon } from '../ui/Icon'
import { DitherSky } from '../ui/DitherSky'
import { ProductCard } from '../ui/ProductCard'
import { Markdown } from '../ui/Markdown'
import { showDrawer } from '../ui/drawerEvents'

/** Chat is the first page. Before a question it is a sky, a box and recent work.
 *  After a question the box drops to the bottom and the run fills the page. */
export function ChatScreen({ onOpen }: { onOpen: (lookupId: string) => void }) {
  const { motion: m } = usePrefs()
  const engine = useEngine()
  const { run, turns, start, stop } = useChat()
  const recents = useRecents()
  const thread = run.status !== 'idle' || turns.length > 0
  const running = run.status === 'running'
  /** The one detail the agent asked for, while it waits for the answer. */
  const asking = run.status !== 'idle' ? run.questions?.[0] : undefined
  /** A question taken back into the box to be changed. `at` makes the same words count twice. */
  const [draft, setDraft] = useState<{ text: string; at: number } | null>(null)
  /** What was asked in this chat, oldest first, for the up arrow. */
  const asked = [...turns.map((turn) => turn.prompt), ...(run.prompt ? [run.prompt] : [])]
  const agentOf = (ref?: AgentRef): Agent =>
    engine.agents.find((a) => a.id === ref?.id) ?? engine.agents.find((a) => a.id === engine.preferred) ?? engine.agents[0]
  const focusComposer = () => document.querySelector<HTMLTextAreaElement>('.composer-field')?.focus()

  return (
    <section className="chat" data-thread={thread}>
      <motion.div className="sky" initial={false} animate={{ opacity: thread ? 0 : 1, y: thread ? -m.d(30) : 0 }} transition={m.tx.page} aria-hidden="true">
        <DitherSky />
      </motion.div>

      <div className="chat-col">
        <AnimatePresence mode="popLayout" initial={false}>
          {!thread && (
            <motion.header
              key="hello"
              className="hello"
              initial={{ opacity: 0, y: m.d(12) }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -m.d(12) }}
              transition={m.tx.page}
            >
              <h1>What do you want to check?</h1>
              <div className="hello-actions">
                <button className="btn" onClick={() => showDrawer('setup')}>Set up and verify Kriko</button>
                <button className="btn ghost" onClick={() => showDrawer('chat')}>Chat settings</button>
              </div>
            </motion.header>
          )}
          {thread && (
            <motion.div
              key="thread"
              className="thread"
              initial={{ opacity: 0, y: m.d(16) }}
              animate={{ opacity: 1, y: 0 }}
              transition={m.tx.page}
            >
              <Thread
                run={run}
                turns={turns}
                onOpen={onOpen}
                onRetry={(turn) => start(turn.prompt, agentOf(turn.agent))}
                onEdit={(text) => setDraft({ text, at: Date.now() })}
                onSuggest={(text) => setDraft({ text, at: Date.now() })}
                onAnswer={(text, agent) => start(text, agentOf(agent))}
                onOwn={focusComposer}
              />
            </motion.div>
          )}
        </AnimatePresence>

        <motion.div layout="position" className="dock" data-tour="composer" transition={m.tx.spring}>
          <StepPill run={run} />
          <Composer
            onSubmit={(text, a, mode) => start(text, a, mode)}
            modes
            running={running}
            onStop={stop}
            autoFocus
            placeholder={asking ? 'Answer the question, or ask something else' : thread ? 'Ask a follow-up' : 'Ask about a product'}
            draft={draft}
            recall={asked}
          />
        </motion.div>

        <AnimatePresence mode="popLayout" initial={false}>
          {!thread && recents.length > 0 && (
            <motion.div key="recents" className="recents" exit={{ opacity: 0, y: m.d(10) }} transition={m.tx.quick}>
              <h2>Recent checks</h2>
              <ul>
                {recents.map((item, index) => (
                  <li key={item.id} className="rise" style={{ '--i': index + 2 } as CSSProperties}>
                    <button className="recent" onClick={() => onOpen(engine.mode === 'live' ? item.id : `demo:${item.name}`)}>
                      <span className="recent-name">{item.name}</span>
                      <span className="recent-note">{item.note}</span>
                      <span className="recent-meta mono">
                        {item.risks} {item.risks === 1 ? 'risk' : 'risks'} · {item.when}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </section>
  )
}

/** Who wrote an answer, above it. */
function AnswerHead({ agent }: { agent?: AgentRef }) {
  if (!agent || (!agent.id && !agent.label)) return null
  return (
    <header className="answer-head">
      <AgentMark id={agent.id} size={24} />
      <span>{agent.label || agent.id}</span>
    </header>
  )
}

/** What a reader does with an answer: take its words, or ask again. */
function AnswerActions({ text, onRetry }: { text: string; onRetry?: () => void }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef(0)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const copy = async () => {
    if (!(await copyText(text))) return
    setCopied(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setCopied(false), 1600)
  }
  return (
    <div className="answer-actions">
      <button className="act" onClick={() => void copy()} aria-label="Copy the answer" title="Copy the answer">
        <Icon name={copied ? 'check' : 'copy'} size={15} />
        <span>{copied ? 'Copied' : 'Copy'}</span>
      </button>
      {onRetry && (
        <button className="act" onClick={onRetry} aria-label="Ask again" title="Ask the same question again">
          <Icon name="retry" size={15} />
          <span>Retry</span>
        </button>
      )}
    </div>
  )
}

/** The one detail the agent could not settle, as buttons the reader presses.
 *  Pressing one asks it as their next message, so the thread keeps the answer
 *  and the agent sees it as something the reader said. */
function AskCard({
  question,
  agent,
  busy,
  onAnswer,
  onOwn,
}: {
  question: Question
  agent?: AgentRef
  busy: boolean
  onAnswer: (text: string) => void
  onOwn: () => void
}) {
  return (
    <article className="answer ask-card rise">
      <AnswerHead agent={agent} />
      <p className="ask-question">{question.ask}</p>
      <div className="ask-options" role="group" aria-label="Answers you can press">
        {question.options.map((option) => (
          <button key={option} className="ask-option" disabled={busy} onClick={() => onAnswer(option)}>
            {option}
          </button>
        ))}
        <button className="ask-option is-own" disabled={busy} onClick={onOwn}>
          Something else…
        </button>
      </div>
      {question.why && <p className="ask-why">{question.why}</p>}
    </article>
  )
}

function TaskActions({ prompt }: { prompt: string }) {
  if (/\b(?:create|author|make|file|save|import|update)\b.{0,60}\b(?:catalog|pack|research|quick look)/i.test(prompt)) return <div className="card-actions"><button className="btn" onClick={() => showDrawer('browse')}>Create or manage catalogs</button></div>
  if (/\b(?:backup|restore|snapshot)\b/i.test(prompt)) return <button className="btn" onClick={() => showDrawer('backups')}>Backup and restore</button>
  return null
}

function Thread({
  run,
  turns,
  onOpen,
  onRetry,
  onEdit,
  onSuggest,
  onAnswer,
  onOwn,
}: {
  run: Run
  turns: Turn[]
  onOpen: (lookupId: string) => void
  onRetry: (turn: Turn) => void
  onEdit: (text: string) => void
  onSuggest: (text: string) => void
  onAnswer: (text: string, agent?: AgentRef) => void
  onOwn: () => void
}) {
  const { motion: m } = usePrefs()
  const scroller = useRef<HTMLDivElement>(null)
  const inner = useRef<HTMLDivElement>(null)
  const stuck = useRef(true)
  const done = run.status === 'done'
  const followups = done ? run.followups : run.status === 'idle' ? turns.at(-1)?.followups : []
  const idle = run.status === 'idle'
  /** The answer is complete even if the turn is still naming its follow-ups. */
  const settled = run.status !== 'running' || run.answerFinal === true
  const questions = run.status !== 'idle' ? run.questions ?? [] : []
  const [away, setAway] = useState(false)

  // Follow the newest line, unless the reader scrolled up to read. The reader's
  // position is remembered at scroll time: judging it after the content grew
  // loses to any block taller than the slack (a long answer, a product card).
  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const onScroll = () => {
      stuck.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  // The thread grows by streaming text, steps and cards that animate in, so it
  // is the size that is watched, not a list of the things that can change it.
  useEffect(() => {
    const el = scroller.current
    const body = inner.current
    if (!el || !body) return
    const follow = () => {
      if (stuck.current) el.scrollTop = el.scrollHeight
    }
    follow()
    const watch = new ResizeObserver(follow)
    watch.observe(body)
    return () => watch.disconnect()
  }, [])

  // A new question is the reader's own act: take them to it.
  useEffect(() => {
    const el = scroller.current
    if (!el) return
    stuck.current = true
    el.scrollTo({ top: el.scrollHeight, behavior: m.on ? 'smooth' : 'auto' })
  }, [turns.length, m.on])

  const watch = (event: UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget
    setAway(el.scrollHeight - el.scrollTop - el.clientHeight > 260)
  }
  const latest = () => {
    const el = scroller.current
    el?.scrollTo({ top: el.scrollHeight, behavior: m.on ? 'smooth' : 'auto' })
  }

  // Only the newest question can be changed or asked again, and only once nothing is running.
  const newest = idle ? turns[turns.length - 1] : undefined

  return (
    <div className="thread-scroll" ref={scroller} onScroll={watch}>
      <div className="thread-inner" ref={inner}>
        {turns.map((turn) => (
          <div key={turn.id} className="turn">
            <div className="you-row">
              {newest === turn && (
                <button className="act you-edit" onClick={() => onEdit(turn.prompt)} aria-label="Edit the question" title="Change the question and ask again">
                  <Icon name="edit" size={14} />
                </button>
              )}
              <p className="you">{turn.prompt}</p>
            </div>
            <TaskActions prompt={turn.prompt} />
            {!!turn.rows?.length && <Timeline historical run={{ ...run, status: turn.error ? 'failed' : 'done', rows: turn.rows, answer: turn.answer, prompt: turn.prompt }} />}
            {turn.questions?.length ? (
              <AskCard question={turn.questions[0]} agent={turn.agent} busy={newest !== turn} onAnswer={(text) => onAnswer(text, turn.agent)} onOwn={onOwn} />
            ) : turn.answer && (
              <article className="answer">
                {turn.rows?.some((row) => row.id === 'activity-citation-warning' || row.id === 'activity-evidence-warning') && <p className="error-note" role="alert">Some claims or references could not be verified against the supplied evidence. Check the sources before relying on this answer.</p>}
                <AnswerHead agent={turn.agent} />
                <Markdown text={turn.answer} live={false} />
                <AnswerActions text={turn.answer} onRetry={newest === turn ? () => onRetry(turn) : undefined} />
              </article>
            )}
            {turn.error && (
              <p className="error-note" role="alert">
                {turn.error}
              </p>
            )}
            {turn.products.map((product) => (
              <ProductCard key={product.id} product={product} onOpen={onOpen} />
            ))}
          </div>
        ))}
        {run.status !== 'idle' && (
          <div className="you-row">
            {run.status !== 'running' && (
              <button className="act you-edit" onClick={() => onEdit(run.prompt)} aria-label="Edit the question" title="Change the question and ask again">
                <Icon name="edit" size={14} />
              </button>
            )}
            <p className="you">{run.prompt}</p>
          </div>
        )}
        {run.status !== 'idle' && !questions.length && <Timeline run={run} />}
        {run.status !== 'idle' && <TaskActions prompt={run.prompt} />}
        {!!questions.length ? (
          <AskCard question={questions[0]} agent={run.agent} busy={run.status === 'running'} onAnswer={(text) => onAnswer(text, run.agent)} onOwn={onOwn} />
        ) : (
          run.status !== 'idle' && (
            // Kept mounted for the whole turn, and re-keyed only when a new one
            // starts: unmounting it between polls reset the word counter and the
            // whole answer rose out of the blur again, once per poll.
            <article key={run.startedAt} className="answer rise">
              {run.rows.some((row) => row.id === 'activity-citation-warning' || row.id === 'activity-evidence-warning') && <p className="error-note" role="alert">Some claims or references could not be verified against the supplied evidence. Check the sources before relying on this answer.</p>}
              <AnswerHead agent={run.agent} />
              {run.answer && <Markdown text={run.answer} live={!settled} />}
              {run.answer && settled && (
                <AnswerActions
                  text={run.answer}
                  onRetry={() => onRetry({ id: String(run.startedAt), prompt: run.prompt, answer: run.answer, products: run.products, agent: run.agent })}
                />
              )}
            </article>
          )
        )}
        {run.status === 'failed' && (
          <p className="error-note" role="alert">
            {run.error}
          </p>
        )}
        <AnimatePresence>
          {done && run.products.map((product) => <ProductCard key={product.id} product={product} onOpen={onOpen} />)}
        </AnimatePresence>
        {!!followups?.length && (
          <div className="followup-prompts" aria-label="Related follow-up questions">
            <p className="muted">Keep exploring</p>
            {followups.map((question) => <button key={question} className="btn" onClick={() => onSuggest(question)}>{question}</button>)}
          </div>
        )}
      </div>
      {away && (
        <button className="jump" onClick={latest} aria-label="Jump to the latest">
          <Icon name="down" size={16} />
          <span>Latest</span>
        </button>
      )}
    </div>
  )
}

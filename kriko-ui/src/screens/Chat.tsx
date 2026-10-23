import { useEffect, useRef, useState, type CSSProperties, type UIEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { StepPill, Timeline } from '../activity/Timeline'
import { FocusProvider } from '../chat/focus'
import { groupsOf, threadUsage, turnLine } from '../chat/view'
import type { AgentRef, Question, Run, Turn, Usage } from '../activity/run'
import { useChat } from '../chat'
import { useEngine, type Agent } from '../engine/Engine'
import { useRecents } from '../engine/recents'
import { usePrefs } from '../prefs'
import { AgentMark, type AgentState } from '../ui/AgentMark'
import { copyText } from '../ui/clipboard'
import { ChatRail } from '../ui/ChatRail'
import { Composer } from '../ui/Composer'
import { ContextBar } from '../ui/ContextBar'
import { Icon } from '../ui/Icon'
import { DitherSky } from '../ui/DitherSky'
import { ProductList } from '../ui/ProductList'
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
  /** In a narrow window the sources column is a drawer; whether it is drawn. */
  const [railOpen, setRailOpen] = useState(false)
  // The column and the bars read what the turns already carry: nothing is kept twice.
  const groups = groupsOf(
    turns,
    run.status !== 'idle' ? { id: String(run.startedAt), prompt: run.prompt, products: run.products, pages: run.pages, running } : undefined,
  )
  const usage = threadUsage([...turns, ...(run.status !== 'idle' ? [run] : [])])
  const touched = groups.reduce((total, group) => total + group.products.length + group.pages.length, 0)
  /** What was asked in this chat, oldest first, for the up arrow. */
  const asked = [...turns.map((turn) => turn.prompt), ...(run.prompt ? [run.prompt] : [])]
  const agentOf = (ref?: AgentRef): Agent =>
    engine.agents.find((a) => a.id === ref?.id) ?? engine.agents.find((a) => a.id === engine.preferred) ?? engine.agents[0]
  const focusComposer = () => document.querySelector<HTMLTextAreaElement>('.composer-field')?.focus()

  return (
    <FocusProvider reduceMotion={!m.on}>
    <section className="chat" data-thread={thread}>
      <motion.div className="sky" initial={false} animate={{ opacity: thread ? 0 : 1, y: thread ? -m.d(30) : 0 }} transition={m.tx.page} aria-hidden="true">
        <DitherSky />
      </motion.div>

      <div className="chat-main">
      <div className="chat-col">
        <AnimatePresence mode="popLayout" initial={false}>
          {!thread && (
            <motion.header
              key="hello"
              className="hello"
              layout="position"
              initial={{ opacity: 0, y: m.d(12) }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -m.d(12) }}
              transition={m.tx.page}
            >
              <h1>What do you want to check?</h1>
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
          <ContextBar usage={usage} />
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
      {thread && <ChatRail groups={groups} onOpen={onOpen} open={railOpen} onClose={() => setRailOpen(false)} />}
      </div>
      {thread && (
        <button className="cr-toggle" onClick={() => setRailOpen((value) => !value)} aria-expanded={railOpen} aria-controls="chat-rail">
          <Icon name="queue" size={15} />
          <span>Sources</span>
          <span className="mono">{touched}</span>
        </button>
      )}
    </section>
    </FocusProvider>
  )
}

/** Who wrote an answer, above it. */
function AnswerHead({ agent, state = 'idle' }: { agent?: AgentRef; state?: AgentState }) {
  if (!agent || (!agent.id && !agent.label)) return null
  return (
    <header className="answer-head">
      <AgentMark id={agent.id} size={28} state={state} />
      <span>{agent.label || agent.id}</span>
    </header>
  )
}

/** What a reader does with an answer: take its words, or ask again. */
function AnswerActions({ text, onRetry, usage }: { text: string; onRetry?: () => void; usage?: Usage }) {
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
        <button className="act" onClick={onRetry} aria-label="Retry" title="Ask the same question again">
          <Icon name="retry" size={15} />
          <span>Retry</span>
        </button>
      )}
      {usage && (
        <span className="act-usage mono" title={usage.used !== null ? `Largest prompt this turn: ${usage.used.toLocaleString('en-GB')} tokens` : 'This agent did not say how large its prompts were'}>
          {turnLine(usage)}
        </span>
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
  const answer = useRef<HTMLElement>(null)
  const stuck = useRef(true)
  const done = run.status === 'done'
  const running = run.status === 'running'
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
  // Only a run in flight is followed: the cards and follow-ups that arrive with
  // the finished turn must not pull the reader off the answer they just read.
  useEffect(() => {
    const el = scroller.current
    const body = inner.current
    if (!el || !body) return
    const follow = () => {
      if (body.dataset.running === 'true' && stuck.current) el.scrollTop = el.scrollHeight
      setAway(el.scrollHeight - el.scrollTop - el.clientHeight > 120)
    }
    follow()
    const watch = new ResizeObserver(follow)
    watch.observe(body)
    return () => watch.disconnect()
  }, [])

  // The answer is settled: the actions, products and follow-ups below it arrive
  // now. Reveal all of them when the answer still starts in view after the
  // scroll; otherwise leave its last lines in view and let the reader choose to
  // go further. Never yank them off the answer they just read.
  const arrived = useRef(false)
  useEffect(() => {
    if (running) {
      arrived.current = false
      return
    }
    const el = scroller.current
    const box = answer.current
    if (!el || !box || arrived.current || !stuck.current) return
    arrived.current = true
    const view = el.getBoundingClientRect()
    const text = box.getBoundingClientRect()
    const below = el.scrollHeight - el.scrollTop - el.clientHeight
    const hidesStart = text.top - below < view.top
    const amount = Math.max(0, text.bottom - view.bottom + 12)
    const top = hidesStart ? el.scrollTop + amount : el.scrollTop + below
    if (top > el.scrollTop + 1) el.scrollTo({ top, behavior: m.on ? 'smooth' : 'auto' })
  }, [running, m.on])

  // A new question is the reader's own act: take them to it.
  useEffect(() => {
    const el = scroller.current
    if (!el) return
    stuck.current = true
    el.scrollTo({ top: el.scrollHeight, behavior: m.on ? 'smooth' : 'auto' })
  }, [turns.length, m.on])

  const watch = (event: UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget
    setAway(el.scrollHeight - el.scrollTop - el.clientHeight > 120)
  }
  const latest = () => {
    const el = scroller.current
    el?.scrollTo({ top: el.scrollHeight, behavior: m.on ? 'smooth' : 'auto' })
  }

  // Only the newest question can be changed or asked again, and only once nothing is running.
  const newest = idle ? turns[turns.length - 1] : undefined

  return (
    <div className="thread-scroll" ref={scroller} onScroll={watch}>
      <div className="thread-inner" ref={inner} data-running={running ? 'true' : undefined}>
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
                <AnswerActions text={turn.answer} onRetry={newest === turn ? () => onRetry(turn) : undefined} usage={turn.usage} />
              </article>
            )}
            {turn.error && (
              <p className="error-note" role="alert">
                {turn.error}
              </p>
            )}
            <ProductList products={turn.products} onOpen={onOpen} />
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
        {/* Only a run with activity has a record to show. A turn that asks one
            question, or fails before its first step, keeps no empty card; a run
            that is still waiting for an answer keeps the rows it already has. */}
        {run.status !== 'idle' && run.rows.length > 0 && <Timeline key={`timeline-${run.startedAt}`} run={run} />}
        {run.status !== 'idle' && <TaskActions prompt={run.prompt} />}
        {!!questions.length ? (
          <AskCard question={questions[0]} agent={run.agent} busy={run.status === 'running'} onAnswer={(text) => onAnswer(text, run.agent)} onOwn={onOwn} />
        ) : (
          run.status !== 'idle' && (
            // Kept mounted for the whole turn, and re-keyed only when a new one
            // starts: unmounting it between polls reset the word counter and the
            // whole answer rose out of the blur again, once per poll.
            <article key={run.startedAt} className="answer rise" ref={answer}>
              {run.rows.some((row) => row.id === 'activity-citation-warning' || row.id === 'activity-evidence-warning') && <p className="error-note" role="alert">Some claims or references could not be verified against the supplied evidence. Check the sources before relying on this answer.</p>}
              <AnswerHead agent={run.agent} state={run.status === 'running' ? 'working' : run.status === 'failed' ? 'failed' : run.status === 'done' ? 'done' : 'idle'} />
              {run.answer && <Markdown text={run.answer} live={!settled} />}
              {run.answer && settled && (
                <AnswerActions
                  text={run.answer}
                  usage={run.usage}
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
        {done && <ProductList products={run.products} onOpen={onOpen} />}
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

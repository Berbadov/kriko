import { useEffect, useRef, useState, type CSSProperties, type UIEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { StepPill, Timeline } from '../activity/Timeline'
import type { AgentRef, Run, Turn } from '../activity/run'
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

/** Chat is the first page. Before a question it is a sky, a box and recent work.
 *  After a question the box drops to the bottom and the run fills the page. */
export function ChatScreen({ onOpen }: { onOpen: (lookupId: string) => void }) {
  const { motion: m } = usePrefs()
  const engine = useEngine()
  const { run, turns, start, stop } = useChat()
  const recents = useRecents()
  const thread = run.status !== 'idle' || turns.length > 0
  const running = run.status === 'running'
  /** A question taken back into the box to be changed. `at` makes the same words count twice. */
  const [draft, setDraft] = useState<{ text: string; at: number } | null>(null)
  /** What was asked in this chat, oldest first, for the up arrow. */
  const asked = [...turns.map((turn) => turn.prompt), ...(run.prompt ? [run.prompt] : [])]
  const agentOf = (ref?: AgentRef): Agent =>
    engine.agents.find((a) => a.id === ref?.id) ?? engine.agents.find((a) => a.id === engine.preferred) ?? engine.agents[0]

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
              />
            </motion.div>
          )}
        </AnimatePresence>

        <motion.div layout="position" className="dock" data-tour="composer" transition={m.tx.spring}>
          <StepPill run={run} />
          <Composer
            onSubmit={(text, a) => start(text, a)}
            running={running}
            onStop={stop}
            autoFocus
            placeholder={thread ? 'Ask a follow-up' : 'Ask about a product'}
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

function Thread({
  run,
  turns,
  onOpen,
  onRetry,
  onEdit,
}: {
  run: Run
  turns: Turn[]
  onOpen: (lookupId: string) => void
  onRetry: (turn: Turn) => void
  onEdit: (text: string) => void
}) {
  const { motion: m } = usePrefs()
  const end = useRef<HTMLDivElement>(null)
  const done = run.status === 'done'
  const idle = run.status === 'idle'
  const [away, setAway] = useState(false)

  // Follow the newest line, unless the reader scrolled up to read.
  useEffect(() => {
    const el = end.current?.closest<HTMLElement>('.thread-scroll')
    if (!el) return
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 140
    if (near) el.scrollTo({ top: el.scrollHeight, behavior: m.on ? 'smooth' : 'auto' })
  }, [turns.length, run.rows.length, run.answer.length, done, m.on])

  const watch = (event: UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget
    setAway(el.scrollHeight - el.scrollTop - el.clientHeight > 260)
  }
  const latest = () => {
    const el = end.current?.closest<HTMLElement>('.thread-scroll')
    el?.scrollTo({ top: el.scrollHeight, behavior: m.on ? 'smooth' : 'auto' })
  }

  // Only the newest question can be changed or asked again, and only once nothing is running.
  const newest = idle ? turns[turns.length - 1] : undefined

  return (
    <div className="thread-scroll" onScroll={watch}>
      <div className="thread-inner">
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
            {turn.answer && (
              <article className="answer">
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
        {run.status !== 'idle' && <Timeline run={run} />}
        {run.answer && (
          <article className="answer rise">
            <AnswerHead agent={run.agent} />
            <Markdown text={run.answer} live={run.status === 'running'} />
            {run.status !== 'running' && (
              <AnswerActions
                text={run.answer}
                onRetry={() => onRetry({ id: String(run.startedAt), prompt: run.prompt, answer: run.answer, products: run.products, agent: run.agent })}
              />
            )}
          </article>
        )}
        {run.status === 'failed' && (
          <p className="error-note" role="alert">
            {run.error}
          </p>
        )}
        <AnimatePresence>
          {done && run.products.map((product) => <ProductCard key={product.id} product={product} onOpen={onOpen} />)}
        </AnimatePresence>
        <div ref={end} />
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

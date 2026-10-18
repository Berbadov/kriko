import { useEffect, useRef, type CSSProperties } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { StepPill, Timeline } from '../activity/Timeline'
import type { Run, Turn } from '../activity/run'
import { useChat } from '../chat'
import { useEngine } from '../engine/Engine'
import { useRecents } from '../engine/recents'
import { usePrefs } from '../prefs'
import { Composer } from '../ui/Composer'
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
              <Thread run={run} turns={turns} onOpen={onOpen} />
            </motion.div>
          )}
        </AnimatePresence>

        <motion.div layout="position" className="dock" data-tour="composer" transition={m.tx.spring}>
          <StepPill run={run} />
          <Composer onSubmit={(text, a) => start(text, a)} running={running} onStop={stop} autoFocus placeholder={thread ? 'Ask a follow-up' : 'Ask about a product'} />
        </motion.div>

        <AnimatePresence mode="popLayout" initial={false}>
          {!thread && (
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

function Thread({ run, turns, onOpen }: { run: Run; turns: Turn[]; onOpen: (lookupId: string) => void }) {
  const { motion: m } = usePrefs()
  const scroller = useRef<HTMLDivElement>(null)
  const inner = useRef<HTMLDivElement>(null)
  const stuck = useRef(true)
  const done = run.status === 'done'

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

  return (
    <div className="thread-scroll" ref={scroller}>
      <div className="thread-inner" ref={inner}>
        {turns.map((turn) => (
          <div key={turn.id} className="turn">
            <p className="you">{turn.prompt}</p>
            {turn.answer && (
              <article className="answer">
                <Markdown text={turn.answer} live={false} />
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
        {run.status !== 'idle' && <p className="you">{run.prompt}</p>}
        {run.status !== 'idle' && <Timeline run={run} />}
        {run.answer && (
          <article className="answer rise">
            <Markdown text={run.answer} live={run.status === 'running'} />
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
      </div>
    </div>
  )
}

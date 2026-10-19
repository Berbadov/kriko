import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useEngine } from '../engine/Engine'
import { usePrefs } from '../prefs'
import { showDrawer } from '../ui/drawerEvents'

/** A short walk through the window, once, on the first start. The reader can
 *  skip it at any step and take it again from Settings. */

interface Step {
  /** The `data-tour` value of the thing to show. Without one the card sits in the middle. */
  target?: string
  title: string
  text: string
  /** A drawer panel to open first, because the target is inside it. */
  panel?: string
}

const STEPS: Step[] = [
  { title: 'Welcome to Kriko', text: 'Kriko tells you what can go wrong with a product before you buy it. This tour takes one minute.' },
  { target: 'composer', title: 'Ask here', text: 'Type a product or a question. Kriko reads your catalogs and the web, and shows its work.' },
  { target: 'agent-pick', title: 'Pick an agent', text: 'The agent does the reading. Choose one for each question. Settings sets the one you use most.' },
  { target: 'new-chat', title: 'Chats', text: 'Start a new chat here. Your old chats stay in the list below.' },
  { target: 'nav-compare', title: 'Compare', text: 'Put up to four products side by side. Products are columns. Risks are rows.' },
  { target: 'nav-queue', title: 'Queue', text: 'Send products from your browser. Kriko checks them one by one, when you press Start.' },
  { target: 'source-kinds', panel: 'settings', title: 'Where to look', text: 'Choose the kinds of page Kriko reads for each product: forums, reviews, recalls and more. At least one stays on.' },
  { target: 'more', title: 'More', text: 'Settings, agents, local models, catalogs and sites are here. You can take this tour again from Settings.' },
  { title: 'Verify your setup', panel: 'setup', text: 'Check the selected agent, get a catalog, connect the extension, and complete a real sourced check.' },
]

const KEY = 'kriko.tour'
const EVENT = 'kriko:tour'

/** Ask for the tour. Settings uses this. */
export const startTour = () => window.dispatchEvent(new Event(EVENT))

const seen = () => {
  try {
    return localStorage.getItem(KEY) === 'done'
  } catch {
    return false
  }
}
const remember = () => {
  try {
    localStorage.setItem(KEY, 'done')
  } catch {
    /* the tour may show again; that is all */
  }
}

const PAD = 8
const CARD_W = 340

interface Place {
  rect: { top: number; left: number; width: number; height: number } | null
  card: { top?: number; left?: number; bottom?: number }
}

function place(step: Step): Place {
  const el = step.target ? document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`) : null
  if (!el) return { rect: null, card: {} }
  const box = el.getBoundingClientRect()
  const rect = { top: box.top - PAD, left: box.left - PAD, width: box.width + PAD * 2, height: box.height + PAD * 2 }
  const w = window.innerWidth
  const h = window.innerHeight
  // Beside it when it sits at the left edge, above it when it sits low, below it otherwise.
  // Beside a thing in a panel, to the right of the panel.
  if (step.panel) return { rect, card: { left: Math.min(box.right + PAD + 24, w - CARD_W - 16), top: Math.min(Math.max(box.top - 8, 16), h - 260) } }
  if (box.right < 360) return { rect, card: { left: box.right + PAD + 16, top: Math.min(Math.max(box.top - 8, 16), h - 260) } }
  const left = Math.min(Math.max(box.left + box.width / 2 - CARD_W / 2, 16), w - CARD_W - 16)
  if (box.top > h / 2) return { rect, card: { left, bottom: h - box.top + PAD + 16 } }
  return { rect, card: { left, top: box.bottom + PAD + 16 } }
}

export function Tour({ onStart }: { onStart: () => void }) {
  const { motion: m } = usePrefs()
  const { mode } = useEngine()
  const [at, setAt] = useState<number | null>(null)
  const [spot, setSpot] = useState<Place>({ rect: null, card: {} })
  const next = useRef<HTMLButtonElement>(null)
  /** The caller's function changes on every render. The tour must not restart for it. */
  const started = useRef(onStart)
  useEffect(() => {
    started.current = onStart
  }, [onStart])

  const open = useCallback(() => {
    started.current()
    setAt(0)
  }, [])

  const close = useCallback(() => {
    remember()
    showDrawer(null)
    setAt(null)
  }, [])

  // The first start. A browser under automation never gets it, so a test is not blocked by it.
  useEffect(() => {
    if (mode === 'checking' || seen() || navigator.webdriver) return
    const timer = window.setTimeout(open, 900)
    return () => window.clearTimeout(timer)
  }, [mode, open])

  useEffect(() => {
    window.addEventListener(EVENT, open)
    return () => window.removeEventListener(EVENT, open)
  }, [open])

  useLayoutEffect(() => {
    if (at === null) return
    const step = STEPS[at]
    const measure = () => setSpot(place(step))
    // A step inside a panel opens the panel, and every other step closes it.
    showDrawer(step.panel ?? null)
    measure()
    // The panel slides in, so the spot is measured again once it has landed.
    const settle = step.panel
      ? window.setTimeout(() => {
          document.querySelector(`[data-tour="${step.target}"]`)?.scrollIntoView({ block: 'center' })
          measure()
        }, 650)
      : undefined
    window.addEventListener('resize', measure)
    return () => {
      window.clearTimeout(settle)
      window.removeEventListener('resize', measure)
    }
  }, [at])

  useEffect(() => {
    if (at === null) return
    next.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
      else if (event.key === 'ArrowRight') setAt((now) => (now === null ? now : Math.min(now + 1, STEPS.length - 1)))
      else if (event.key === 'ArrowLeft') setAt((now) => (now === null ? now : Math.max(now - 1, 0)))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [at, close])

  if (at === null) return null
  const step = STEPS[at]
  const last = at === STEPS.length - 1
  const { rect, card } = spot

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label="Tour of Kriko">
      {rect ? (
        <motion.div className="tour-spot" initial={false} animate={rect} transition={m.tx.spring} aria-hidden="true" />
      ) : (
        <div className="tour-wash" aria-hidden="true" />
      )}
      <AnimatePresence mode="wait" initial>
        <motion.div
          key={at}
          className="tour-card"
          data-centered={!rect}
          style={rect ? { ...card, width: CARD_W } : undefined}
          initial={{ opacity: 0, y: m.d(10) }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -m.d(6) }}
          transition={m.tx.soft}
        >
          <small className="tour-count">
            {at + 1} of {STEPS.length}
          </small>
          <h2>{step.title}</h2>
          <p>{step.text}</p>
          <div className="tour-dots" aria-hidden="true">
            {STEPS.map((_, index) => (
              <i key={index} data-on={index === at} />
            ))}
          </div>
          <div className="tour-actions">
            {!last && (
              <button className="tour-skip" onClick={close}>
                Skip
              </button>
            )}
            {at > 0 && <button onClick={() => setAt(at - 1)}>Back</button>}
            <button ref={next} className="tour-next" onClick={() => (last ? close() : setAt(at + 1))}>
              {last ? 'Done' : at === 0 ? 'Start' : 'Next'}
            </button>
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

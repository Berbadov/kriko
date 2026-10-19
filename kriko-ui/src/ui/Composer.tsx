import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useEngine, type Agent } from '../engine/Engine'
import { usePrefs } from '../prefs'
import { AgentMark } from './AgentMark'
import { Icon } from './Icon'
import { PixelGlyph } from './PixelGlyph'

/** The box where the reader asks. Frosted glass, so the sky shows through. */
export function Composer({
  onSubmit,
  running,
  onStop,
  placeholder = 'Ask about a product',
  autoFocus = false,
  agents: pickAgent = true,
  draft = null,
  recall = [],
}: {
  onSubmit: (text: string, agent: Agent) => void
  running: boolean
  onStop: () => void
  placeholder?: string
  autoFocus?: boolean
  /** Show the agent pick. Off where the engine chooses the agent itself. */
  agents?: boolean
  /** Words to put in the box, such as a question taken back to be changed. A new `at` puts them again. */
  draft?: { text: string; at: number } | null
  /** What was asked before, oldest first. The up arrow in an empty box walks back through it. */
  recall?: string[]
}) {
  const { motion: m } = usePrefs()
  const { agents, preferred } = useEngine()
  const [text, setText] = useState('')
  const [chosen, setChosen] = useState('')
  // The reader's own choice wins. Then the agent set in Settings. Then the first.
  const agent = agents.find((a) => a.id === chosen) ?? agents.find((a) => a.id === preferred) ?? agents[0]
  const [menu, setMenu] = useState(false)
  const field = useRef<HTMLTextAreaElement>(null)

  /** How far back the up arrow has gone: 0 is the box as the reader left it. */
  const back = useRef(0)

  useEffect(() => {
    if (autoFocus) field.current?.focus()
  }, [autoFocus])

  useEffect(() => {
    if (!draft) return
    setText(draft.text)
    back.current = 0
    field.current?.focus()
  }, [draft])

  const send = () => {
    const value = text.trim()
    if (!value || running) return
    onSubmit(value, agent)
    setText('')
    back.current = 0
  }

  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send()
      return
    }
    // Up in an empty box (or one already showing an old question) brings the last question back.
    const walking = back.current > 0
    if (event.key === 'ArrowUp' && recall.length && (!text || walking)) {
      event.preventDefault()
      back.current = Math.min(back.current + 1, recall.length)
      setText(recall[recall.length - back.current])
    } else if (event.key === 'ArrowDown' && walking) {
      event.preventDefault()
      back.current -= 1
      setText(back.current ? recall[recall.length - back.current] : '')
    }
    // Escape closes the agent menu, and it is the only key that does: a
    // `role="listbox"` that can only be dismissed with a mouse is a menu a
    // keyboard user cannot leave.
    if (event.key === 'Escape' && menu) {
      event.stopPropagation()
      setMenu(false)
    }
  }

  /** Arrow keys move through the agent list, as `role="listbox"` promises. */
  const onMenuKey = (event: KeyboardEvent<HTMLUListElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const at = agents.findIndex((item) => item.id === chosen)
    const step = event.key === 'ArrowDown' ? 1 : -1
    const next = agents[(at + step + agents.length) % agents.length]
    if (next) setChosen(next.id)
  }

  return (
    <div className="composer">
      <textarea
        ref={field}
        className="composer-field"
        value={text}
        placeholder={placeholder}
        rows={1}
        onChange={(event) => {
          setText(event.target.value)
          back.current = 0
        }}
        onKeyDown={onKey}
        aria-label="Message"
      />
      <div className="composer-foot">
        {/* The attach button is gone. It carried `aria-label="Add a file"` and
            no `onClick` at all: a screen reader announced a control that did
            nothing, and a reader who pressed it got nothing. Nothing in the
            engine accepts an attachment, so there is no control to wire. */}
        {pickAgent && (
        <div className="agent-pick" data-tour="agent-pick">
          <button className="pill" onClick={() => setMenu((v) => !v)} aria-haspopup="listbox" aria-expanded={menu}>
            <AgentMark id={agent.id} size={20} />
            {agent.label}
            <Icon name="chevron" size={13} />
          </button>
          <AnimatePresence>
            {menu && (
              <motion.ul
                className="menu"
                role="listbox"
                onKeyDown={onMenuKey}
                tabIndex={-1}
                initial={{ opacity: 0, y: m.d(6), scale: m.on ? 0.97 : 1 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: m.d(4) }}
                transition={m.tx.quick}
              >
                {agents.map((item) => (
                  <li key={item.id || item.label}>
                    <button
                      role="option"
                      aria-selected={item.id === agent.id}
                      onClick={() => {
                        setChosen(item.id)
                        setMenu(false)
                      }}
                    >
                      <AgentMark id={item.id} size={20} />
                      <span className="menu-label">{item.label}</span>
                      {item.id === agent.id && <Icon name="check" size={14} />}
                    </button>
                  </li>
                ))}
              </motion.ul>
            )}
          </AnimatePresence>
        </div>
        )}
        <span className="grow" />
        {running ? (
          <button className="send is-running" onClick={onStop} aria-label="Stop">
            <PixelGlyph size={18} tone="ink" />
          </button>
        ) : (
          <button className="send" onClick={send} disabled={!text.trim()} aria-label="Send">
            <Icon name="send" size={17} />
          </button>
        )}
      </div>
    </div>
  )
}

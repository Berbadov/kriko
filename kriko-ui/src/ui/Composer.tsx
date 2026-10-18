import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useEngine, type Agent } from '../engine/Engine'
import { usePrefs } from '../prefs'
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
}: {
  onSubmit: (text: string, agent: Agent) => void
  running: boolean
  onStop: () => void
  placeholder?: string
  autoFocus?: boolean
  /** Show the agent pick. Off where the engine chooses the agent itself. */
  agents?: boolean
}) {
  const { motion: m } = usePrefs()
  const { agents, preferred } = useEngine()
  const [text, setText] = useState('')
  const [chosen, setChosen] = useState('')
  // The reader's own choice wins. Then the agent set in Settings. Then the first.
  const agent = agents.find((a) => a.id === chosen) ?? agents.find((a) => a.id === preferred) ?? agents[0]
  const [menu, setMenu] = useState(false)
  const field = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (autoFocus) field.current?.focus()
  }, [autoFocus])

  const send = () => {
    const value = text.trim()
    if (!value || running) return
    onSubmit(value, agent)
    setText('')
  }

  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send()
    }
  }

  return (
    <div className="composer">
      <textarea
        ref={field}
        className="composer-field"
        value={text}
        placeholder={placeholder}
        rows={1}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKey}
        aria-label="Message"
      />
      <div className="composer-foot">
        <button className="icon-btn" aria-label="Add a file">
          <Icon name="attach" />
        </button>
        {pickAgent && (
        <div className="agent-pick" data-tour="agent-pick">
          <button className="pill" onClick={() => setMenu((v) => !v)} aria-haspopup="listbox" aria-expanded={menu}>
            <Icon name="spark" size={14} />
            {agent.label}
            <Icon name="chevron" size={13} />
          </button>
          <AnimatePresence>
            {menu && (
              <motion.ul
                className="menu"
                role="listbox"
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
                      {item.label}
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

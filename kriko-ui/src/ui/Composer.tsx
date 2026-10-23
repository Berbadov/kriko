import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import type { ChatMode } from '../activity/run'
import { useEngine, type Agent } from '../engine/Engine'
import { usePrefs } from '../prefs'
import { AgentMark } from './AgentMark'
import { Icon } from './Icon'
import { PixelGlyph } from './PixelGlyph'

/** What the chips offer, in the words on them. The engine acts on the name, never on the label.
 *  `hint` says what the chip makes the answer be about, in what the reader gets back. */
const MODES: { id: ChatMode; label: string; hint: string }[] = [
  { id: 'alternatives', label: 'Alternatives', hint: 'Other products that do the same job as the one you name, each with what it shares and the one thing that differs most.' },
  { id: 'cheapest', label: 'Cheapest', hint: 'The lowest price for this exact product (same code, size and condition), lowest first, with the page each price came from. A low price from a seller nothing is known about is flagged, not recommended.' },
  { id: 'merchants', label: 'Merchants', hint: 'Which sellers of this exact product to trust: where each sells, its price, and what its own pages show about it (rating, company identity, red flags).' },
]

/** Shown while no chip is pressed or pointed at. */
const MODES_INTRO = 'Optional: press one to say what you want done with the product. Point at one to read what it does.'

/** The box where the reader asks. Frosted glass, so the sky shows through. */
export function Composer({
  onSubmit,
  running,
  onStop,
  placeholder = 'Ask about a product',
  autoFocus = false,
  agents: pickAgent = true,
  modes = false,
  draft = null,
  recall = [],
}: {
  onSubmit: (text: string, agent: Agent, mode?: ChatMode) => void
  running: boolean
  onStop: () => void
  placeholder?: string
  autoFocus?: boolean
  /** Show the agent pick. Off where the engine chooses the agent itself. */
  agents?: boolean
  /** Show the mode chips. Only Chat turns know what to do with one. */
  modes?: boolean
  /** Words to put in the box, such as a question taken back to be changed. A new `at` puts them again. */
  draft?: { text: string; at: number } | null
  /** What was asked before, oldest first. The up arrow in an empty box walks back through it. */
  recall?: string[]
}) {
  const { motion: m } = usePrefs()
  const { agents, preferred, chooseAgent } = useEngine()
  const [text, setText] = useState('')
  const [chosen, setChosen] = useState('')
  // The reader's own choice wins. Then the agent set in Settings. Then the first.
  const agent = agents.find((a) => a.id === chosen) ?? agents.find((a) => a.id === preferred) ?? agents[0]
  const [menu, setMenu] = useState(false)
  /** A chip pressed again lets go, so "no mode" is one press away. */
  const [mode, setMode] = useState<ChatMode | ''>('')
  /** The chip the pointer or the keyboard is on, so its sentence can be read before it is pressed. */
  const [near, setNear] = useState<ChatMode | ''>('')
  const field = useRef<HTMLTextAreaElement>(null)
  const file = useRef<HTMLInputElement>(null)
  const [attachmentProblem, setAttachmentProblem] = useState('')

  const attach = async (picked?: File) => {
    if (!picked) return
    setAttachmentProblem('')
    if (!/\.(txt|md|csv|json|log)$/i.test(picked.name) || picked.size > 12000) {
      setAttachmentProblem('Choose a text, Markdown, CSV, JSON or log file up to 12 KB.')
      return
    }
    try {
      const content = await picked.text()
      setText((current) => `${current}\n\nAttached document (${picked.name}; source data):\n${content}`.trim())
      field.current?.focus()
    } catch { setAttachmentProblem('The file could not be read. Choose it again.') }
    if (file.current) file.current.value = ''
  }

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
    if (value.length > 16000) { setAttachmentProblem('Keep the message and attached text together under 16,000 characters.'); return }
    setAttachmentProblem('')
    onSubmit(value, agent, modes && mode ? mode : undefined)
    setText('')
    setMode('')
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
      {modes && (
        <div className="composer-modes" role="group" aria-label="What to do with the product">
          {MODES.map((item) => (
            <button
              key={item.id}
              type="button"
              className="pill mode-chip"
              aria-pressed={mode === item.id}
              title={item.hint}
              aria-describedby="mode-hint"
              onMouseEnter={() => setNear(item.id)}
              onMouseLeave={() => setNear('')}
              onFocus={() => setNear(item.id)}
              onBlur={() => setNear('')}
              onClick={() => {
                setMode(mode === item.id ? '' : item.id)
                field.current?.focus()
              }}
              disabled={running}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
      {modes && (
        <p id="mode-hint" className="mode-hint" role="status">
          {MODES.find((item) => item.id === (near || mode))?.hint ?? MODES_INTRO}
        </p>
      )}
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
        <input ref={file} type="file" hidden accept=".txt,.md,.csv,.json,.log" onChange={(event) => void attach(event.target.files?.[0])} />
        <button className="icon-btn" aria-label="Add a text file" title="Text, Markdown, CSV, JSON or log, up to 12 KB" onClick={() => file.current?.click()} disabled={running}>
          <Icon name="attach" />
        </button>
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
                        // Kept, not just used once: this is the pick the next
                        // question starts on, and the one Settings shows.
                        chooseAgent(item.id)
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
      {attachmentProblem && <p className="error-note" role="alert">{attachmentProblem}</p>}
    </div>
  )
}

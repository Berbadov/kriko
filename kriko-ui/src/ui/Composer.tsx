import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import type { ChatMode } from '../activity/run'
import { useEngine, type Agent } from '../engine/Engine'
import { usePrefs } from '../prefs'
import { AgentMark } from './AgentMark'
import { Icon } from './Icon'
import { PixelGlyph } from './PixelGlyph'

/** The slider's three ways to ask, in the words on it. The engine acts on the id, never on the label.
 *  `find` is Chat's default: the engine still reads the words, so it is sent as no mode at all. */
export const MODES: { id: ChatMode; label: string; hint: string; placeholder: string }[] = [
  { id: 'find', label: 'Find', hint: 'Find the product that fits, and where to get it', placeholder: 'What are you looking for?' },
  { id: 'alternatives', label: 'Alternatives', hint: 'Other products that do the same job as the one you name', placeholder: 'Which product do you want alternatives to?' },
  { id: 'research', label: 'Research', hint: 'What a product is, how it is rated and what goes wrong with it', placeholder: 'Which product do you want to know about?' },
]

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
  mode: heldMode,
  onMode,
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
  /** The slider, when the screen holds it (so the page around the box can follow it). */
  mode?: ChatMode
  onMode?: (mode: ChatMode) => void
}) {
  const { motion: m } = usePrefs()
  const { agents, preferred, chooseAgent } = useEngine()
  const [text, setText] = useState('')
  const [chosen, setChosen] = useState('')
  // The reader's own choice wins. Then the agent set in Settings. Then the first.
  const agent = agents.find((a) => a.id === chosen) ?? agents.find((a) => a.id === preferred) ?? agents[0]
  const [menu, setMenu] = useState(false)
  const [ownMode, setOwnMode] = useState<ChatMode>('find')
  const mode = heldMode ?? ownMode
  const setMode = (next: ChatMode) => { setOwnMode(next); onMode?.(next) }
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
    onSubmit(value, agent, modes && mode !== 'find' ? mode : undefined)
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

  const trigger = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const [place, setPlace] = useState<CSSProperties>({})

  /** Keep the list inside the window: above the button when it fits there,
   *  otherwise on the side with more room, scrolling when neither is enough. */
  const reposition = useCallback(() => {
    const button = trigger.current
    if (!button) return
    const box = button.getBoundingClientRect()
    const gap = 8
    const top = 48
    const roomAbove = box.top - gap - top
    const roomBelow = window.innerHeight - box.bottom - gap * 2
    const wanted = list.current?.scrollHeight ?? 0
    const up = roomAbove >= Math.min(wanted, 320) || roomAbove >= roomBelow
    const left = Math.max(gap, Math.min(box.left, window.innerWidth - 220 - gap))
    setPlace(up
      ? { left, bottom: window.innerHeight - box.top + gap, maxHeight: Math.max(120, roomAbove) }
      : { left, top: box.bottom + gap, maxHeight: Math.max(120, roomBelow) })
  }, [])

  useLayoutEffect(() => {
    if (!menu) return
    reposition()
    const selected = list.current?.querySelector<HTMLElement>('[aria-selected="true"]') ?? list.current?.querySelector<HTMLElement>('[role="option"]')
    selected?.focus({ preventScroll: false })
    window.addEventListener('resize', reposition)
    window.addEventListener('scroll', reposition, true)
    const outside = (event: PointerEvent) => {
      const target = event.target as Node
      if (!list.current?.contains(target) && !trigger.current?.contains(target)) setMenu(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => {
      window.removeEventListener('resize', reposition)
      window.removeEventListener('scroll', reposition, true)
      document.removeEventListener('pointerdown', outside)
    }
  }, [menu, reposition, agents.length])

  /** Arrow keys, Home and End move through the list; Escape and Tab leave it. */
  const onMenuKey = (event: KeyboardEvent<HTMLUListElement>) => {
    if (event.key === 'Escape' || event.key === 'Tab') {
      if (event.key === 'Escape') event.stopPropagation()
      setMenu(false)
      trigger.current?.focus()
      return
    }
    const options = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="option"]'))
    const at = options.indexOf(document.activeElement as HTMLElement)
    const next = event.key === 'ArrowDown' ? at + 1 : event.key === 'ArrowUp' ? at - 1 : event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : null
    if (next === null || !options.length) return
    event.preventDefault()
    options[(next + options.length) % options.length].focus()
  }

  const selected = MODES.find((item) => item.id === mode) ?? MODES[0]

  return (
    <div className="composer-root">
      <div className="composer">
        <textarea
          ref={field}
          className="composer-field"
          value={text}
          placeholder={modes && mode !== 'find' && placeholder === 'Ask about a product' ? MODES.find((item) => item.id === mode)?.placeholder : placeholder}
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
          <button className="composer-tool" aria-label="Add a text file" title="Text, Markdown, CSV, JSON or log, up to 12 KB" onClick={() => file.current?.click()} disabled={running}>
            <Icon name="attach" size={16} />
            <span>Attach</span>
          </button>
          {pickAgent && (
          <div className="agent-pick" data-tour="agent-pick">
            <button ref={trigger} className="pill composer-agent" onClick={() => setMenu((v) => !v)} aria-haspopup="listbox" aria-expanded={menu}>
              <AgentMark id={agent.id} size={20} />
              <span className="composer-tag">Agent</span>
              <span className="composer-agent-name">{agent.label}</span>
              <Icon name="chevron" size={13} />
            </button>
            {createPortal(
              <AnimatePresence>
                {menu && (
                  <motion.ul
                    ref={list}
                    className="menu"
                    role="listbox"
                    aria-label="Agent"
                    onKeyDown={onMenuKey}
                    style={place}
                    initial={{ opacity: 0, scale: m.on ? 0.97 : 1 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0 }}
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
                            trigger.current?.focus()
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
              </AnimatePresence>,
              document.body,
            )}
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
      {modes && (
        <div className="composer-modes">
          <div className="k-seg" role="radiogroup" aria-label="What to do" data-tour="mode-slider">
            {MODES.map((item) => (
              <button
                key={item.id}
                type="button"
                role="radio"
                aria-checked={mode === item.id}
                disabled={running}
                onClick={() => { setMode(item.id); field.current?.focus() }}
              >
                {item.label}
              </button>
            ))}
          </div>
          <p className="composer-mode-hint">{selected.hint}</p>
        </div>
      )}
    </div>
  )
}

import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import type { Agent } from '../engine/Engine'
import type { MarketAgent } from '../engine/agents'
import { standingWords } from '../engine/usagemeters'
import { AgentMark } from './AgentMark'
import { Icon } from './Icon'

/** How the agent's standing is drawn: a shape as well as a colour, so the dot is
 *  never the only word-less signal. `working` adds a halo; `setup` is a ring;
 *  `missing` is dashed; `checking` and `example` are hollow. */
export type Standing = 'working' | 'ready' | 'setup' | 'missing' | 'checking' | 'example' | 'none'

export interface AgentStanding {
  status: Standing
  /** The word for it. Every dot and every menu row says this in full. */
  word: string
}

/** One agent's standing in words, from the engine's market read. Working wins
 *  while a research job runs on the agent in use. */
function agentStanding(args: { id: string; inUse: boolean; busy: boolean; live: boolean; market: Map<string, MarketAgent> | null }): AgentStanding {
  if (args.busy && args.inUse) return { status: 'working', word: 'Working now' }
  if (!args.live) return { status: 'example', word: 'Not checked in demo' }
  if (args.id === '') return { status: 'none', word: 'Used when no agent is chosen' }
  if (!args.market) return { status: 'checking', word: 'Checking' }
  const row = args.market.get(args.id)
  if (!row) return { status: 'checking', word: 'Not reported by the engine' }
  const word = standingWords(row.state, row.kind)
  if (row.state === 'ready') return { status: 'ready', word }
  if (row.state === 'not_installed') return { status: 'missing', word }
  return { status: 'setup', word }
}

export interface AgentMenuProps {
  agents: Agent[]
  /** The agent the reader chose as the default; "" is the default agent. */
  preferred: string
  /** A research job is running. */
  busy: boolean
  /** A real engine answers; in demo nothing is checked. */
  live: boolean
  /** The engine's market rows by id, or null until the first read has come back. */
  market: Map<string, MarketAgent> | null
  /** The menu is about to open: the caller may read the market. */
  onOpen: () => void
  onChoose: (id: string) => void
  onVerify: () => void
  onSettings: () => void
  /** The tour's hook on the pill. */
  tour: string
}

/** The agent pill at the top of the window, and the menu it opens. The pill
 *  names the agent that does the research and says its standing in a word. The
 *  menu lists every agent the engine knows, each with its state, marks the one
 *  in use, and ends in two text buttons. Escape closes it and gives the focus
 *  back to the pill; the arrow keys move between agents. */
export function AgentMenu({ agents, preferred, busy, live, market, onOpen, onChoose, onVerify, onSettings, tour }: AgentMenuProps) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const pill = useRef<HTMLButtonElement>(null)
  const rows = useRef<(HTMLButtonElement | null)[]>([])
  const menuId = useId()

  const current = agents.find((agent) => agent.id === preferred)
  const label = current?.label ?? 'Default agent'
  const pillStanding = agentStanding({ id: preferred, inUse: true, busy, live, market })

  // Focus the agent in use when the menu opens, so the arrow keys start there.
  // Runs when the menu opens only: a refresh of the list must not move the focus.
  useEffect(() => {
    if (!open) return
    const at = Math.max(0, agents.findIndex((agent) => agent.id === preferred))
    rows.current[at]?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // A press anywhere outside closes the menu, and leaves the focus where it was pressed.
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])

  const show = () => {
    onOpen()
    setOpen(true)
  }
  const close = (back: boolean) => {
    setOpen(false)
    if (back) pill.current?.focus()
  }
  const choose = (id: string) => {
    onChoose(id)
    close(true)
  }

  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape' && open) {
      event.preventDefault()
      close(true)
    }
  }

  const onPillKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!open && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault()
      show()
    }
  }

  const onListKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const list = rows.current.filter((node): node is HTMLButtonElement => node !== null)
    const count = list.length
    if (count === 0) return
    const at = list.indexOf(document.activeElement as HTMLButtonElement)
    let next = -1
    if (event.key === 'ArrowDown') next = (at + 1) % count
    else if (event.key === 'ArrowUp') next = at <= 0 ? count - 1 : at - 1
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = count - 1
    if (next >= 0) {
      event.preventDefault()
      list[next].focus()
    }
  }

  return (
    <div
      className="agent-menu"
      ref={wrap}
      onKeyDown={onKey}
      onBlur={(event) => {
        // Tabbing out of the menu closes it. A press on something that cannot take
        // focus clears it with no new focus target, and the menu stays open.
        const to = event.relatedTarget as Node | null
        if (open && to && !wrap.current?.contains(to)) setOpen(false)
      }}
    >
      <button
        ref={pill}
        type="button"
        className="strip-agent"
        data-tour={tour}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        title="The agent that does the research. Open to change it."
        onClick={() => (open ? close(true) : show())}
        onKeyDown={onPillKey}
      >
        <span className="agent-dot" data-status={pillStanding.status} role="img" aria-label={pillStanding.word} />
        <AgentMark id={preferred} size={18} state={busy ? 'working' : 'idle'} />
        <span className="strip-agent-name">{label}</span>
        {busy && <span className="strip-agent-busy">Working</span>}
        <Icon name="chevron" size={14} />
      </button>

      {open && (
        <div className="agent-menu-pop" id={menuId}>
          <div role="menu" aria-label="Research agent" className="agent-menu-list" onKeyDown={onListKey}>
            {agents.map((agent, index) => {
              const on = agent.id === preferred
              const standing = agentStanding({ id: agent.id, inUse: on, busy, live, market })
              return (
                <button
                  key={agent.id || 'default'}
                  ref={(node) => {
                    rows.current[index] = node
                  }}
                  type="button"
                  role="menuitemradio"
                  aria-checked={on}
                  tabIndex={-1}
                  className="agent-menu-item"
                  data-on={on}
                  onClick={() => choose(agent.id)}
                >
                  <AgentMark id={agent.id} size={28} state={busy && on ? 'working' : 'idle'} />
                  <span className="agent-menu-text">
                    <strong>{agent.label}</strong>
                    <small data-status={standing.status}>{standing.word}</small>
                  </span>
                  {on && (
                    <span className="agent-menu-in">
                      <Icon name="check" size={14} />
                      <span>In use</span>
                    </span>
                  )}
                </button>
              )
            })}
          </div>
          <div className="agent-menu-foot">
            <button
              type="button"
              className="agent-menu-link"
              onClick={() => {
                setOpen(false)
                onVerify()
              }}
            >
              Verify this agent
            </button>
            <button
              type="button"
              className="agent-menu-link"
              onClick={() => {
                setOpen(false)
                onSettings()
              }}
            >
              Agent settings
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

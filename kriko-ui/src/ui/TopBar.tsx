import { useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import wordSvg from '../assets/wordmark.svg?raw'
import { useEngine } from '../engine/Engine'
import { usePrefs } from '../prefs'
import { useQueue } from '../queue'
import { showDrawer } from './drawerEvents'
import { AgentMark } from './AgentMark'
import { Icon, type IconName } from './Icon'
import { PixelGlyph } from './PixelGlyph'
import { RailChats } from './RailChats'
import { UsagePill } from './UsagePill'

/** The logo files are white. They take the colour of the text instead. */
const ink = (svg: string) => svg.replaceAll('#ffffff', 'currentColor')

export type Screen = 'chat' | 'compare' | 'queue'
export const ORDER: Screen[] = ['chat', 'compare', 'queue']

const ITEMS: { id: Screen; label: string; icon: IconName }[] = [
  { id: 'chat', label: 'Chat', icon: 'chat' },
  { id: 'compare', label: 'Compare', icon: 'compare' },
  { id: 'queue', label: 'Queue', icon: 'queue' },
]

/** The bar across the top. It holds the three places, the chats the reader has
 *  had, a new chat, the agent doing the work and the queue's state. Everything
 *  else opens in the drawer. The window below gets the whole width.
 *
 *  Where the system draws no title bar (Windows, see `ui/TitleBar.tsx`) this row
 *  *is* the window's caption: the three window buttons sit in it and the row
 *  drags the window. Tauri drags only from a press whose target carries
 *  `data-tauri-drag-region`, so the row and its two ends carry it while every
 *  button inside stays a button — the ground between the controls is the handle. */
export function TopBar({
  screen,
  onNavigate,
  onMore,
  onNewChat,
  onOpenChat,
  queueCount,
  attention = 0,
}: {
  screen: Screen
  onNavigate: (s: Screen) => void
  onMore: () => void
  onNewChat: () => void
  onOpenChat: (threadId: string) => void
  queueCount: number
  /** Things that need the reader: a price that fell, a purchase to answer for. */
  attention?: number
}) {
  const { motion: m } = usePrefs()
  const { agents, preferred } = useEngine()
  const { items } = useQueue()
  const agent = agents.find((a) => a.id === preferred)?.label ?? 'Default agent'
  const busy = items.some((i) => i.state === 'researching')
  const done = items.filter((i) => i.state === 'done').length
  const [history, setHistory] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!history) return
    const out = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setHistory(false)
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setHistory(false)
    }
    document.addEventListener('pointerdown', out)
    window.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('pointerdown', out)
      window.removeEventListener('keydown', key)
    }
  }, [history])

  return (
    <header className="topbar" data-tauri-drag-region>
      <div className="topbar-left" data-tauri-drag-region>
        <div className="brand" aria-label="Kriko">
          <span className="logo-word" dangerouslySetInnerHTML={{ __html: ink(wordSvg) }} />
        </div>
        <span className="topbar-slash" aria-hidden="true">
          /
        </span>
        <button className="topbar-agent" onClick={() => showDrawer('agents')} title="The agent that does the research. Open to change it." data-tour="agent-pill">
          <AgentMark id={preferred} size={18} state={busy ? 'working' : 'idle'} />
          <span className="topbar-agent-name">{agent}</span>
          <Icon name="chevron" size={14} />
        </button>
      </div>

      <nav className="topbar-nav" aria-label="Main">
        {ITEMS.map((item) => {
          const on = item.id === screen
          return (
            <button key={item.id} className="topbar-tab" data-tour={`nav-${item.id}`} data-on={on} onClick={() => onNavigate(item.id)} aria-current={on ? 'page' : undefined}>
              {on && <motion.span layoutId="topbar-active" className="topbar-active" transition={m.tx.spring} />}
              <Icon name={item.icon} size={17} />
              <span className="topbar-label">{item.label}</span>
              {item.id === 'queue' && queueCount > 0 && <span className="badge mono">{queueCount}</span>}
            </button>
          )
        })}
        <div className="topbar-history" ref={box}>
          <button className="topbar-tab" data-on={history || undefined} onClick={() => setHistory((v) => !v)} aria-expanded={history} aria-haspopup="dialog" data-tour="history">
            <Icon name="clock" size={17} />
            <span className="topbar-label">History</span>
          </button>
          {history && (
            <div className="topbar-pop" role="dialog" aria-label="Your chats">
              <RailChats
                onOpen={(id) => {
                  setHistory(false)
                  onOpenChat(id)
                }}
              />
            </div>
          )}
        </div>
        <button className="topbar-tab topbar-new" data-tour="new-chat" onClick={onNewChat}>
          <PixelGlyph size={15} active={false} />
          <span className="topbar-label">New chat</span>
        </button>
      </nav>

      <div className="topbar-right" data-tauri-drag-region>
        <UsagePill />
        {items.length > 0 && (
          <button className="topbar-queue" onClick={() => onNavigate('queue')} aria-label={`Queue, ${done} of ${items.length} done`} title="Queue">
            <PixelGlyph size={16} active={busy} />
            <span className="mono">
              {done} of {items.length}
            </span>
          </button>
        )}
        <button className="topbar-tab topbar-settings" data-tour="settings" onClick={() => showDrawer('settings')} aria-label="Settings" title="Settings: agents, keys, search, look">
          <Icon name="gear" size={21} />
          <span className="topbar-label">Settings</span>
        </button>
        <button className="icon-btn" data-tour="more" onClick={onMore} aria-label="More" title="More">
          <Icon name="more" size={19} />
          {attention > 0 && (
            <span className="topbar-dot mono" aria-label={`${attention} waiting in For you`}>
              {attention}
            </span>
          )}
        </button>
      </div>
    </header>
  )
}

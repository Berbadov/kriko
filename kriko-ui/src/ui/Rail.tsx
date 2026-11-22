import { useEngine } from '../engine/Engine'
import { useAppUpdate } from '../engine/appupdate'
import { useQueue } from '../queue'
import wordSvg from '../assets/wordmark.svg?raw'
import { showDrawer, type Screen } from './drawerEvents'
import { AgentMark } from './AgentMark'
import { Icon, type IconName } from './Icon'
import { PixelGlyph } from './PixelGlyph'
import { TitleBar } from './TitleBar'
import { UsagePill } from './UsagePill'

/** The logo files are white. They take the colour of the text instead. */
const ink = (svg: string) => svg.replaceAll('#ffffff', 'currentColor')

/** The rail, top to bottom. Each group is ruled off from the next by a hairline. */
const GROUPS: { name: string; tour?: string; items: { id: Screen; label: string; icon: IconName; tour?: string }[] }[] = [
  {
    name: 'Check',
    items: [
      { id: 'chat', label: 'Ask', icon: 'chat', tour: 'nav-chat' },
      { id: 'compare', label: 'Compare', icon: 'compare', tour: 'nav-compare' },
      { id: 'queue', label: 'Queue', icon: 'queue', tour: 'nav-queue' },
      { id: 'history', label: 'History', icon: 'clock', tour: 'history' },
    ],
  },
  {
    name: 'Procure',
    items: [
      { id: 'estimate', label: 'Procurement', icon: 'gauge', tour: 'nav-estimate' },
      { id: 'prices', label: 'Prices', icon: 'coins', tour: 'nav-prices' },
    ],
  },
  {
    name: 'Library',
    tour: 'library',
    items: [
      { id: 'catalogs', label: 'Catalogs', icon: 'book' },
      { id: 'sites', label: 'Sites', icon: 'globe' },
      { id: 'foryou', label: 'For you', icon: 'star' },
    ],
  },
]

/** The rail, labelled and grouped. Under 900px of window it keeps only the icons;
 *  each word stays in the page for the screen reader and as a tooltip. */
export function Rail({
  screen,
  onNavigate,
  onNewChat,
  queueCount,
  attention,
}: {
  screen: Screen
  onNavigate: (s: Screen) => void
  onNewChat: () => void
  queueCount: number
  /** Things that need the reader: a price that fell, a purchase to answer for. */
  attention: number
}) {
  const { release } = useAppUpdate()
  const counts: Partial<Record<Screen, number>> = { queue: queueCount, foryou: attention }
  const settingsOn = screen === 'settings'

  return (
    <aside className="lrail" aria-label="Kriko">
      <div className="lrail-top" data-tauri-drag-region>
        <div className="brand lrail-brand" data-tauri-drag-region>
          <span className="logo-word" dangerouslySetInnerHTML={{ __html: ink(wordSvg) }} />
        </div>
        <button type="button" className="lrail-new" data-tour="new-chat" onClick={onNewChat} title="New chat">
          <Icon name="plus" size={16} />
          <span className="lrail-label">New chat</span>
        </button>
      </div>

      <nav className="lrail-nav" aria-label="Main">
        {GROUPS.map((group) => (
          <div key={group.name} className="lrail-group" role="group" aria-label={group.name} data-tour={group.tour}>
            {group.items.map((item) => {
              const on = item.id === screen
              const count = counts[item.id] ?? 0
              return (
                <button
                  key={item.id}
                  type="button"
                  className="lrail-item"
                  data-on={on}
                  data-tour={item.tour}
                  aria-current={on ? 'page' : undefined}
                  title={item.label}
                  onClick={() => onNavigate(item.id)}
                >
                  <Icon name={item.icon} size={18} />
                  <span className="lrail-label">{item.label}</span>
                  {count > 0 && (
                    <span className="lrail-count mono" aria-label={item.id === 'queue' ? `${count} in queue` : `${count} waiting`}>
                      {count}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        ))}
      </nav>

      <div className="lrail-foot">
        <button
          type="button"
          className="lrail-item"
          data-on={settingsOn}
          data-tour="settings"
          aria-current={settingsOn ? 'page' : undefined}
          title="Settings"
          onClick={() => onNavigate('settings')}
        >
          <Icon name="gear" size={18} />
          <span className="lrail-label">Settings</span>
          {release && <span className="lrail-dot" role="img" aria-label="An app update is ready" />}
        </button>
      </div>
    </aside>
  )
}

/** The slim strip across the top of the content column. It holds the agent that
 *  does the research, the usage, the queue's state and, on Windows, the window's
 *  own buttons. Its empty ground drags the window. */
export function TopStrip({ onNavigate }: { onNavigate: (s: Screen) => void }) {
  const { agents, preferred } = useEngine()
  const { items } = useQueue()
  const agent = agents.find((a) => a.id === preferred)?.label ?? 'Default agent'
  const busy = items.some((i) => i.state === 'researching')
  const done = items.filter((i) => i.state === 'done').length

  return (
    <header className="strip" data-tauri-drag-region>
      <button
        type="button"
        className="strip-agent"
        onClick={() => showDrawer('agents')}
        title="The agent that does the research. Open to change it."
        data-tour="agent-pill"
      >
        <AgentMark id={preferred} size={18} state={busy ? 'working' : 'idle'} />
        <span className="strip-agent-name">{agent}</span>
        <Icon name="chevron" size={14} />
      </button>

      <div className="strip-drag" data-tauri-drag-region />

      <div className="strip-right">
        <UsagePill />
        {items.length > 0 && (
          <button type="button" className="strip-queue" onClick={() => onNavigate('queue')} aria-label={`Queue, ${done} of ${items.length} done`} title="Queue">
            <PixelGlyph size={16} active={busy} />
            <span className="mono">
              {done} of {items.length} done
            </span>
          </button>
        )}
        <TitleBar />
      </div>
    </header>
  )
}

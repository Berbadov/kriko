import { AnimatePresence, motion } from 'motion/react'
import markSvg from '../assets/mark.svg?raw'
import wordSvg from '../assets/wordmark.svg?raw'
import { usePrefs } from '../prefs'
import { Icon, type IconName } from './Icon'
import { QueueCard } from './QueueCard'
import { RailChats } from './RailChats'

/** The logo files are white. They take the colour of the text instead. */
const ink = (svg: string) => svg.replaceAll('#ffffff', 'currentColor')

export type Screen = 'chat' | 'compare' | 'queue'
export const ORDER: Screen[] = ['chat', 'compare', 'queue']

const ITEMS: { id: Screen; label: string; icon: IconName }[] = [
  { id: 'chat', label: 'Chat', icon: 'chat' },
  { id: 'compare', label: 'Compare', icon: 'compare' },
  { id: 'queue', label: 'Queue', icon: 'queue' },
]

/** The rail holds three places. Everything else opens in the drawer. */
export function Rail({
  screen,
  onNavigate,
  collapsed,
  onCollapse,
  onMore,
  onNewChat,
  onOpenChat,
  queueCount,
}: {
  screen: Screen
  onNavigate: (s: Screen) => void
  collapsed: boolean
  onCollapse: () => void
  onMore: () => void
  onNewChat: () => void
  onOpenChat: (threadId: string) => void
  queueCount: number
}) {
  const { motion: m } = usePrefs()
  return (
    <motion.aside
      className="rail"
      data-collapsed={collapsed}
      initial={false}
      animate={{ width: collapsed ? 68 : 244 }}
      transition={m.tx.spring}
    >
      <div className="rail-top">
        <div className="brand" aria-label="Kriko">
          <AnimatePresence mode="wait" initial={false}>
            {collapsed ? (
              <motion.span key="mark" className="logo-mark" dangerouslySetInnerHTML={{ __html: ink(markSvg) }} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={m.tx.quick} />
            ) : (
              <motion.span key="word" className="logo-word" dangerouslySetInnerHTML={{ __html: ink(wordSvg) }} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={m.tx.quick} />
            )}
          </AnimatePresence>
        </div>
        <button className="icon-btn" onClick={onCollapse} aria-label={collapsed ? 'Open the rail' : 'Close the rail'}>
          <motion.span style={{ display: 'grid' }} animate={{ rotate: collapsed ? 180 : 0 }} transition={m.tx.spring}>
            <Icon name="collapse" />
          </motion.span>
        </button>
      </div>

      <button className="rail-new" data-tour="new-chat" onClick={onNewChat} title={collapsed ? 'New chat' : undefined}>
        <Icon name="plus" size={18} />
        <span className="rail-label">New chat</span>
      </button>

      <nav className="rail-nav" aria-label="Main">
        {ITEMS.map((item) => {
          const on = item.id === screen
          return (
            <button key={item.id} className="rail-item" data-tour={`nav-${item.id}`} data-on={on} onClick={() => onNavigate(item.id)} title={collapsed ? item.label : undefined} aria-current={on ? 'page' : undefined}>
              {on && <motion.span layoutId="rail-active" className="rail-active" transition={m.tx.spring} />}
              <Icon name={item.icon} size={19} />
              <span className="rail-label">{item.label}</span>
              {item.id === 'queue' && queueCount > 0 && <span className="badge mono">{queueCount}</span>}
            </button>
          )
        })}
      </nav>

      {!collapsed && <RailChats onOpen={onOpenChat} />}

      <div className="rail-bottom">
        <QueueCard screen={screen} collapsed={collapsed} onOpen={() => onNavigate('queue')} />
        <button className="rail-item" data-tour="more" onClick={onMore} title={collapsed ? 'More' : undefined}>
          <Icon name="more" size={19} />
          <span className="rail-label">More</span>
        </button>
      </div>
    </motion.aside>
  )
}

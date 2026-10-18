import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { usePrefs } from '../prefs'
import { useEngine } from '../engine/Engine'
import { useQueue, type QueueItem } from '../queue'
import { PixelBar } from './controls'
import { Icon } from './Icon'
import { PixelGlyph } from './PixelGlyph'
import type { Screen } from './Rail'

/** The queue on every screen. It sits at the foot of the rail and opens into a list.
 *  A collapsed rail shows only the glyph. */
export function QueueCard({ screen, onOpen, collapsed }: { screen: Screen; onOpen: () => void; collapsed: boolean }) {
  const { motion: m } = usePrefs()
  const { items, active, running, start, stop } = useQueue()
  const { mode } = useEngine()
  const canStart = items.some((i) => i.state === 'waiting' || i.state === 'paused')
  const [open, setOpen] = useState(false)
  const show = screen !== 'queue' && items.length > 0
  const busy = items.some((i) => i.state === 'researching')
  const done = items.filter((i) => i.state === 'done').length
  const overall = items.length ? items.reduce((sum, i) => sum + i.progress, 0) / items.length : 0

  if (collapsed) {
    return show ? (
      <button className="icon-btn qc-mini" onClick={onOpen} aria-label={`Queue, ${done} of ${items.length} done`} title="Queue">
        <PixelGlyph size={18} active={busy} />
      </button>
    ) : null
  }

  return (
    <AnimatePresence>
      {show && (
        <motion.aside
          className="queue-card"
          aria-label="Queue"
          initial={{ opacity: 0, y: m.d(16) }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: m.d(10) }}
          transition={m.tx.spring}
        >
          <div className="qc-head">
            <button className="qc-title" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
              <PixelGlyph size={16} active={busy} />
              <strong>Queue</strong>
              <span className="qc-count mono">
                {done} of {items.length}
              </span>
              <motion.span style={{ display: 'grid', marginLeft: 'auto' }} animate={{ rotate: open ? 180 : 0 }} transition={m.tx.spring}>
                <Icon name="chevron" size={16} />
              </motion.span>
            </button>
            {mode === 'live' && (
              <button className="icon-btn sm" onClick={running ? stop : start} disabled={!running && !canStart} aria-label={running ? 'Stop the research' : 'Start the research'}>
                <Icon name={running ? 'stop' : 'play'} size={14} />
              </button>
            )}
            <button className="icon-btn sm" onClick={onOpen} aria-label="Open the queue">
              <Icon name="external" size={15} />
            </button>
          </div>
          {!open && <PixelBar value={overall} active={busy} cells={28} />}
          <AnimatePresence initial={false}>
            {open && (
              <motion.ul
                className="qc-list"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={m.tx.soft}
              >
                {items.slice(0, 4).map((item) => (
                  <QueueRow key={item.id} item={item} />
                ))}
              </motion.ul>
            )}
          </AnimatePresence>
          <span className="sr" aria-live="polite">
            {active} in the queue
          </span>
        </motion.aside>
      )}
    </AnimatePresence>
  )
}

export function QueueRow({ item, wide = false }: { item: QueueItem; wide?: boolean }) {
  const { toggle, cancel } = useQueue()
  const canToggle = item.state === 'researching' || item.state === 'paused'
  return (
    <li className="qc-row" data-wide={wide} data-state={item.state}>
      <div className="qc-main">
        <span className="qc-name">{item.name}</span>
        <span className="qc-line">{wide ? `${item.agent} · ${item.line}` : item.line}</span>
        <PixelBar value={item.progress} active={item.state === 'researching'} cells={wide ? 36 : 22} />
      </div>
      <div className="qc-actions">
        {canToggle && (
          <button className="icon-btn sm" onClick={() => toggle(item.id)} aria-label={item.state === 'paused' ? 'Resume' : 'Pause'}>
            <Icon name={item.state === 'paused' ? 'play' : 'pause'} size={14} />
          </button>
        )}
        <button className="icon-btn sm" onClick={() => cancel(item.id)} aria-label="Remove">
          <Icon name="x" size={14} />
        </button>
      </div>
    </li>
  )
}

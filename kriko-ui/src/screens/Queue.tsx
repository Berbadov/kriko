import type { CSSProperties } from 'react'
import { Reorder } from 'motion/react'
import { useEngine } from '../engine/Engine'
import { useQueue } from '../queue'
import { Icon } from '../ui/Icon'
import { QueueRow } from '../ui/QueueCard'

/** Every queued product. Drag a row to change the order. */
export function QueueScreen() {
  const { items, setItems, running, start, stop } = useQueue()
  const { mode } = useEngine()
  const waiting = items.some((i) => i.state === 'waiting' || i.state === 'paused')
  return (
    <section className="queue-page">
      <header className="page-head rise" style={{ '--i': 0 } as CSSProperties}>
        <h1>Queue</h1>
        <span className="mono muted">{items.filter((i) => i.state === 'done').length} of {items.length} done</span>
        {mode === 'live' && (
          <div className="head-tools">
            {running ? (
              <button className="btn" onClick={stop}>
                <Icon name="stop" size={14} /> Stop
              </button>
            ) : (
              <button className="btn primary" onClick={start} disabled={!waiting}>
                <Icon name="play" size={14} /> Start
              </button>
            )}
          </div>
        )}
      </header>
      <Reorder.Group as="ul" axis="y" values={items} onReorder={setItems} className="queue-list rise" style={{ '--i': 1 } as CSSProperties}>
        {items.map((item) => (
          <Reorder.Item as="li" key={item.id} value={item} className="queue-item" whileDrag={{ scale: 1.015 }}>
            <ul>
              <QueueRow item={item} wide />
            </ul>
          </Reorder.Item>
        ))}
      </Reorder.Group>
    </section>
  )
}

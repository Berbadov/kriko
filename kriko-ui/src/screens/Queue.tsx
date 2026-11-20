import { Reorder } from 'motion/react'
import { useEngine } from '../engine/Engine'
import { useQueue, type QueueItem } from '../queue'
import { QueueRow } from '../ui/QueueCard'

/** The captions, in the order the reader reads them. */
type Group = 'Running' | 'Waiting' | 'Done' | 'Needs a look'
const GROUPS: Group[] = ['Running', 'Waiting', 'Done', 'Needs a look']

/** A product that was passed over (failed or interrupted) waits with its reason in `note`. */
function groupOf(item: QueueItem): Group {
  if (item.state === 'researching') return 'Running'
  if (item.state === 'done') return 'Done'
  if ((item.state === 'waiting' || item.state === 'paused') && item.note) return 'Needs a look'
  return 'Waiting'
}

/** Every queued product, in four captioned groups. Drag a row within its group to change the order. */
export function QueueScreen({ onOpen }: { onOpen?: (lookupId: string) => void }) {
  const { items, setItems, running, start, stop } = useQueue()
  const { mode } = useEngine()
  const waiting = items.filter((i) => groupOf(i) === 'Waiting').length
  const researching = items.filter((i) => i.state === 'researching').length
  const done = items.filter((i) => i.state === 'done').length
  const canStart = items.some((i) => i.state === 'waiting' || i.state === 'paused')

  /** A finished row opens its product. The shell hands the link to the app's own route when no handler is given. */
  const open = (lookupId: string) => {
    if (onOpen) onOpen(lookupId)
    else window.location.hash = `#/result/${encodeURIComponent(lookupId)}`
  }
  const openIdOf = (item: QueueItem) => item.lookupId ?? (mode === 'demo' ? `demo:${item.name}` : undefined)

  /** Reorders one group. The rows of the other groups keep their places in the full queue. */
  const reorder = (group: Group) => (next: QueueItem[]) =>
    setItems((list) => {
      const order = next.map((i) => i.id)
      const current = new Map(list.map((i) => [i.id, i]))
      const slots = list.flatMap((item, index) => (groupOf(item) === group ? [index] : []))
      const copy = [...list]
      slots.forEach((slot, n) => {
        copy[slot] = current.get(order[n]) ?? copy[slot]
      })
      return copy
    })

  return (
    <section className="k-screen" aria-label="Queue">
      <header className="k-head">
        <h1 className="k-title">Queue</h1>
        {mode === 'live' && (
          <div className="k-head-actions">
            {running ? (
              <button type="button" className="k-btn" onClick={stop}>
                Stop
              </button>
            ) : (
              <button type="button" className="k-btn" data-kind="primary" onClick={start} disabled={!canStart}>
                Start
              </button>
            )}
          </div>
        )}
      </header>

      {!items.length ? (
        <section className="k-empty work-empty">
          <strong>The queue is empty</strong>
          <p>
            The queue holds the products Kriko is researching or will research next. Add one from Ask, or from a listing in your browser, and it waits here until its research runs.
          </p>
          <button type="button" className="k-btn" data-kind="primary" onClick={() => window.dispatchEvent(new CustomEvent('kriko:navigate', { detail: { screen: 'chat' } }))}>
            Ask about a product
          </button>
        </section>
      ) : (
        <>
          <div className="k-kpis" aria-label="Queue summary">
            <div className="k-kpi">
              <span className="k-kpi-value">{researching}</span>
              <span className="k-kpi-label">Running</span>
            </div>
            <div className="k-kpi">
              <span className="k-kpi-value">{waiting}</span>
              <span className="k-kpi-label">Waiting</span>
            </div>
            <div className="k-kpi">
              <span className="k-kpi-value">{done}</span>
              <span className="k-kpi-label">Done</span>
            </div>
          </div>

          {GROUPS.map((group) => {
            const rows = items.filter((i) => groupOf(i) === group)
            if (!rows.length) return null
            return (
              <section key={group} className="k-group" aria-label={group}>
                <h2 className="k-caption">{group}</h2>
                <div className="k-card">
                  <Reorder.Group as="ul" axis="y" values={rows} onReorder={reorder(group)} className="k-list">
                    {rows.map((item) => (
                      <Reorder.Item key={item.id} as="li" value={item} whileDrag={{ scale: 1.01 }}>
                        <QueueRow item={item} openId={openIdOf(item)} onOpen={open} />
                      </Reorder.Item>
                    ))}
                  </Reorder.Group>
                </div>
              </section>
            )
          })}
        </>
      )}
    </section>
  )
}

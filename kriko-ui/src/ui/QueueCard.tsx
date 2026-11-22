import { useState, type CSSProperties } from 'react'
import { useQueue, type QueueItem } from '../queue'
import { stepOf } from '../engine/steps'
import { AGENT_STEPS } from './controls'
import { Elapsed } from './text'
import { ProductGlyph } from './ProductGlyph'
import { glyphFor } from './productGlyphs'
import { ReportButton } from './ReportButton'

/** How long a row has been running. The queue keeps no times, so this counts from when the row
 *  entered the Running group: a row is remounted when it moves between groups. */
function Running() {
  const [since] = useState(() => Date.now())
  return <Elapsed since={since} running />
}

/** The four steps as a compact segmented line, filled with the brand colour. */
export function QueueSteps({ value, state }: { value: number; state: QueueItem['state'] }) {
  const count = AGENT_STEPS.length
  const { at, within } = stepOf(value, state, count)
  const word = state === 'done' ? 'Done' : state === 'waiting' ? 'Waiting' : `Step ${at + 1} of ${count}: ${AGENT_STEPS[at]}`
  return (
    <div className="work-steps-line" role="img" aria-label={word}>
      <span className="work-steps" aria-hidden="true">
        {AGENT_STEPS.map((label, index) => {
          const fill = index < at ? 1 : index === at ? within : 0
          return <i key={label} className="work-step" style={{ '--fill': `${Math.round(fill * 100)}%` } as CSSProperties} />
        })}
      </span>
      <span className="work-steps-word">{word}</span>
    </div>
  )
}

/** One queued product, as a row of its card. Its words are the state: what it is
 *  doing, which agent, how long, and the one or two presses that apply to it. */
export function QueueRow({ item, openId, onOpen }: { item: QueueItem; openId?: string; onOpen?: (lookupId: string) => void }) {
  const { toggle, cancel } = useQueue()
  const failed = (item.state === 'waiting' || item.state === 'paused') && !!item.note
  const note = failed ? item.note! : `${item.agent} · ${item.line}`
  return (
    <div className="k-row work-queue" data-state={item.state} data-failed={failed || undefined}>
      {glyphFor(item.name) ? (
        <span className="k-row-icon">
          <ProductGlyph name={item.name} size={22} />
        </span>
      ) : (
        <span className="work-slot" aria-hidden="true" />
      )}
      <div className="k-row-main">
        <span className="k-row-title">{item.name}</span>
        <span className="k-row-note">{note}</span>
        {!failed && <QueueSteps value={item.progress} state={item.state} />}
        {failed && item.jobId && <ReportButton jobId={item.jobId} note={item.note!} />}
      </div>
      {item.state === 'researching' && (
        <span className="k-row-value work-elapsed" aria-label="Elapsed">
          <Running />
        </span>
      )}
      <div className="k-row-control work-queue-actions">
        {item.state === 'researching' && (
          <button type="button" className="k-btn" data-size="sm" onClick={() => toggle(item.id)} aria-label={`Stop ${item.name}`}>
            Stop
          </button>
        )}
        {item.state === 'paused' && (
          <button type="button" className="k-btn" data-size="sm" onClick={() => toggle(item.id)} aria-label={`Resume ${item.name}`}>
            Resume
          </button>
        )}
        {failed && (
          <button type="button" className="k-btn" data-size="sm" onClick={() => toggle(item.id)} aria-label={`Retry ${item.name}`}>
            Retry
          </button>
        )}
        {item.state === 'done' && openId && onOpen && (
          <button type="button" className="k-btn" data-size="sm" data-kind="quiet" onClick={() => onOpen(openId)} aria-label={`Open ${item.name}`}>
            Open
          </button>
        )}
        <button type="button" className="k-btn" data-size="sm" data-kind="quiet" onClick={() => cancel(item.id)} aria-label={`Remove ${item.name}`}>
          Remove
        </button>
      </div>
    </div>
  )
}

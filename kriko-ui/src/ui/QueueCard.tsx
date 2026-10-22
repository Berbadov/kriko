import { useQueue, type QueueItem } from '../queue'
import { AgentSteps } from './controls'
import { Icon } from './Icon'

export function QueueRow({ item, wide = false }: { item: QueueItem; wide?: boolean }) {
  const { toggle, cancel } = useQueue()
  const canToggle = item.state === 'researching' || item.state === 'paused'
  return (
    <li className="qc-row" data-wide={wide} data-state={item.state}>
      <div className="qc-main">
        <span className="qc-name">{item.name}</span>
        <span className="qc-line">{wide ? `${item.agent} · ${item.line}` : item.line}</span>
        <AgentSteps value={item.progress} state={item.state} labels={wide} />
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

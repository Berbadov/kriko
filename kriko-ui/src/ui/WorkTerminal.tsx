import { useEffect, useMemo, useRef } from 'react'
import type { ApiJob } from '../engine/api'
import { WORK_LINES_VISIBLE, markOf, waitReason, workLines, type WorkReading } from './workfeed'

/** The real work of one job, in the app: the hosts it read, what it searched,
 *  and the engine's own line about why the reader is still waiting.
 *
 *  It draws only what the job reported. A job with no feed yet shows the stage
 *  the interface is actually in, never a made-up step or a percentage. The
 *  newest line is the one that types; older lines fade, and the reader's
 *  reduced-motion setting stills it all. */

export interface WorkTerminalProps extends WorkReading {
  /** The job being followed: its feed, log, state and message. */
  job?: ApiJob | null
  /** What this work is for, read by a screen reader. */
  title?: string
  compact?: boolean
}

export function WorkTerminal({ job, title, compact = false, ...reading }: WorkTerminalProps) {
  const merged = useMemo<WorkReading>(() => ({
    state: reading.state ?? job?.state,
    message: reading.message ?? job?.message,
    stage: reading.stage,
    agent: reading.agent,
    feed: reading.feed ?? job?.feed,
    log: reading.log ?? job?.log,
    steps: reading.steps ?? job?.result?.steps,
    activity: reading.activity ?? job?.result?.activity,
  }), [reading.state, reading.message, reading.stage, reading.agent, reading.feed, reading.log, reading.steps, reading.activity, job])

  const lines = useMemo(() => workLines(merged), [merged])
  const reason = useMemo(() => waitReason(merged), [merged])
  const shown = lines.slice(-WORK_LINES_VISIBLE)
  const box = useRef<HTMLDivElement>(null)
  const last = lines[lines.length - 1]

  // One scroll per reading, not per frame: the 700 ms poll is the only thing
  // that grows this list.
  useEffect(() => {
    const element = box.current
    if (element) element.scrollTop = element.scrollHeight
  }, [last?.id, shown.length])

  return (
    <section
      className="work-terminal"
      data-compact={compact || undefined}
      data-state={merged.state || undefined}
      aria-label={title ? `${title}: research activity` : 'Research activity'}
    >
      <header className="wt-head">
        <span className="wt-dot" aria-hidden="true" />
        <p className="wt-reason" role="status" aria-live="polite" aria-atomic="true">{reason}</p>
      </header>
      <div className="wt-lines" ref={box} aria-hidden="true">
        {shown.length ? (
          shown.map((line, index) => (
            <div className="wt-line" key={line.id} data-kind={line.kind} data-new={index === shown.length - 1 || undefined} data-old={index < shown.length - 2 || undefined}>
              <span className="wt-mark">{markOf(line.kind)}</span>
              <span className="wt-text">{line.text}</span>
            </div>
          ))
        ) : (
          <div className="wt-line wt-quiet" data-new="">
            <span className="wt-mark">{markOf('note')}</span>
            <span className="wt-text">{reason}</span>
          </div>
        )}
      </div>
    </section>
  )
}

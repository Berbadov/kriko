import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useFocus } from '../chat/focus'
import { pageKey } from '../chat/view'
import { usePrefs } from '../prefs'
import { Icon } from '../ui/Icon'
import { PixelGlyph } from '../ui/PixelGlyph'
import { Elapsed, Fold, Shimmer, WordStream, count, formatSeconds } from '../ui/text'
import type { Row, Run } from './run'

/** The live record of one run. A run opens it and it stays open when the run
 *  ends, so the answer does not move under the reader at the moment it is
 *  finished. The reader folds it, or a turn from the thread starts folded. */

function useOpen(auto: boolean) {
  const [chosen, setChosen] = useState<boolean | null>(null)
  return [chosen ?? auto, () => setChosen(!(chosen ?? auto))] as const
}

export function Timeline({ run, historical = false }: { run: Run; historical?: boolean }) {
  const running = run.status === 'running'
  const [open, toggle] = useOpen(!historical)
  const label = running ? 'Research' : run.status === 'done' ? 'Done' : run.status === 'failed' ? 'Failed' : 'Stopped'
  const total = (run.endedAt ?? run.startedAt) - run.startedAt
  const measured = run.rows.flatMap((row) => (row.kind === 'event' || row.kind === 'tool') && row.counts?.pagesRead !== undefined ? [row.counts] : [])
  const pageReads = measured.reduce((count, item) => count + (item.pagesRead ?? 0), 0)

  return (
    <section className="timeline" aria-label="Research activity">
      <button className="tl-head" onClick={toggle} aria-expanded={open}>
        <PixelGlyph size={16} active={running} />
        <span className="tl-label">
          <Shimmer active={running}>{historical ? 'Run details' : label}</Shimmer>
        </span>
        {measured.length > 0 && <span className="mono muted">{pageReads} page {pageReads === 1 ? 'read' : 'reads'}</span>}
        {!historical && <span className="tl-time">
          <Elapsed since={run.startedAt} running={running} final={total} />
        </span>}
        <span className="tl-chev" data-open={open}>
          <Icon name="chevron" size={16} />
        </span>
      </button>
      <Fold open={open}>
        <div className="tl-body">
          <AnimatePresence initial={false}>
            {run.rows.map((row) => (
              <RowView key={row.id} row={row} />
            ))}
          </AnimatePresence>
        </div>
      </Fold>
    </section>
  )
}

function RowView({ row }: { row: Row }) {
  const { motion: m } = usePrefs()
  return (
    <motion.div
      className="tl-row"
      initial={{ opacity: 0, y: m.d(8) }}
      animate={{ opacity: 1, y: 0 }}
      transition={m.tx.soft}
    >
      {row.kind === 'thought' && <Thought row={row} />}
      {row.kind === 'tool' && <Tool row={row} />}
      {row.kind === 'event' && <Event row={row} />}
      {row.kind === 'plan' && <Plan row={row} />}
    </motion.div>
  )
}

function Thought({ row }: { row: Extract<Row, { kind: 'thought' }> }) {
  const [open, toggle] = useOpen(!row.done)
  return (
    <div className="thought">
      <button className="row-head" onClick={toggle} aria-expanded={open}>
        <Icon name="spark" size={15} />
        <span>Thoughts</span>
        <span className="tl-chev" data-open={open}>
          <Icon name="chevron" size={14} />
        </span>
      </button>
      <Fold open={open}>
        <p className="thought-text">
          <WordStream text={row.text} live={!row.done} />
        </p>
      </Fold>
    </div>
  )
}

function Tool({ row }: { row: Extract<Row, { kind: 'tool' }> }) {
  const running = row.ms === undefined
  const counts = [
    row.counts?.searchResults === undefined ? '' : count(row.counts.searchResults, 'search result'),
    row.counts?.pagesAttempted === undefined ? '' : `${count(row.counts.pagesAttempted, 'page')} attempted`,
    row.counts?.pagesRead === undefined ? '' : `${count(row.counts.pagesRead, 'page')} read`,
  ].filter(Boolean)
  const source = safeHttpUrl(row.url)
  return (
    <div className="tool">
      <span className="tool-dot" data-running={running} data-failed={row.failed}>
        {running ? <PixelGlyph size={14} /> : <Icon name={row.failed ? 'x' : 'check'} size={14} />}
      </span>
      <span className="tool-name">{row.name}</span>
      <span className="tool-detail">
        <span>{row.detail}</span>
        {source && <a className="tool-url" href={source} target="_blank" rel="noreferrer">{row.url}</a>}
        {counts.length > 0 && <span className="tool-counts">{counts.join(' · ')}</span>}
      </span>
      <span className="tool-time mono">
        {running ? <Elapsed since={row.startedAt} running /> : formatSeconds((row.ms ?? 0) / 1000)}
      </span>
    </div>
  )
}

function safeHttpUrl(value?: string) {
  if (!value) return undefined
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : undefined
  } catch {
    return undefined
  }
}

function Event({ row }: { row: Extract<Row, { kind: 'event' }> }) {
  const source = safeHttpUrl(row.sourceUrl)
  const focus = useFocus()
  const key = source ? pageKey(source) : undefined
  /** A feed line that is a source carries the address as its text; print it once. */
  const sameUrl = !!source && row.text.trim() === (row.sourceUrl ?? '').trim()
  const counts = [
    row.counts?.searchResults === undefined ? '' : count(row.counts.searchResults, 'search result'),
    row.counts?.pagesAttempted === undefined ? '' : `${count(row.counts.pagesAttempted, 'page')} attempted`,
    row.counts?.pagesRead === undefined ? '' : `${count(row.counts.pagesRead, 'page')} read`,
  ].filter(Boolean)
  return (
    <div
      className="run-event"
      data-level={row.level ?? 'info'}
      data-focus-key={key}
      data-lit={(key && focus.key === key) || undefined}
      onClick={key ? (event) => !(event.target as HTMLElement).closest('a') && focus.select(key, 'thread') : undefined}
    >
      {row.stage && <span className="run-event-stage">{row.stage}</span>}
      {!sameUrl && <span>{row.text}</span>}
      {source && <a className="run-event-url" href={source} target="_blank" rel="noreferrer">{row.sourceUrl}</a>}
      {counts.length > 0 && <span className="tool-counts">{counts.join(' · ')}</span>}
    </div>
  )
}

function Plan({ row }: { row: Extract<Row, { kind: 'plan' }> }) {
  const { motion: m } = usePrefs()
  return (
    <div className="plan">
      <div className="row-head static">
        <Icon name="queue" size={15} />
        <span>Plan · {count(row.steps.length, 'step')}</span>
      </div>
      <ul>
        {row.steps.map((step) => (
          <li key={step.label} data-state={step.state}>
            <span className="plan-mark">
              <AnimatePresence initial={false}>
                {step.state === 'done' && (
                  <motion.span
                    key="check"
                    initial={{ scale: m.on ? 0.4 : 1, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={m.tx.spring}
                  >
                    <Icon name="check" size={12} />
                  </motion.span>
                )}
              </AnimatePresence>
              {step.state === 'active' && <PixelGlyph size={12} />}
            </span>
            <span>{step.label}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** The floating pill that names the step in progress. */
export function StepPill({ run }: { run: Run }) {
  const { motion: m } = usePrefs()
  const plan = run.rows.find((r) => r.kind === 'plan')
  const total = plan?.kind === 'plan' ? plan.steps.length : 0
  const show = run.status === 'running' && total > 0
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className="step-pill"
          initial={{ opacity: 0, y: m.d(10), scale: m.on ? 0.96 : 1 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: m.d(6) }}
          transition={m.tx.spring}
        >
          <PixelGlyph size={14} />
          <span>
            Step {run.step + 1} of {total}
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

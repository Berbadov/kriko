import { useEffect, useRef, useState, type ReactNode } from 'react'
import { formatSeconds } from './format'

export { count, formatSeconds } from './format'

/** Text that sweeps light across it while work runs. */
export function Shimmer({ children, active = true }: { children: ReactNode; active?: boolean }) {
  return <span className={active ? 'shimmer' : undefined}>{children}</span>
}

/** Streamed words, for the thoughts in the timeline. Each new word rises out
 *  of a blur. While the text still grows (`live`), the last few words stay a
 *  little blurred. A word already on the screen never replays, because the key
 *  is its position. */
export function WordStream({ text, live = false }: { text: string; live?: boolean }) {
  const words = text.split(/\s+/).filter(Boolean)
  return (
    <>
      {words.map((word, index) => {
        const fromEnd = words.length - 1 - index
        return (
          <span key={index} className="word" data-tail={live && fromEnd < 4 ? fromEnd + 1 : undefined}>
            {word}{' '}
          </span>
        )
      })}
    </>
  )
}

/** A number of seconds that counts up while `running`, to one decimal below 10 s. */
export function Elapsed({ since, running, final }: { since: number; running: boolean; final?: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(timer)
  }, [running])
  const seconds = (running ? now - since : (final ?? now - since)) / 1000
  return <span className="mono">{formatSeconds(seconds)}</span>
}

/** A box that opens and closes by its content height. It uses a grid row, so
 *  no height is measured and the page never jumps. */
export function Fold({ open, children }: { open: boolean; children: ReactNode }) {
  const inner = useRef<HTMLDivElement>(null)
  return (
    <div className="fold" data-open={open}>
      <div className="fold-inner" ref={inner} inert={!open}>
        {children}
      </div>
    </div>
  )
}

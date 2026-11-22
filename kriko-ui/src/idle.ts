import { useEffect, useState } from 'react'

type IdleWindow = Window & {
  requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number
  cancelIdleCallback?: (id: number) => void
}

/** Run `callback` once the browser is idle, and at the latest after `timeout` ms.
 *  Where there is no idle callback (Safari, a test) a short timer stands in.
 *  Returns the way to cancel it. */
export function whenIdle(callback: () => void, timeout = 1200): () => void {
  const w = window as IdleWindow
  if (typeof w.requestIdleCallback === 'function') {
    const id = w.requestIdleCallback(callback, { timeout })
    return () => w.cancelIdleCallback?.(id)
  }
  const id = window.setTimeout(callback, Math.min(timeout, 200))
  return () => window.clearTimeout(id)
}

/** False on the first paint, true once the window has been idle. Decoration
 *  waits for it, so nothing ornamental sits on the path to an interactive Ask. */
export function useAfterIdle(timeout = 1500): boolean {
  const [ready, setReady] = useState(false)
  useEffect(() => whenIdle(() => setReady(true), timeout), [timeout])
  return ready
}

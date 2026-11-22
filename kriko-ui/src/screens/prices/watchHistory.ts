import { useEffect, useRef, useState } from 'react'
import { get, seg } from '../../engine/api'
import type { PriceHistory } from './priceHistory'

/** One history request per watch at most, kept for 30 seconds. A watch that was
 *  read again since (its `last_checked` moved) asks again at once. */

export const HISTORY_CACHE_MS = 30_000

interface Cached { at: number; stamp: string; data: PriceHistory }

const cache = new Map<string, Cached>()
const inflight = new Map<string, Promise<PriceHistory>>()

export function clearHistoryCache() {
  cache.clear()
  inflight.clear()
}

export function fetchHistory(watchId: string, stamp: string, now: number = Date.now()): Promise<PriceHistory> {
  const kept = cache.get(watchId)
  if (kept && kept.stamp === stamp && now - kept.at < HISTORY_CACHE_MS) return Promise.resolve(kept.data)
  const running = inflight.get(watchId)
  if (running) return running
  const request = get<PriceHistory>(`/api/prices/watches/${seg(watchId)}/history`)
    .then((data) => {
      cache.set(watchId, { at: now, stamp, data })
      return data
    })
    .finally(() => { inflight.delete(watchId) })
  inflight.set(watchId, request)
  return request
}

/** True once the element has been on screen. Without IntersectionObserver the row counts as seen. */
export function useSeen<T extends Element>() {
  const ref = useRef<T>(null)
  const [seen, setSeen] = useState(typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    const node = ref.current
    if (seen || !node) return
    const watcher = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setSeen(true)
        watcher.disconnect()
      }
    }, { rootMargin: '120px' })
    watcher.observe(node)
    return () => watcher.disconnect()
  }, [seen])
  return { ref, seen }
}

/** The history of one watch, loaded when `enabled` turns true. A failure leaves it unknown, never invented. */
export function useWatchHistory(watchId: string, stamp: string, enabled: boolean): PriceHistory | null {
  const [loaded, setLoaded] = useState<{ id: string; stamp: string; data: PriceHistory } | null>(null)
  useEffect(() => {
    if (!enabled) return
    let live = true
    fetchHistory(watchId, stamp)
      .then((data) => { if (live) setLoaded({ id: watchId, stamp, data }) })
      .catch(() => { /* the row simply has no picture */ })
    return () => { live = false }
  }, [watchId, stamp, enabled])
  return loaded && loaded.id === watchId ? loaded.data : null
}

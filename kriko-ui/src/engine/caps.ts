import { useCallback, useEffect, useState } from 'react'
import type { CapResource } from './caprules'

export * from './caprules'

/** Where a reader's daily ceilings live: this window's storage, beside the
 *  theme and the motion dial. It is a warning on the screen, never a stop in
 *  the engine, so it stays out of the engine's preferences on purpose: a cap
 *  that could halt research would be a second engine decision by the back door.
 *
 *  The usage card and the Settings panel read the same keys, and a change in
 *  one is heard by the other at once. */

const KEY = (id: CapResource) => `kriko.cap.${id}`
const EVENT = 'kriko:caps'

/** The stored ceiling for one resource, or `null` when the reader set none. */
export function readCap(id: CapResource): number | null {
  try {
    const raw = window.localStorage.getItem(KEY(id))
    if (raw === null || raw.trim() === '') return null
    const value = Number(raw)
    return Number.isFinite(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

export function readCaps(): Record<CapResource, number | null> {
  return {
    cli_agent: readCap('cli_agent'),
    llm_api: readCap('llm_api'),
    web_search: readCap('web_search'),
    local_model: readCap('local_model'),
  }
}

/** Store a ceiling. `null` clears it. Other readers in this window hear at once. */
export function writeCap(id: CapResource, value: number | null) {
  try {
    if (value === null || !Number.isFinite(value) || value <= 0) window.localStorage.removeItem(KEY(id))
    else window.localStorage.setItem(KEY(id), String(value))
  } catch {
    /* storage can be blocked; the cap then lasts for this session only */
  }
  window.dispatchEvent(new Event(EVENT))
}

export function useCaps(): { caps: Record<CapResource, number | null>; setCap: (id: CapResource, value: number | null) => void } {
  const [caps, setCaps] = useState(readCaps)
  useEffect(() => {
    const on = () => setCaps(readCaps())
    window.addEventListener(EVENT, on)
    window.addEventListener('storage', on)
    return () => {
      window.removeEventListener(EVENT, on)
      window.removeEventListener('storage', on)
    }
  }, [])
  const setCap = useCallback((id: CapResource, value: number | null) => {
    writeCap(id, value)
    setCaps(readCaps())
  }, [])
  return { caps, setCap }
}

import { useCallback, useEffect, useSyncExternalStore } from 'react'
import { get, put } from './api'
import { useEngine } from './Engine'
import { normalise, type Sensitivity } from './thinness'

/** The reader's information sensitivity: one value for the whole window.
 *  Live, it is the engine's `info_sensitivity` setting, which the browser
 *  extension reads too. In demo mode it is kept in the window. Screens read it
 *  here so a change in Settings reaches the Product and Compare screens at once. */

let current: Sensitivity = 'all'
const listeners = new Set<() => void>()
const publish = (next: Sensitivity) => {
  current = next
  listeners.forEach((listener) => listener())
}
const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useSensitivity() {
  const { mode } = useEngine()
  const value = useSyncExternalStore(subscribe, () => current, () => current)

  useEffect(() => {
    if (mode !== 'live') return
    let alive = true
    get<Record<string, unknown>>('/api/settings')
      .then((all) => alive && publish(normalise(all.info_sensitivity)))
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [mode])

  /** Choose a step. It shows at once; the engine's answer decides whether it stays. */
  const choose = useCallback(
    async (next: Sensitivity): Promise<string> => {
      const was = current
      publish(next)
      if (mode !== 'live') return ''
      try {
        const saved = await put<{ chosen?: Record<string, string> }>('/api/prefs', { info_sensitivity: next })
        publish(normalise(saved.chosen?.info_sensitivity))
        return ''
      } catch (error) {
        publish(was)
        return error instanceof Error ? error.message : 'Could not save the setting.'
      }
    },
    [mode],
  )

  return { sensitivity: value, choose }
}

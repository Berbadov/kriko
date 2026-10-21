import { useCallback, useEffect, useState } from 'react'
import { get } from './api'
import { useEngine } from './Engine'
import { demoMeters, type Meters } from './usagemeters'

/** The usage meters, read when the window opens and every half minute after.
 *  Demo mode shows example numbers and says so; a failed read keeps the last
 *  good one rather than blanking the pill. */
export function useUsage(): { meters: Meters | null; demo: boolean; reload: () => void } {
  const { mode } = useEngine()
  const [live, setLive] = useState<Meters | null>(null)
  const [example] = useState(() => demoMeters(Math.round(Date.now() / 1000)))
  const demo = mode === 'demo'

  const reload = useCallback(() => {
    if (mode !== 'live') return
    get<Meters>('/api/usage/meters', 8000).then(setLive, () => undefined)
  }, [mode])

  useEffect(() => {
    if (mode !== 'live') return
    reload()
    const id = window.setInterval(reload, 30_000)
    return () => window.clearInterval(id)
  }, [mode, reload])

  return { meters: demo ? example : live, demo, reload }
}

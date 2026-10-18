import { useCallback, useEffect, useRef, useState } from 'react'
import { del, get, post, seg } from './api'
import { useEngine } from './Engine'
import { followJob } from './jobs'

/** The pages that Kriko can read, and the sites that someone asked for.
 *  Live, these are `/api/sites`. In demo mode the same shapes are kept in the window. */

/** Where the way to read a site came from. */
export type Origin = 'catalog' | 'agent' | 'reader' | 'inferred'

export interface Site {
  host: string
  origin: Origin
  /** Will the page panel appear: ready, needs the browser, off, or not known yet. */
  status: 'ready' | 'permission' | 'off' | 'waiting' | 'refused'
  detail: string
  /** Only a way that was worked out here can be turned off. */
  enabled: boolean
}

export interface Wanted {
  host: string
  asks: number
  title: string
  /** Set while an agent works on it, and after a failure. */
  state: 'open' | 'working' | 'failed'
  detail: string
}

interface ApiSite {
  site: string
  source: string
  learned_by: string
  enabled: boolean
  superseded?: boolean
  activation?: { state: string; detail: string }
}

interface ApiWanted {
  host: string
  asks: number
  title: string
  state: string
  detail: string
}

const DEMO_SITES: Site[] = [
  { host: 'akakce.com', origin: 'catalog', status: 'ready', detail: '', enabled: true },
  { host: 'trendyol.com', origin: 'catalog', status: 'permission', detail: 'Open the extension options and press Grant.', enabled: true },
  { host: 'hepsiburada.com', origin: 'agent', status: 'ready', detail: '', enabled: true },
  { host: 'example-shop.com', origin: 'inferred', status: 'ready', detail: '', enabled: true },
]
const DEMO_WANTED: Wanted[] = [
  { host: 'n11.com', asks: 3, title: 'Kettle - n11', state: 'open', detail: '' },
  { host: 'twitch.tv', asks: 1, title: 'Caedrel - Twitch', state: 'open', detail: '' },
]

const STATUS: Record<string, Site['status']> = { active: 'ready', needs_permission: 'permission', no_adapter: 'off', unknown: 'waiting', invalid: 'refused' }

function tidy(rows: ApiSite[]): Site[] {
  const seen = new Map<string, Site>()
  for (const row of rows) {
    // A local copy of what a catalog now ships says nothing new.
    if (row.superseded) continue
    const origin: Origin = row.source === 'pack' ? 'catalog' : row.learned_by === 'inference' ? 'inferred' : row.learned_by === 'reader' ? 'reader' : 'agent'
    const next: Site = { host: row.site, origin, status: STATUS[row.activation?.state ?? ''] ?? 'waiting', detail: row.activation?.detail ?? '', enabled: row.enabled }
    // Many catalogs can read one site. One row is enough, and a catalog's way is the one that stays.
    if (!seen.has(row.site) || (origin === 'catalog' && seen.get(row.site)?.origin !== 'catalog')) seen.set(row.site, next)
  }
  return [...seen.values()].sort((a, b) => a.host.localeCompare(b.host))
}

export function useSites() {
  const { mode } = useEngine()
  const [sites, setSites] = useState<Site[] | null>(null)
  const [wanted, setWanted] = useState<Wanted[]>([])
  const [problem, setProblem] = useState('')
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const load = useCallback(async () => {
    if (mode !== 'live') {
      setSites((now) => now ?? DEMO_SITES)
      setWanted((now) => (now.length ? now : DEMO_WANTED))
      return
    }
    try {
      const data = await get<{ registered: ApiSite[]; requested: ApiWanted[] }>('/api/sites')
      if (!alive.current) return
      setSites(tidy(data.registered))
      setWanted(data.requested.map((row) => ({ host: row.host, asks: row.asks, title: row.title, state: row.state === 'working' ? 'working' : row.state === 'failed' ? 'failed' : 'open', detail: row.detail })))
    } catch (error) {
      if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not read the sites.')
    }
  }, [mode])

  useEffect(() => {
    void load()
  }, [load])

  const turn = useCallback(
    async (host: string, enabled: boolean) => {
      setProblem('')
      try {
        if (mode === 'live') {
          await post(`/api/sites/${seg(host)}/inferred`, { enabled })
          await load()
        } else setSites((now) => (now ?? []).map((row) => (row.host === host ? { ...row, enabled, status: enabled ? 'ready' : 'off' } : row)))
      } catch (error) {
        if (alive.current) setProblem(error instanceof Error ? error.message : 'It did not work.')
      }
    },
    [mode, load],
  )

  const forget = useCallback(
    async (host: string) => {
      setProblem('')
      try {
        if (mode === 'live') {
          await del(`/api/sites/${seg(host)}`)
          await load()
        } else {
          setSites((now) => (now ?? []).filter((row) => row.host !== host))
          setWanted((now) => [...now, { host, asks: 1, title: '', state: 'open', detail: '' }])
        }
      } catch (error) {
        if (alive.current) setProblem(error instanceof Error ? error.message : 'It did not work.')
      }
    },
    [mode, load],
  )

  /** Ask an agent to work out how to read the site. It reads one page, so it can take a minute. */
  const learn = useCallback(
    async (host: string) => {
      setProblem('')
      const mark = (patch: Partial<Wanted>) => setWanted((now) => now.map((row) => (row.host === host ? { ...row, ...patch } : row)))
      mark({ state: 'working', detail: '' })
      try {
        if (mode !== 'live') {
          await new Promise((resolve) => window.setTimeout(resolve, 1400))
          if (!alive.current) return
          setWanted((now) => now.filter((row) => row.host !== host))
          setSites((now) => [...(now ?? []), { host, origin: 'agent', status: 'permission', detail: 'Open the extension options and press Grant.', enabled: true }])
          return
        }
        const started = await post<{ job_id: string }>(`/api/sites/${seg(host)}/register`)
        const end = await followJob(
          started.job_id,
          (reading) => alive.current && mark({ detail: reading.message ?? '' }),
          () => alive.current,
        )
        if (!end) return
        if (end.state !== 'succeeded') mark({ state: 'failed', detail: end.state === 'cancelled' ? 'Stopped.' : end.message || 'The agent could not read this site.' })
      } catch (error) {
        mark({ state: 'failed', detail: error instanceof Error ? error.message : 'It did not work.' })
      } finally {
        if (mode === 'live' && alive.current) void load()
      }
    },
    [mode, load],
  )

  return { sites, wanted, problem, turn, forget, learn }
}

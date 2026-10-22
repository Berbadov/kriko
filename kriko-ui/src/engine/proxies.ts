import { useCallback, useEffect, useRef, useState } from 'react'
import { get, notifyAgentsChanged, post, put } from './api'
import { useEngine } from './Engine'

/** Rotating proxies for pages that refuse to be read. Off unless the reader turns it on.
 *  Live, the engine's `/api/proxies`; the switch and addresses are saved with the other settings
 *  (`proxy_enabled`, `proxy_pool`) and the login under Keys. */

export interface ProxiesDoc {
  enabled: boolean
  pool: string[]
  login_saved: boolean
  active: boolean
  learned: {
    proxied_reads: number
    direct_fallbacks: number
    unreadable: number
    retirements: number
    healthy: number
    pool: number
    blocked_hosts: { host: string; count: number }[]
  } | null
  limits: { tries: number; retire_seconds: number; block_memory_seconds: number }
}

export interface ProxyCheck {
  address: string
  ok: boolean
  ms: number
  error: string
}

const DEMO: ProxiesDoc = {
  enabled: false,
  pool: [],
  login_saved: false,
  active: false,
  learned: null,
  limits: { tries: 3, retire_seconds: 300, block_memory_seconds: 1800 },
}

export function useProxies() {
  const { mode } = useEngine()
  const [doc, setDoc] = useState<ProxiesDoc | null>(null)
  const [problem, setProblem] = useState('')
  const [checked, setChecked] = useState<ProxyCheck[] | 'checking' | null>(null)
  const demo = useRef<ProxiesDoc>(structuredClone(DEMO))

  const load = useCallback(async () => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setProblem('')
      setDoc(structuredClone(demo.current))
      return
    }
    try {
      setDoc(await get<ProxiesDoc>('/api/proxies'))
      setProblem('')
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not read the proxy settings.')
    }
  }, [mode])

  useEffect(() => {
    void load()
  }, [load])

  const save = useCallback(
    async (patch: { proxy_enabled?: string; proxy_pool?: string }) => {
      setProblem('')
      setChecked(null)
      if (mode !== 'live') {
        const now = demo.current
        if (patch.proxy_enabled !== undefined) now.enabled = patch.proxy_enabled === '1'
        if (patch.proxy_pool !== undefined) now.pool = patch.proxy_pool.split(/[\s,]+/).filter(Boolean)
        now.active = now.enabled && now.pool.length > 0
        setDoc(structuredClone(now))
        return
      }
      try {
        await put('/api/prefs', patch)
        notifyAgentsChanged()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not save.')
      }
      await load()
    },
    [mode, load],
  )

  const check = useCallback(async () => {
    setChecked('checking')
    if (mode !== 'live') {
      window.setTimeout(() => setChecked(demo.current.pool.map((address, index) => ({ address, ok: index % 2 === 0, ms: 420, error: index % 2 === 0 ? '' : 'could not connect (ConnectionRefusedError)' }))), 400)
      return
    }
    try {
      const reply = await post<{ results: ProxyCheck[]; message: string }>('/api/proxies/check', {}, 60000)
      setChecked(reply.results)
      if (reply.message) setProblem(reply.message)
    } catch (error) {
      setChecked(null)
      setProblem(error instanceof Error ? error.message : 'The check did not finish.')
    }
  }, [mode])

  return { doc, problem, checked, save, check, reload: load }
}

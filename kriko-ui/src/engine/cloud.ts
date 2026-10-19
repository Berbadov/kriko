import { useCallback, useEffect, useState } from 'react'
import { del, EngineError, get, post, seg } from './api'
import { useEngine } from './Engine'

/** The relay: a small server of your own that keeps sealed copies of what you keep,
 *  so a phone and this computer agree, and watches a price while this computer is
 *  off. It cannot read what it stores. It is told a page only when you turn that
 *  watch on in the cloud. */

export interface RelayStatus {
  connected: boolean
  server: string
  group?: string
  watching: number
  private_labels: boolean
  synced_at: string
  topic?: string
  suggested_server?: string
}

const reason = (error: unknown, fallback: string) => (error instanceof EngineError ? error.message : fallback)

export function useRelay() {
  const { mode } = useEngine()
  const [status, setStatus] = useState<RelayStatus | null>(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)
  const [code, setCode] = useState('')

  const reload = useCallback(async () => {
    if (mode !== 'live') return
    try {
      setStatus(await get<RelayStatus>('/api/cloud'))
    } catch (error) {
      setProblem(reason(error, 'Could not read the relay.'))
    }
  }, [mode])

  useEffect(() => {
    void reload()
  }, [reload])

  const run = useCallback(
    async (act: () => Promise<unknown>, failed: string) => {
      setBusy(true)
      setProblem('')
      try {
        await act()
        await reload()
      } catch (error) {
        setProblem(reason(error, failed))
      } finally {
        setBusy(false)
      }
    },
    [reload],
  )

  const connect = (server: string, privateLabels: boolean) => run(() => post('/api/cloud/connect', { server_url: server, private_labels: privateLabels }), 'Could not connect.')
  const join = (pairing: string) => run(() => post('/api/cloud/join', { code: pairing }), 'Could not join.')
  const sync = () => run(() => post('/api/cloud/sync'), 'Could not sync.')
  const disconnect = () =>
    run(async () => {
      setCode('')
      await del('/api/cloud')
    }, 'Could not disconnect.')
  const toggleWatch = (watchId: string, on: boolean) => run(() => post(`/api/cloud/watches/${seg(watchId)}`, { on }), 'Could not change it.')
  /** The key, shown only because it was asked for. */
  const reveal = () =>
    run(async () => {
      setCode((await get<{ code: string }>('/api/cloud/pairing')).code)
    }, 'Could not make the code.')

  return { status, problem, busy, code, hide: () => setCode(''), connect, join, sync, disconnect, toggleWatch, reveal, live: mode === 'live' }
}

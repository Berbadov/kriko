import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { get, inShell, type ApiHarness } from './api'

/** Whether a real engine answers. Without one the interface plays demo data,
 *  so design work never waits on the engine. `?demo` in the address forces it. */

export type Mode = 'checking' | 'live' | 'demo'

export interface Agent {
  id: string
  label: string
  backend: 'harness' | 'local'
}

const DEMO_AGENTS: Agent[] = [
  { id: '', label: 'Default agent', backend: 'harness' },
  { id: 'coding', label: 'Coding agent', backend: 'harness' },
  { id: 'local', label: 'Local model', backend: 'local' },
]

interface Engine {
  mode: Mode
  /** What the shell says when it could not start the engine. */
  problem: string
  agents: Agent[]
  /** The agent the reader chose in Settings. */
  preferred: string
  /** The reader changed the default agent. */
  setPreferred: (id: string) => void
  retry: () => void
}

const Ctx = createContext<Engine | null>(null)

/** In the packaged window the shell starts the engine. Wait until it says it is ready. */
async function untilStarted(wanted: () => boolean): Promise<{ ok: boolean }> {
  const { invoke } = await import('@tauri-apps/api/core')
  for (;;) {
    if (!wanted()) throw new Error('no engine')
    const status = await invoke<{ state: 'starting' | 'ready' | 'failed'; title?: string; detail?: string }>('engine_status')
    if (status.state === 'ready') return { ok: true }
    if (status.state === 'failed') throw new Error(`${status.title}. ${status.detail}`.slice(0, 600))
    await new Promise((resolve) => window.setTimeout(resolve, 400))
  }
}

const forced = () => new URLSearchParams(window.location.search).has('demo')

export function EngineProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>('checking')
  const [agents, setAgents] = useState<Agent[]>(DEMO_AGENTS)
  const [preferred, setPreferred] = useState('')
  const [problem, setProblem] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (forced()) {
      setMode('demo')
      return
    }
    let live = true
    setMode('checking')
    setProblem('')
    get<{ ok?: boolean }>('/api/health', 2500)
      .catch(() => (inShell() ? untilStarted(() => live) : Promise.reject(new Error('no engine'))))
      .then(async () => {
        const prefs = await get<{ harnesses?: ApiHarness[]; chosen?: { preferred_harness?: string } }>('/api/prefs', 4000)
        if (!live) return
        const found = (prefs.harnesses ?? []).map<Agent>((h) => ({
          id: h.id,
          label: h.label,
          backend: h.local ? 'local' : 'harness',
        }))
        if (found.length) setAgents(found)
        setPreferred(prefs.chosen?.preferred_harness ?? '')
        setMode('live')
      })
      .catch((error: unknown) => {
        if (!live) return
        setProblem(error instanceof Error && error.message !== 'no engine' ? error.message : '')
        setMode('demo')
      })
    return () => {
      live = false
    }
  }, [attempt])

  const retry = useCallback(() => {
    // In the packaged window the shell owns the engine, so it starts it again.
    const again = inShell() ? import('@tauri-apps/api/core').then(({ invoke }) => invoke('engine_restart')) : Promise.resolve()
    void again.catch(() => undefined).then(() => setAttempt((n) => n + 1))
  }, [])
  const value = useMemo(() => ({ mode, problem, agents, preferred, setPreferred, retry }), [mode, problem, agents, preferred, retry])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useEngine(): Engine {
  const value = useContext(Ctx)
  if (!value) throw new Error('useEngine needs EngineProvider')
  return value
}

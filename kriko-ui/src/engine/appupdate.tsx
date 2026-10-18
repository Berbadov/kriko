import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { EngineError, get, inShell, post } from './api'
import { useEngine } from './Engine'

/** The newest release, when it is newer than the one running. */
export interface Release {
  version: string
  notes: string
  /** The release's page, for a copy that cannot install it itself. */
  page: string
}

type Phase = 'idle' | 'checking' | 'downloading' | 'installing'

interface AppUpdate {
  phase: Phase
  release: Release | null
  /** What went wrong the last time, in words. */
  problem: string
  /** A check has finished at least once, so "up to date" is a fact and not a blank. */
  checked: boolean
  /** This copy was installed by the installer and can be replaced by it. */
  canInstall: boolean
  /** The reader said "later" to this version. */
  dismissed: boolean
  check: () => Promise<void>
  install: () => Promise<void>
  dismiss: () => void
}

interface ApiUpdate {
  newer?: boolean
  error?: string
  version?: string
  notes?: string
  page?: string
}

const Ctx = createContext<AppUpdate | null>(null)

const LATER = 'kriko.update.later'
/** The first look waits, so it never competes with the window's own start. */
const FIRST_LOOK_MS = 8000
const EVERY_MS = 6 * 60 * 60 * 1000

const later = () => {
  try {
    return localStorage.getItem(LATER) ?? ''
  } catch {
    return ''
  }
}

export function UpdateProvider({ children }: { children: ReactNode }) {
  const { mode } = useEngine()
  const [phase, setPhase] = useState<Phase>('idle')
  const [release, setRelease] = useState<Release | null>(null)
  const [problem, setProblem] = useState('')
  const [checked, setChecked] = useState(false)
  const [canInstall, setCanInstall] = useState(false)
  const [skipped, setSkipped] = useState(later)
  const busy = useRef(false)

  useEffect(() => {
    if (!inShell()) return
    void import('@tauri-apps/api/core').then(({ invoke }) => invoke<boolean>('app_update_supported')).then(setCanInstall, () => setCanInstall(false))
  }, [])

  const check = useCallback(async () => {
    if (mode !== 'live' || busy.current) return
    busy.current = true
    setPhase('checking')
    setProblem('')
    try {
      const found = await get<ApiUpdate>('/api/app-update', 20000)
      if (found.error) setProblem(found.error)
      setRelease(found.newer && found.version ? { version: found.version, notes: found.notes ?? '', page: found.page ?? '' } : null)
      setChecked(!found.error)
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not look for an update.')
    } finally {
      busy.current = false
      setPhase('idle')
    }
  }, [mode])

  // A quiet look soon after the engine is up, and again every few hours while the app stays open.
  useEffect(() => {
    if (mode !== 'live') return
    const first = window.setTimeout(() => void check(), FIRST_LOOK_MS)
    const again = window.setInterval(() => void check(), EVERY_MS)
    return () => {
      window.clearTimeout(first)
      window.clearInterval(again)
    }
  }, [mode, check])

  const install = useCallback(async () => {
    if (!release || busy.current) return
    busy.current = true
    setProblem('')
    setPhase('downloading')
    try {
      const got = await post<{ path: string }>('/api/app-update/download', {}, 600000)
      setPhase('installing')
      const { invoke } = await import('@tauri-apps/api/core')
      // The shell starts the installer and closes this window; an answer only comes back when it could not.
      await invoke('app_install_update', { path: got.path })
    } catch (error) {
      const text = typeof error === 'string' ? error : error instanceof EngineError || error instanceof Error ? error.message : ''
      setProblem(text || 'The update could not be installed.')
      setPhase('idle')
      busy.current = false
    }
  }, [release])

  const dismiss = useCallback(() => {
    if (!release) return
    setSkipped(release.version)
    try {
      localStorage.setItem(LATER, release.version)
    } catch {
      /* it will be offered again next time; that is all */
    }
  }, [release])

  const value = useMemo<AppUpdate>(
    () => ({ phase, release, problem, checked, canInstall, dismissed: !!release && skipped === release.version, check, install, dismiss }),
    [phase, release, problem, checked, canInstall, skipped, check, install, dismiss],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAppUpdate(): AppUpdate {
  const value = useContext(Ctx)
  if (!value) throw new Error('useAppUpdate needs UpdateProvider')
  return value
}

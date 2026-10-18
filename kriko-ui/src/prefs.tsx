import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import type { Transition } from 'motion/react'

export type ThemePref = 'system' | 'dark' | 'light'
export type Profile = 'calm' | 'standard' | 'vivid'

/** How long and how far each profile moves, against Standard. */
const TIME: Record<Profile, number> = { calm: 1.35, standard: 1, vivid: 0.8 }
const DIST: Record<Profile, number> = { calm: 0.6, standard: 1, vivid: 1.45 }

interface Motion {
  /** True when animation may play: the reader allows it and the window is in front. */
  on: boolean
  /** A distance in pixels, scaled by the profile. */
  d: (px: number) => number
  /** A transition set for motion components. */
  tx: { quick: Transition; soft: Transition; spring: Transition; page: Transition }
}

interface Prefs {
  theme: ThemePref
  setTheme: (t: ThemePref) => void
  resolved: 'dark' | 'light'
  profile: Profile
  setProfile: (p: Profile) => void
  reduce: boolean
  setReduce: (r: boolean) => void
  motion: Motion
}

const Ctx = createContext<Prefs | null>(null)

function read<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = localStorage.getItem(key)
    return allowed.includes(value as T) ? (value as T) : fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* storage can be blocked; the choice then lasts for this session only */
  }
}

function useMedia(query: string): boolean {
  const [match, setMatch] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const list = window.matchMedia(query)
    const on = () => setMatch(list.matches)
    list.addEventListener('change', on)
    return () => list.removeEventListener('change', on)
  }, [query])
  return match
}

function useInFront(): boolean {
  const read = () => document.visibilityState === 'visible' && document.hasFocus()
  const [front, setFront] = useState(read)
  useEffect(() => {
    const on = () => setFront(read())
    window.addEventListener('focus', on)
    window.addEventListener('blur', on)
    document.addEventListener('visibilitychange', on)
    return () => {
      window.removeEventListener('focus', on)
      window.removeEventListener('blur', on)
      document.removeEventListener('visibilitychange', on)
    }
  }, [])
  return front
}

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemePref>(() =>
    read('kriko.theme', ['system', 'dark', 'light'] as const, 'system'),
  )
  const [profile, setProfileState] = useState<Profile>(() =>
    read('kriko.profile', ['calm', 'standard', 'vivid'] as const, 'standard'),
  )
  const [reduce, setReduceState] = useState(() => read('kriko.reduce', ['0', '1'] as const, '0') === '1')

  const systemLight = useMedia('(prefers-color-scheme: light)')
  const osReduce = useMedia('(prefers-reduced-motion: reduce)')
  const front = useInFront()

  const setTheme = useCallback((t: ThemePref) => {
    setThemeState(t)
    write('kriko.theme', t)
  }, [])
  const setProfile = useCallback((p: Profile) => {
    setProfileState(p)
    write('kriko.profile', p)
  }, [])
  const setReduce = useCallback((r: boolean) => {
    setReduceState(r)
    write('kriko.reduce', r ? '1' : '0')
  }, [])

  const resolved: 'dark' | 'light' = theme === 'system' ? (systemLight ? 'light' : 'dark') : theme
  const on = !(reduce || osReduce) && front

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    root.dataset.motion = on ? 'on' : 'off'
    root.style.setProperty('--tm', String(TIME[profile]))
    root.style.setProperty('--dm', String(DIST[profile]))
  }, [theme, on, profile])

  const motion = useMemo<Motion>(() => {
    const t = TIME[profile]
    const dist = DIST[profile]
    const off: Transition = { duration: 0 }
    return {
      on,
      d: (px) => (on ? px * dist : 0),
      tx: on
        ? {
            quick: { duration: 0.18 * t, ease: [0.22, 1, 0.36, 1] },
            soft: { duration: 0.42 * t, ease: [0.22, 1, 0.36, 1] },
            spring: { type: 'spring', stiffness: 420 / (t * t), damping: 34, mass: 0.9 },
            page: { duration: 0.46 * t, ease: [0.22, 1, 0.36, 1] },
          }
        : { quick: off, soft: off, spring: off, page: off },
    }
  }, [on, profile])

  const value = useMemo<Prefs>(
    () => ({ theme, setTheme, resolved, profile, setProfile, reduce, setReduce, motion }),
    [theme, setTheme, resolved, profile, setProfile, reduce, setReduce, motion],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function usePrefs(): Prefs {
  const value = useContext(Ctx)
  if (!value) throw new Error('usePrefs needs PrefsProvider')
  return value
}

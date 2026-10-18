import { createContext, useContext, type ReactNode } from 'react'
import { useDemoRun, type RunApi } from './activity/run'
import { useEngine } from './engine/Engine'
import { useLiveRun } from './engine/live'

/** The conversation lives above the screens, so a run goes on while the
 *  reader looks at Compare, and the answer is still there on return. */
const Ctx = createContext<RunApi | null>(null)

export function ChatProvider({ children }: { children: ReactNode }) {
  const { mode } = useEngine()
  const demo = useDemoRun()
  const real = useLiveRun()
  return <Ctx.Provider value={mode === 'live' ? real : demo}>{children}</Ctx.Provider>
}

export function useChat(): RunApi {
  const value = useContext(Ctx)
  if (!value) throw new Error('useChat needs ChatProvider')
  return value
}

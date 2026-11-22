import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { useDemoRun, type RunApi } from './activity/run'
import { useEngine } from './engine/Engine'
import { useLiveRun } from './engine/live'

/** The conversation lives above the screens, so a run goes on while the
 *  reader looks at Compare, and the answer is still there on return. */
const Ctx = createContext<RunApi | null>(null)
/** The things a reader can do to the chat, apart from what it holds. They keep
 *  their identity while the run streams, so a part of the window that only
 *  starts or stops a chat (the shell, the rail) is not drawn again for every
 *  word of an answer. */
type ChatActions = Pick<RunApi, 'start' | 'stop' | 'newChat' | 'open'>
const ActionsCtx = createContext<ChatActions | null>(null)

export function ChatProvider({ children }: { children: ReactNode }) {
  const { mode } = useEngine()
  const demo = useDemoRun()
  const real = useLiveRun()
  const api = mode === 'live' ? real : demo
  const { start, stop, newChat, open } = api
  const actions = useMemo<ChatActions>(() => ({ start, stop, newChat, open }), [start, stop, newChat, open])
  return (
    <ActionsCtx.Provider value={actions}>
      <Ctx.Provider value={api}>{children}</Ctx.Provider>
    </ActionsCtx.Provider>
  )
}

export function useChat(): RunApi {
  const value = useContext(Ctx)
  if (!value) throw new Error('useChat needs ChatProvider')
  return value
}

/** Start, stop, new chat and open, without subscribing to the run itself. */
export function useChatActions(): ChatActions {
  const value = useContext(ActionsCtx)
  if (!value) throw new Error('useChatActions needs ChatProvider')
  return value
}

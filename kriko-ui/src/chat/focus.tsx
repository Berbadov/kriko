import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

/** Which product or page the reader has selected in a chat. A card in the thread
 *  and its entry in the right-hand column are the same item, so both read this
 *  one key and light up together. Outside a chat the context is inert. */
interface Focus {
  key: string | null
  /** Select an item; where it was selected from decides which side is scrolled to it. */
  select: (key: string | null, from?: 'thread' | 'rail') => void
}

const Ctx = createContext<Focus>({ key: null, select: () => undefined })

export function FocusProvider({ children, reduceMotion }: { children: ReactNode; reduceMotion?: boolean }) {
  const [key, setKey] = useState<string | null>(null)
  const select = useCallback(
    (next: string | null, from: 'thread' | 'rail' = 'thread') => {
      setKey((now) => (now === next ? null : next))
      if (next === null) return
      // After the lit state has drawn, bring the other side's copy into view.
      window.requestAnimationFrame(() => {
        const side = from === 'rail' ? '.thread-scroll' : '.chat-rail-scroll'
        const found = [...document.querySelectorAll<HTMLElement>(`${side} [data-focus-key]`)].find((el) => el.dataset.focusKey === next)
        found?.scrollIntoView({ block: 'nearest', behavior: reduceMotion ? 'auto' : 'smooth' })
      })
    },
    [reduceMotion],
  )
  const value = useMemo(() => ({ key, select }), [key, select])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const useFocus = () => useContext(Ctx)

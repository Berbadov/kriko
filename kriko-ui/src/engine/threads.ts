import { useCallback, useEffect, useRef, useState } from 'react'
import type { Turn } from '../activity/run'
import { del, get, patch, seg } from './api'
import { useEngine } from './Engine'
import { ago } from './history'

/** The chats that the reader has had, newest first. Live, they are `/api/chat/threads`.
 *  In demo mode the same shapes are kept in the window for as long as it is open. */

export interface ChatThread {
  id: string
  title: string
  at: number
  when: string
  pinned: boolean
}

interface ApiThread {
  thread_id: string
  title: string
  updated_at: string
  pinned?: boolean
}

/** The event that tells the lists a chat was made, changed or deleted. */
export const THREADS_CHANGED = 'kriko:threads'
export const threadsChanged = () => window.dispatchEvent(new Event(THREADS_CHANGED))

interface DemoThread {
  id: string
  title: string
  at: number
  turns: Turn[]
  pinned?: boolean
}

const HOUR = 3600000
const demo: DemoThread[] = [
  {
    id: 'demo-kettle',
    title: 'Is the Delta kettle safe for daily use?',
    at: Date.now() - 2 * HOUR,
    turns: [
      {
        id: 'k1',
        prompt: 'Is the Delta kettle safe for daily use?',
        answer: 'Delta Unit 500 has **two sourced reports**: the lid hinge cracks, and the base runs warm. Neither is a safety risk on its own. Check the lid when it is new.',
        products: [{ id: 'delta', name: 'Delta Unit 500', note: '2 risks' }],
      },
    ],
  },
  {
    id: 'demo-drill',
    title: 'Which drill lasts longer under heavy use?',
    at: Date.now() - 27 * HOUR,
    turns: [
      {
        id: 'd1',
        prompt: 'Which drill lasts longer under heavy use?',
        answer: 'Gamma Unit 400 keeps its chuck better than Beta Unit 300. Both report battery fade after a year of daily work.',
        products: [],
      },
    ],
  },
]

export const demoThreads = {
  list: () => [...demo].sort((a, b) => b.at - a.at),
  get: (id: string) => demo.find((row) => row.id === id),
  /** Keep the turns of a chat. A new chat is named after its first question. */
  save(id: string, turns: Turn[]) {
    if (turns.length === 0) return
    const found = demo.find((row) => row.id === id)
    if (found) {
      if (found.turns.length === turns.length) return
      found.turns = turns
      found.at = Date.now()
    } else demo.push({ id, title: turns[0].prompt, at: Date.now(), turns })
    threadsChanged()
  },
  remove(id: string) {
    const at = demo.findIndex((row) => row.id === id)
    if (at >= 0) demo.splice(at, 1)
  },
  rename(id: string, title: string) {
    const found = demo.find((row) => row.id === id)
    if (found && title.trim()) found.title = title.trim()
  },
  pin(id: string, pinned: boolean) {
    const found = demo.find((row) => row.id === id)
    if (found) found.pinned = pinned
  },
  /** The chats whose name, or any question or answer, holds the words. */
  find(words: string) {
    const needle = words.trim().toLowerCase()
    if (!needle) return this.list()
    return this.list().filter(
      (row) =>
        row.title.toLowerCase().includes(needle) ||
        row.turns.some((turn) => turn.prompt.toLowerCase().includes(needle) || turn.answer.toLowerCase().includes(needle)),
    )
  },
}

export function useThreads(query = '') {
  const { mode } = useEngine()
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [problem, setProblem] = useState('')
  // The newest request wins: typing in the rail's search sends one per key, and they can arrive out of order.
  const latest = useRef(0)

  const load = useCallback(async () => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setThreads(demoThreads.find(query).map((row) => ({ id: row.id, title: row.title, at: row.at, when: ago(row.at), pinned: !!row.pinned })))
      return
    }
    const mine = ++latest.current
    try {
      const data = await get<{ items: ApiThread[] }>(query.trim() ? `/api/chat/threads?q=${encodeURIComponent(query.trim())}` : '/api/chat/threads')
      if (latest.current !== mine) return
      // A chat with no name has no question in it yet.
      setThreads(
        data.items
          .filter((row) => row.title.trim())
          .map((row) => ({ id: row.thread_id, title: row.title, at: new Date(row.updated_at).getTime(), when: ago(row.updated_at), pinned: !!row.pinned })),
      )
    } catch {
      /* the list stays as it was; the rail is not the place for an error */
    }
  }, [mode, query])

  useEffect(() => {
    void load()
    window.addEventListener(THREADS_CHANGED, load)
    return () => window.removeEventListener(THREADS_CHANGED, load)
  }, [load])

  const remove = useCallback(
    async (id: string) => {
      setProblem('')
      try {
        if (mode === 'live') await del(`/api/chat/threads/${seg(id)}`)
        else demoThreads.remove(id)
        await load()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not delete the chat.')
      }
    },
    [mode, load],
  )

  /** Give a chat the name the reader chose. */
  const rename = useCallback(
    async (id: string, title: string) => {
      setProblem('')
      const name = title.trim()
      if (!name) return
      try {
        if (mode === 'live') await patch(`/api/chat/threads/${seg(id)}`, { title: name })
        else demoThreads.rename(id, name)
        await load()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not rename the chat.')
      }
    },
    [mode, load],
  )

  /** Keep a chat at the top of the list, or let it go back. */
  const pin = useCallback(
    async (id: string, pinned: boolean) => {
      setProblem('')
      try {
        if (mode === 'live') await patch(`/api/chat/threads/${seg(id)}`, { pinned })
        else demoThreads.pin(id, pinned)
        await load()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not pin the chat.')
      }
    },
    [mode, load],
  )

  return { threads, problem, remove, rename, pin, live: mode === 'live' }
}

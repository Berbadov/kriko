import { useCallback, useEffect, useState } from 'react'
import type { Turn } from '../activity/run'
import { del, get, seg } from './api'
import { useEngine } from './Engine'
import { ago } from './history'

/** The chats that the reader has had, newest first. Live, they are `/api/chat/threads`.
 *  In demo mode the same shapes are kept in the window for as long as it is open. */

export interface ChatThread {
  id: string
  title: string
  at: number
  when: string
}

interface ApiThread {
  thread_id: string
  title: string
  updated_at: string
}

/** The event that tells the lists a chat was made, changed or deleted. */
export const THREADS_CHANGED = 'kriko:threads'
export const threadsChanged = () => window.dispatchEvent(new Event(THREADS_CHANGED))

interface DemoThread {
  id: string
  title: string
  at: number
  turns: Turn[]
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
}

export function useThreads() {
  const { mode } = useEngine()
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [problem, setProblem] = useState('')

  const load = useCallback(async () => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setThreads(demoThreads.list().map((row) => ({ id: row.id, title: row.title, at: row.at, when: ago(row.at) })))
      return
    }
    try {
      const data = await get<{ items: ApiThread[] }>('/api/chat/threads')
      // A chat with no name has no question in it yet.
      setThreads(
        data.items
          .filter((row) => row.title.trim())
          .map((row) => ({ id: row.thread_id, title: row.title, at: new Date(row.updated_at).getTime(), when: ago(row.updated_at) })),
      )
    } catch {
      /* the list stays as it was; the rail is not the place for an error */
    }
  }, [mode])

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

  return { threads, problem, remove }
}

import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { demoThreads } from '../engine/threads'

/** One run of an agent, as the interface sees it. The mock engine below fills
 *  it in time. The real engine will fill the same shape from its live feed. */

export type StepState = 'todo' | 'active' | 'done'

export type Row =
  | { kind: 'thought'; id: string; text: string; done: boolean }
  | {
      kind: 'tool'
      id: string
      name: string
      detail: string
      startedAt: number
      ms?: number
      failed?: boolean
      /** Exact URL observed by the runner, when the runner reports one. */
      url?: string
      /** Counts reported by the search/read implementation, never inferred from other rows. */
      counts?: { searchResults?: number; pagesAttempted?: number; pagesRead?: number }
    }
  | {
      kind: 'event'
      id: string
      text: string
      stage?: string
      level?: 'info' | 'warn' | 'error'
      sourceUrl?: string
      counts?: { searchResults?: number; pagesAttempted?: number; pagesRead?: number }
    }
  | { kind: 'plan'; id: string; steps: { label: string; state: StepState }[] }

/** A product that a turn found in the reader's own catalogs. */
export interface Product {
  id: string
  name: string
  note: string
}

/** Which agent answered: the id picks its mark, the label is what the reader reads. */
export interface AgentRef {
  id: string
  label: string
}

/** A question the agent asked instead of answering, with what a reader can press.
 *  One detail it could not settle itself: a size, a model year, an engine. */
export interface Question {
  id: string
  ask: string
  options: string[]
  key?: string
  why?: string
}

export interface Run {
  status: 'idle' | 'running' | 'done' | 'stopped' | 'failed'
  startedAt: number
  endedAt?: number
  prompt: string
  rows: Row[]
  answer: string
  products: Product[]
  followups?: string[]
  /** The one question this turn asked, when it asked instead of answering. */
  questions?: Question[]
  /** The answer is complete, even if the turn is still naming its follow-ups. */
  answerFinal?: boolean
  /** Why the run failed, in the engine's words. */
  error?: string
  agent?: AgentRef
  /** Index of the active plan step. */
  step: number
}

/** A turn that has ended: what was asked, the answer, and the products found. */
export interface Turn {
  id: string
  prompt: string
  answer: string
  products: Product[]
  rows?: Row[]
  followups?: string[]
  questions?: Question[]
  /** Why the turn failed, when it did. */
  error?: string
  agent?: AgentRef
}

/** What the reader can ask Chat to do with a product. The engine knows the same three by name. */
export type ChatMode = 'alternatives' | 'cheapest' | 'merchants'

/** What the screens hold: the chat so far, the run now, and what the reader can do. */
export interface RunApi {
  run: Run
  /** The turns of this chat that came before the run. */
  turns: Turn[]
  /** The chat that the run belongs to. Empty before the first question. */
  threadId: string
  start: (prompt: string, agent: { id: string; label?: string; backend: 'harness' | 'local' }, mode?: ChatMode) => void
  stop: () => void
  /** Leave this chat and start a new, empty one. */
  newChat: () => void
  /** Show a chat from the list. */
  open: (threadId: string) => Promise<void>
}

/** The turn that a run became once it ended. A run in flight or not begun is not one yet. */
export const turnOf = (run: Run): Turn | null =>
  run.status === 'idle' || run.status === 'running' || !run.prompt
    ? null
    : { id: String(run.startedAt), prompt: run.prompt, answer: run.answer, products: run.products, rows: run.rows, followups: run.followups, questions: run.questions, error: run.error, agent: run.agent }

export type Action =
  | { type: 'start'; prompt: string; now: number }
  | { type: 'add'; row: Row }
  | { type: 'patch'; id: string; patch: Partial<Row> }
  | { type: 'words'; id: string; text: string }
  | { type: 'answer'; text: string }
  | { type: 'step'; step: number }
  | { type: 'end'; status: 'done' | 'stopped'; now: number }
  | { type: 'replace'; patch: Partial<Run> }
  | { type: 'reset' }

export const EMPTY: Run = { status: 'idle', startedAt: 0, prompt: '', rows: [], answer: '', products: [], step: 0 }

export function runReducer(run: Run, action: Action): Run {
  switch (action.type) {
    case 'start':
      return { ...EMPTY, status: 'running', startedAt: action.now, prompt: action.prompt }
    case 'replace':
      return { ...run, ...action.patch }
    case 'reset':
      return EMPTY
    case 'add':
      return { ...run, rows: [...run.rows, action.row] }
    case 'patch':
      return { ...run, rows: run.rows.map((r) => (r.id === action.id ? ({ ...r, ...action.patch } as Row) : r)) }
    case 'words':
      return {
        ...run,
        rows: run.rows.map((r) =>
          r.id === action.id && r.kind === 'thought' ? { ...r, text: r.text ? `${r.text} ${action.text}` : action.text } : r,
        ),
      }
    case 'answer':
      return { ...run, answer: run.answer ? `${run.answer} ${action.text}` : action.text }
    case 'step':
      return {
        ...run,
        step: action.step,
        rows: run.rows.map((r) =>
          r.kind === 'plan'
            ? {
                ...r,
                steps: r.steps.map((s, i) => ({
                  ...s,
                  state: i < action.step ? 'done' : i === action.step ? 'active' : 'todo',
                })),
              }
            : r,
        ),
      }
    case 'end':
      return {
        ...run,
        status: action.status,
        endedAt: action.now,
        rows: run.rows.map((r) => {
          if (r.kind === 'thought') return { ...r, done: true }
          if (r.kind === 'tool' && r.ms === undefined) return { ...r, ms: action.now - r.startedAt }
          if (r.kind === 'plan' && action.status === 'done') return { ...r, steps: r.steps.map((s) => ({ ...s, state: 'done' as const })) }
          return r
        }),
      }
  }
}

/** The script a mock run plays. Times are real milliseconds. */
interface Beat {
  at: number
  do: (api: Api) => void
}

interface Api {
  dispatch: (a: Action) => void
}

const THOUGHT_1 = 'Check what the catalog holds about this product before any search.'
const THOUGHT_2 = 'Two makers report heat under long load. Read the maker page for the exact limit.'
const ANSWER =
  'Alpha Unit 200 has **one sourced report**: it overheats under long loads. The maker states a limit of 40 minutes of full load. Check your use against that limit before you buy.'

function script(): Beat[] {
  const beats: Beat[] = []
  let t = 300
  const add = (delay: number, fn: (api: Api) => void) => {
    t += delay
    beats.push({ at: t, do: fn })
  }
  const stream = (id: string, text: string, kind: 'thought' | 'answer', each = 55) => {
    text.split(' ').forEach((word) => add(each, ({ dispatch }) => dispatch(kind === 'thought' ? { type: 'words', id, text: word } : { type: 'answer', text: word })))
  }

  add(0, ({ dispatch }) =>
    dispatch({
      type: 'add',
      row: {
        kind: 'plan',
        id: 'plan',
        steps: [
          { label: 'Read the catalog', state: 'active' },
          { label: 'Search the web', state: 'todo' },
          { label: 'Check the sources', state: 'todo' },
        ],
      },
    }),
  )
  add(250, ({ dispatch }) => dispatch({ type: 'add', row: { kind: 'thought', id: 't1', text: '', done: false } }))
  stream('t1', THOUGHT_1, 'thought')
  add(200, ({ dispatch }) => dispatch({ type: 'patch', id: 't1', patch: { done: true } }))
  add(150, ({ dispatch }) =>
    dispatch({ type: 'add', row: { kind: 'tool', id: 'k1', name: 'Catalog lookup', detail: 'Alpha Unit 200', startedAt: Date.now() } }),
  )
  add(1100, ({ dispatch }) => dispatch({ type: 'patch', id: 'k1', patch: { ms: 1100 } }))
  add(150, ({ dispatch }) => dispatch({ type: 'step', step: 1 }))
  add(200, ({ dispatch }) =>
    dispatch({ type: 'add', row: { kind: 'tool', id: 'k2', name: 'Web search', detail: 'alpha unit 200 overheating', startedAt: Date.now() } }),
  )
  add(3800, ({ dispatch }) => dispatch({ type: 'patch', id: 'k2', patch: { ms: 3800 } }))
  add(200, ({ dispatch }) =>
    dispatch({ type: 'add', row: { kind: 'tool', id: 'k3', name: 'Read page', detail: 'maker.example.test', startedAt: Date.now() } }),
  )
  add(2300, ({ dispatch }) => dispatch({ type: 'patch', id: 'k3', patch: { ms: 2300 } }))
  add(250, ({ dispatch }) => dispatch({ type: 'add', row: { kind: 'thought', id: 't2', text: '', done: false } }))
  stream('t2', THOUGHT_2, 'thought')
  add(200, ({ dispatch }) => dispatch({ type: 'patch', id: 't2', patch: { done: true } }))
  add(150, ({ dispatch }) => dispatch({ type: 'step', step: 2 }))
  add(200, ({ dispatch }) =>
    dispatch({ type: 'add', row: { kind: 'tool', id: 'k4', name: 'Check quote', detail: '2 sources', startedAt: Date.now() } }),
  )
  add(1600, ({ dispatch }) => dispatch({ type: 'patch', id: 'k4', patch: { ms: 1600 } }))
  stream('', ANSWER, 'answer', 45)
  add(300, ({ dispatch }) => {
    dispatch({ type: 'replace', patch: { products: [{ id: 'alpha', name: 'Alpha Unit 200', note: '1 risk' }] } })
    dispatch({ type: 'end', status: 'done', now: Date.now() })
  })
  return beats
}

export function useDemoRun(): RunApi {
  const [run, dispatch] = useReducer(runReducer, EMPTY)
  const [turns, setTurns] = useState<Turn[]>([])
  const [threadId, setThreadId] = useState('')
  const timers = useRef<number[]>([])

  const clear = useCallback(() => {
    timers.current.forEach((id) => window.clearTimeout(id))
    timers.current = []
  }, [])

  const start = useCallback(
    (prompt: string, agent?: { id: string; label?: string }) => {
      clear()
      const last = turnOf(run)
      if (last) setTurns((now) => [...now, last])
      if (!threadId) setThreadId(`demo-${Date.now()}`)
      dispatch({ type: 'start', prompt, now: Date.now() })
      if (agent) dispatch({ type: 'replace', patch: { agent: { id: agent.id, label: agent.label ?? agent.id } } })
      const api: Api = { dispatch }
      for (const beat of script()) {
        timers.current.push(window.setTimeout(() => beat.do(api), beat.at))
      }
    },
    [clear, run, threadId],
  )

  const stop = useCallback(() => {
    clear()
    dispatch({ type: 'end', status: 'stopped', now: Date.now() })
  }, [clear])

  const newChat = useCallback(() => {
    clear()
    dispatch({ type: 'reset' })
    setTurns([])
    setThreadId('')
  }, [clear])

  const open = useCallback(
    async (id: string) => {
      clear()
      dispatch({ type: 'reset' })
      setThreadId(id)
      setTurns(demoThreads.get(id)?.turns ?? [])
    },
    [clear],
  )

  // The demo keeps a chat as it goes, so it is in the list as soon as it has a question.
  useEffect(() => {
    if (!threadId) return
    const last = turnOf(run)
    demoThreads.save(threadId, last ? [...turns, last] : turns)
  }, [threadId, turns, run])

  useEffect(() => clear, [clear])

  return { run, turns, threadId, start, stop, newChat, open }
}

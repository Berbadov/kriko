import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { demoCheck, loadCheck, type Loaded } from './compare/checks'
import { useEngine, type Agent } from './engine/Engine'
import { EngineError, get, post, put, seg, type ApiJob } from './engine/api'
import { useQueue } from './queue'

/** What the Compare screen holds: up to four saved checks as columns, kept as
 *  a draft in the engine, and the questions the reader asked about them. */

export const MAX_SLOTS = 4
const POLL_MS = 700

export interface Question {
  id: string
  text: string
  answer: string
  state: 'running' | 'done' | 'failed'
  note: string
  agent: string
}

interface Compare {
  slots: string[]
  checks: Record<string, Loaded>
  questions: Question[]
  /** Add a saved check. Answers false when the board is full. */
  add: (lookupId: string) => boolean
  remove: (lookupId: string) => void
  ask: (text: string, agent: Agent) => void
  /** Read a column again after it failed. */
  retry: (lookupId: string) => void
}

const Ctx = createContext<Compare | null>(null)

const DEMO_SLOTS = ['demo:Alpha Unit 200', 'demo:Beta Unit 300']
const DEMO_ANSWER =
  'Alpha Unit 200 has **one high risk**: heat under long load. Beta Unit 300 has a short cable instead.\n\n- Pick Beta Unit 300 if your desk is far from a socket.\n- Pick Alpha Unit 200 for short jobs only.'

const reasonOf = (error: unknown) => (error instanceof EngineError ? error.message : 'The engine does not answer.')

interface ApiQuestion {
  question_id: string
  question: string
  answer?: string | null
  job_id?: string
}

interface ApiDraft {
  draft_id: string
  name: string
  lookup_ids: string[]
}

export function CompareProvider({ children }: { children: ReactNode }) {
  const { mode } = useEngine()
  const { lastDone } = useQueue()
  const live = mode === 'live'

  const [slots, setSlots] = useState<string[]>([])
  const [checks, setChecks] = useState<Record<string, Loaded>>({})
  const [questions, setQuestions] = useState<Question[]>([])
  const draft = useRef('')
  const saving = useRef(Promise.resolve())
  const alive = useRef(true)
  const loaded = useRef(false)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  // ---- the questions ----

  const patchQuestion = useCallback((id: string, change: Partial<Question>) => {
    if (!alive.current) return
    setQuestions((list) => list.map((q) => (q.id === id ? { ...q, ...change } : q)))
  }, [])

  /** Follow the job that answers a question. The answer grows in the job's partial result. */
  const follow = useCallback(
    async (id: string, job: string) => {
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, POLL_MS))
        if (!alive.current) return
        try {
          const reading = await get<ApiJob>(`/api/jobs/${seg(job)}`)
          const answer = (reading.result as { answer?: string } | null | undefined)?.answer ?? ''
          if (reading.done || ['succeeded', 'failed', 'cancelled'].includes(reading.state)) {
            if (reading.state === 'succeeded') patchQuestion(id, { answer: answer || 'No answer came back.', state: 'done' })
            else patchQuestion(id, { state: 'failed', note: reading.message || `The research ${reading.state}.` })
            return
          }
          if (answer) patchQuestion(id, { answer })
        } catch (error) {
          patchQuestion(id, { state: 'failed', note: reasonOf(error) })
          return
        }
      }
    },
    [patchQuestion],
  )

  const loadQuestions = useCallback(
    async (draftId: string) => {
      try {
        const reply = await get<{ items: ApiQuestion[] }>(`/api/compare-drafts/${seg(draftId)}/questions`)
        if (!alive.current) return
        setQuestions(
          reply.items.map((q) => ({
            id: q.question_id,
            text: q.question,
            answer: q.answer ?? '',
            state: q.answer ? 'done' : q.job_id ? 'running' : 'failed',
            note: q.answer || q.job_id ? '' : 'No answer came back.',
            agent: '',
          })),
        )
        for (const q of reply.items) if (!q.answer && q.job_id) void follow(q.question_id, q.job_id)
      } catch {
        /* The board still works without its old questions. */
      }
    },
    [follow],
  )

  // ---- the draft ----

  /** Save the slots. One save at a time, so an older request never wins last. */
  const save = useCallback((ids: string[]) => {
    saving.current = saving.current.then(async () => {
      try {
        const body = { name: 'Compare', lookup_ids: ids }
        const saved = draft.current
          ? await put<ApiDraft>(`/api/compare-drafts/${seg(draft.current)}`, body)
          : await post<ApiDraft>('/api/compare-drafts', body)
        if (!draft.current) {
          draft.current = saved.draft_id
          void loadQuestions(saved.draft_id)
        }
      } catch {
        /* The columns stay on screen. The next change saves again. */
      }
    })
  }, [loadQuestions])

  // The board opens on the draft that the engine holds.
  useEffect(() => {
    if (!live || loaded.current) return
    loaded.current = true
    void (async () => {
      try {
        const reply = await get<{ items: ApiDraft[] }>('/api/compare-drafts')
        const first = reply.items[0]
        if (!first || !alive.current) return
        draft.current = first.draft_id
        setSlots(first.lookup_ids.slice(0, MAX_SLOTS))
        void loadQuestions(first.draft_id)
      } catch {
        /* An empty board is a fine start. */
      }
    })()
  }, [live, loadQuestions])

  useEffect(() => {
    if (mode !== 'demo' || loaded.current) return
    loaded.current = true
    setSlots(DEMO_SLOTS)
  }, [mode])

  // ---- the columns ----

  const fetchCheck = useCallback(
    async (lookupId: string) => {
      if (lookupId.startsWith('demo:')) {
        setChecks((all) => ({ ...all, [lookupId]: { status: 'ready', check: demoCheck(lookupId, lookupId.slice(5)) } }))
        return
      }
      setChecks((all) => ({ ...all, [lookupId]: { status: 'loading' } }))
      try {
        const check = await loadCheck(lookupId)
        if (alive.current) setChecks((all) => ({ ...all, [lookupId]: { status: 'ready', check } }))
      } catch (error) {
        if (alive.current) setChecks((all) => ({ ...all, [lookupId]: { status: 'error', message: reasonOf(error) } }))
      }
    },
    [],
  )

  useEffect(() => {
    for (const id of slots) if (!checks[id]) void fetchCheck(id)
  }, [slots, checks, fetchCheck])

  const add = useCallback(
    (lookupId: string) => {
      if (!lookupId || slots.includes(lookupId)) return true
      if (slots.length >= MAX_SLOTS) return false
      const next = [...slots, lookupId]
      setSlots(next)
      if (live) save(next)
      return true
    },
    [slots, live, save],
  )

  const remove = useCallback(
    (lookupId: string) => {
      const next = slots.filter((id) => id !== lookupId)
      setSlots(next)
      if (live) save(next)
    },
    [slots, live, save],
  )

  const retry = useCallback(
    (lookupId: string) => {
      setChecks((all) => {
        const rest = { ...all }
        delete rest[lookupId]
        return rest
      })
    },
    [],
  )

  // A product the queue finished becomes a column.
  const taken = useRef(0)
  useEffect(() => {
    if (!lastDone || lastDone.n <= taken.current) return
    taken.current = lastDone.n
    // Defer: `add` reads the slots of this render.
    add(lastDone.lookupId)
  }, [lastDone, add])

  // ---- asking ----

  const ask = useCallback(
    async (text: string, agent: Agent) => {
      const id = `local-${Date.now()}`
      setQuestions((list) => [...list, { id, text, answer: '', state: 'running', note: '', agent: agent.label }])

      if (!live) {
        const words = DEMO_ANSWER.split(' ')
        for (let at = 3; at <= words.length + 2; at += 3) {
          await new Promise((resolve) => window.setTimeout(resolve, 140))
          if (!alive.current) return
          patchQuestion(id, { answer: words.slice(0, at).join(' ') })
        }
        patchQuestion(id, { state: 'done' })
        return
      }

      try {
        // A question is stored beside its comparison, so there must be one.
        await saving.current
        if (!draft.current) {
          const saved = await post<ApiDraft>('/api/compare-drafts', { name: 'Compare', lookup_ids: slots })
          draft.current = saved.draft_id
        }
        const sent = await post<{ question_id: string; job_id: string }>(`/api/compare-drafts/${seg(draft.current)}/questions`, {
          question: text,
          harness: agent.id,
          backend: agent.backend,
        })
        setQuestions((list) => list.map((q) => (q.id === id ? { ...q, id: sent.question_id } : q)))
        await follow(sent.question_id, sent.job_id)
      } catch (error) {
        patchQuestion(id, { state: 'failed', note: reasonOf(error) })
      }
    },
    [live, slots, follow, patchQuestion],
  )

  const value = useMemo<Compare>(
    () => ({ slots, checks, questions, add, remove, ask: (t, a) => void ask(t, a), retry }),
    [slots, checks, questions, add, remove, ask, retry],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useCompare(): Compare {
  const value = useContext(Ctx)
  if (!value) throw new Error('useCompare needs CompareProvider')
  return value
}

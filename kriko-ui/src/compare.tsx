import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { demoCheck, loadCheck, type Loaded } from './compare/checks'
import { useBoard, MAX_SLOTS } from './compare/board'
import { ENGINE_CHOOSES, researchCompareSlot, resumableNewProducts, type CompareDraft } from './compare/research'
import { ResearchSaves } from './compare/researchSaves'
import { useEngine, type Agent } from './engine/Engine'
import { EngineError, get, post, postQuestion, put, seg, type ApiFeedEvent, type ApiJob } from './engine/api'
import { followJob } from './engine/jobs'
import { useQueue } from './queue'

export { MAX_SLOTS } from './compare/board'

/** What the Compare screen holds: up to four saved checks as columns, kept as
 *  a draft in the engine, and the questions the reader asked about them. */

const POLL_MS = 700
const POLL_MISSES = 5

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
  research: (lookupId: string, agent: Agent, onJob: (jobId: string) => void) => Promise<void>
  /** Read a column again after it failed. */
  retry: (lookupId: string) => void
  /** Products named in Compare without a check yet, while their quick look runs. */
  pending: Pending[]
  /** Research a product by name and add it as a column when it is done. */
  researchNew: (name: string, agent?: Agent) => Promise<void>
  dismissPending: (id: string) => void
  stop: () => void
  problem: string
  saveAgain: () => void
}

/** A product the reader named in Compare, researched before it can be a column. */
export interface Pending {
  id: string
  name: string
  state: 'running' | 'failed'
  note: string
  /** The stage before a job exists, and the engine's own readings after. */
  stage?: string
  feed?: ApiFeedEvent[]
  jobState?: string
  jobMessage?: string
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

  const [checks, setChecks] = useState<Record<string, Loaded>>({})
  const [questions, setQuestions] = useState<Question[]>([])
  const [pending, setPending] = useState<Pending[]>([])
  const [problem, setProblem] = useState('')
  const jobOf = useRef(new Map<string, string>())
  const seenJobs = useRef(new Set<string>())
  const stopRequested = useRef(false)
  const draft = useRef('')
  const saving = useRef(Promise.resolve())
  const alive = useRef(true)
  const loaded = useRef(false)
  const unsaved = useRef(false)
  const researchSaves = useRef(new ResearchSaves())
  const boardRevision = useRef(0)
  const refreshQueue = useRef(Promise.resolve())

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const patchPending = useCallback((id: string, change: Partial<Pending>) => {
    if (!alive.current) return
    setPending((list) => list.map((one) => (one.id === id ? { ...one, ...change } : one)))
  }, [])

  // ---- the questions ----

  const patchQuestion = useCallback((id: string, change: Partial<Question>) => {
    if (!alive.current) return
    setQuestions((list) => list.map((q) => (q.id === id ? { ...q, ...change } : q)))
  }, [])

  /** Follow the job that answers a question. The answer grows in the job's partial result. */
  const follow = useCallback(
    async (id: string, job: string) => {
      jobOf.current.set(id, job)
      let misses = 0
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, POLL_MS))
        if (!alive.current) return
        try {
          const reading = await get<ApiJob>(`/api/jobs/${seg(job)}`)
          misses = 0
          const answer = (reading.result as { answer?: string } | null | undefined)?.answer ?? ''
          if (reading.done || ['succeeded', 'failed', 'cancelled'].includes(reading.state)) {
            if (reading.state === 'succeeded') patchQuestion(id, { answer: answer || 'No answer came back.', state: 'done' })
            else patchQuestion(id, { answer, state: 'failed', note: reading.message || `The research ${reading.state}.` })
            jobOf.current.delete(id)
            return
          }
          if (answer) patchQuestion(id, { answer })
        } catch (error) {
          // A busy engine can miss one read of a job that is still running.
          misses += 1
          if (misses < POLL_MISSES) continue
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
      } catch (error) {
        setProblem(`Could not load the saved questions. ${reasonOf(error)}`)
      }
    },
    [follow],
  )

  // ---- the draft ----

  /** Save the slots. One save at a time, so an older request never wins last. */
  const save = useCallback((ids: string[]) => {
    saving.current = saving.current.then(async () => {
      try {
        setProblem('')
        const body = {
          name: 'Compare',
          lookup_ids: await researchSaves.current.prepare(ids),
        }
        const saved = draft.current
          ? await put<ApiDraft>(`/api/compare-drafts/${seg(draft.current)}`, body)
          : await post<ApiDraft>('/api/compare-drafts', body)
        unsaved.current = false
        if (!draft.current) {
          draft.current = saved.draft_id
          void loadQuestions(saved.draft_id)
        }
      } catch (error) {
        unsaved.current = true
        setProblem(`The comparison is not saved. ${reasonOf(error)}`)
      }
    })
  }, [loadQuestions])

  const boardChanged = useCallback((ids: string[]) => {
    boardRevision.current += 1
    if (live) save(ids)
  }, [live, save])
  const board = useBoard({ onChange: boardChanged })
  const { slots, place, read: readBoard, add: append, remove: take } = board

  const add = useCallback(
    (lookupId: string) => {
      researchSaves.current.forget(lookupId)
      return append(lookupId)
    },
    [append],
  )

  const remove = useCallback(
    (lookupId: string) => {
      researchSaves.current.forget(lookupId)
      take(lookupId)
    },
    [take],
  )

  /** Follow one new-product quick look until its column can join the board.
   *  Shared by a press now and by the recovery of a run that began before a
   *  reload: both finish against the current board, never a captured one. */
  const followNew = useCallback(async (job: string, pendingId: string) => {
    if (!job || seenJobs.current.has(job)) return
    seenJobs.current.add(job)
    try {
      const ended = await followJob(job, (reading) => {
        patchPending(pendingId, { stage: undefined, jobState: reading.state, jobMessage: reading.message, feed: reading.feed })
      }, () => alive.current)
      if (!alive.current) return
      if (!ended || ended.state !== 'succeeded') {
        patchPending(pendingId, { state: 'failed', note: ended?.message || 'The research did not finish.' })
        return
      }
      if (!add(job)) {
        patchPending(pendingId, { state: 'failed', note: 'The comparison already holds four checks. Remove one and research this product again.' })
        return
      }
      setPending((list) => list.filter((one) => one.id !== pendingId))
    } catch (error) {
      patchPending(pendingId, { state: 'failed', note: reasonOf(error) })
    } finally {
      seenJobs.current.delete(job)
    }
  }, [add, patchPending])

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
        place(first.lookup_ids.slice(0, MAX_SLOTS))
        void loadQuestions(first.draft_id)
        // A product researched before this window opened is still a row in
        // flight: resume it, so a reload during research does not hide the work.
        try {
          const jobs = await get<{ items: ApiJob[] }>('/api/jobs?limit=30')
          if (!alive.current || draft.current !== first.draft_id) return
          for (const one of resumableNewProducts(jobs.items ?? [], first.draft_id, first.lookup_ids)) {
            if (seenJobs.current.has(one.jobId)) continue
            const id = `job:${one.jobId}`
            setPending((list) => (list.some((row) => row.id === id) ? list : [...list,
              { id, name: one.name, state: 'running', note: 'Resuming the research…', stage: 'Resuming the research…' }]))
            void followNew(one.jobId, id)
          }
        } catch {
          /* The comparison is still readable; a missed job list is not a load failure. */
        }
      } catch (error) {
        setProblem(`Could not load the saved comparison. ${reasonOf(error)}`)
      }
    })()
  }, [live, loadQuestions, place, followNew])

  useEffect(() => {
    if (mode !== 'demo' || loaded.current) return
    loaded.current = true
    place(DEMO_SLOTS)
  }, [mode, place])

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
    // `add` reads the board ref, so a completion that lands after another
    // column was added appends to the current board, never this render's.
    add(lastDone.lookupId)
  }, [lastDone, add])

  // ---- asking ----

  const ask = useCallback(
    async (text: string, agent: Agent) => {
      stopRequested.current = false
      const id = `local-${Date.now()}`
      let activeId = id
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
        if (unsaved.current) {
          save(readBoard())
          await saving.current
          if (unsaved.current) throw new EngineError(409, 'The comparison could not be saved, so research has not started. Retry saving before asking about these columns.')
        }
        if (!draft.current) {
          const saved = await post<ApiDraft>('/api/compare-drafts', { name: 'Compare', lookup_ids: readBoard() })
          draft.current = saved.draft_id
        }
        const sent = await postQuestion<{ question_id: string; job_id: string }>(`/api/compare-drafts/${seg(draft.current)}/questions`, {
          question: text,
          harness: agent.id,
          backend: agent.backend,
        })
        activeId = sent.question_id
        if (stopRequested.current) await post(`/api/jobs/${seg(sent.job_id)}/cancel`, {})
        setQuestions((list) => list.map((q) => (q.id === id ? { ...q, id: sent.question_id } : q)))
        await follow(sent.question_id, sent.job_id)
      } catch (error) {
        patchQuestion(activeId, { state: 'failed', note: reasonOf(error) })
      }
    },
    [live, readBoard, follow, patchQuestion, save],
  )

  /** Research one saved column with the selected agent. The backend replaces
   *  that draft slot when the durable quick-look job succeeds. */
  const research = useCallback(async (lookupId: string, agent: Agent, onJob: (jobId: string) => void) => {
    if (!live) throw new EngineError(0, 'Connect to Kriko before researching a product.')
    const draftId = await (async () => {
      await saving.current
      if (unsaved.current) {
        save(readBoard())
        await saving.current
        if (unsaved.current) throw new EngineError(409, 'The comparison could not be saved, so research has not started. Retry saving first.')
      }
      if (!draft.current) {
        const saved = await post<ApiDraft>('/api/compare-drafts', { name: 'Compare', lookup_ids: readBoard() })
        draft.current = saved.draft_id
      }
      return draft.current
    })()
    if (unsaved.current) {
      throw new EngineError(409, 'The comparison could not be saved, so research has not started. Retry saving first.')
    }
    // Hold queued saves until the worker finishes; pending and failed job IDs
    // must never replace a readable saved check.
    let beforeResearch: Promise<void>
    do {
      beforeResearch = saving.current
      await beforeResearch
    } while (beforeResearch !== saving.current)
    if (unsaved.current) throw new EngineError(409, 'Save the comparison before starting research.')
    const release = researchSaves.current.begin()
    let current
    try {
      current = await researchCompareSlot(draftId, lookupId, agent, {
        start: postQuestion,
        follow: async (jobId, stillWanted) => {
          try {
            const ended = await followJob(jobId, () => undefined, stillWanted)
            if (ended?.state === 'succeeded' && stillWanted()) {
              const reply = await get<{ items: CompareDraft[] }>('/api/compare-drafts')
              const durable = reply.items.find((item) => item.draft_id === draftId)
              researchSaves.current.confirm(lookupId, jobId, ended.state, durable?.lookup_ids ?? [])
            }
            return ended
          } finally { release() }
        },
        drafts: () => get<{ items: CompareDraft[] }>('/api/compare-drafts'),
        waitForSaves: async () => {
          let pending: Promise<void>
          do {
            pending = saving.current
            await pending
          } while (pending !== saving.current)
        },
        pause: () => new Promise((resolve) => window.setTimeout(resolve, 250)),
      }, () => alive.current && draft.current === draftId, onJob)
    } finally { release() }
    if (!current || !alive.current || draft.current !== draftId) return
    const sync = refreshQueue.current.catch(() => undefined).then(async () => {
      if (!alive.current || draft.current !== draftId) return
      let pending: Promise<void>
      do {
        pending = saving.current
        await pending
      } while (pending !== saving.current)
      const revision = boardRevision.current
      const reply = await get<{ items: CompareDraft[] }>('/api/compare-drafts')
      if (!alive.current || draft.current !== draftId || revision !== boardRevision.current) return
      const latest = reply.items.find((item) => item.draft_id === draftId)
      if (!latest) return
      place(latest.lookup_ids.slice(0, MAX_SLOTS))
      setChecks((previous) => {
        const next = { ...previous }
        delete next[lookupId]
        return next
      })
    })
    refreshQueue.current = sync
    await sync
  }, [live, save, readBoard, place])

  const dismissPending = useCallback((id: string) => setPending((list) => list.filter((one) => one.id !== id)), [])
  /** A product not yet checked: a quick look by name, which the engine adds to
   *  the draft when it succeeds. The column appears here at the same moment. */
  const researchNew = useCallback(async (name: string, agent?: Agent) => {
    const id = `new:${Date.now()}`
    const picked = agent ?? ENGINE_CHOOSES
    setPending((list) => [...list, { id, name, state: 'running', note: 'Starting the research…', stage: 'Starting the research…' }])
    try {
      if (!live) throw new EngineError(0, 'Connect to Kriko before researching a product.')
      if (readBoard().length >= MAX_SLOTS) {
        throw new EngineError(409, 'This comparison already holds four checks. Remove one before researching another.')
      }
      await saving.current
      if (!draft.current) {
        const saved = await post<ApiDraft>('/api/compare-drafts', { name: 'Compare', lookup_ids: readBoard() })
        draft.current = saved.draft_id
      }
      const sent = await post<{ job_id: string }>(`/api/compare-drafts/${seg(draft.current)}/products`, {
        product: name, harness: picked.id, backend: picked.backend,
      })
      await followNew(sent.job_id, id)
    } catch (error) {
      patchPending(id, { state: 'failed', note: reasonOf(error) })
    }
  }, [live, readBoard, followNew, patchPending])

  const stop = useCallback(() => {
    stopRequested.current = true
    for (const [id, job] of jobOf.current) void post(`/api/jobs/${seg(job)}/cancel`, {})
      .then(() => patchQuestion(id, { note: 'Stopping…' }))
      .catch((error) => setProblem(reasonOf(error)))
  }, [patchQuestion])

  const value = useMemo<Compare>(
    () => ({ slots, checks, questions, add, remove, ask: (t, a) => void ask(t, a), research, retry, stop, problem, pending, researchNew, dismissPending,
      saveAgain: () => {
        if (problem.startsWith('Could not load')) {
          void get<{items: ApiDraft[]}>('/api/compare-drafts').then((reply) => {
            setProblem('')
            const first = reply.items[0]
            if (first) { draft.current = first.draft_id; place(first.lookup_ids.slice(0, MAX_SLOTS)); void loadQuestions(first.draft_id) }
          }).catch((error) => setProblem(`Could not load the saved comparison. ${reasonOf(error)}`))
        } else save(slots)
      } }),
    [slots, checks, questions, add, remove, ask, research, retry, stop, problem, save, loadQuestions, pending, researchNew, dismissPending, place],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useCompare(): Compare {
  const value = useContext(Ctx)
  if (!value) throw new Error('useCompare needs CompareProvider')
  return value
}

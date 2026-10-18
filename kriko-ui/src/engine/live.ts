import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { EMPTY, runReducer, turnOf, type Product, type Row, type RunApi, type Turn } from '../activity/run'
import { EngineError, get, post, seg, type ApiJob, type ApiMessage, type ApiProduct, type ApiStep, type ApiTurn } from './api'
import { threadsChanged } from './threads'

/** A real turn: ask the engine, then read the job every 700 ms until it ends.
 *  The job's result holds the turn so far: its steps, and the answer once it
 *  is written. */

const POLL_MS = 700
const ACTIVE = new Set(['queued', 'running', 'cancelling'])

const words = (text: string) => text.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

function rowsFrom(steps: ApiStep[], seen: Map<string, number>): Row[] {
  return steps.map((step) => {
    if (!seen.has(step.id)) seen.set(step.id, Date.now())
    const running = step.state === 'running'
    return {
      kind: 'tool',
      id: step.id,
      name: words(step.source || 'Step'),
      detail: step.label,
      startedAt: seen.get(step.id) ?? Date.now(),
      ms: running ? undefined : step.ms,
      failed: step.state === 'error',
    }
  })
}

function productsFrom(list: ApiProduct[] | undefined): Product[] {
  return (list ?? []).map((p) => ({
    id: p.subject_id,
    name: p.label,
    note: p.claims === 1 ? '1 risk' : `${p.claims} risks`,
  }))
}

export function useLiveRun(): RunApi {
  const [run, dispatch] = useReducer(runReducer, EMPTY)
  const [turns, setTurns] = useState<Turn[]>([])
  const [threadId, setThreadId] = useState('')
  const thread = useRef('')
  /** The latest run, for the callbacks that move it into the chat when the next question comes. */
  const latest = useRef(run)
  useEffect(() => {
    latest.current = run
  }, [run])
  /** Counts the chats that were opened, so a slow answer for an old one is dropped. */
  const opened = useRef(0)
  const job = useRef('')
  const timer = useRef(0)
  const seen = useRef(new Map<string, number>())
  const live = useRef(true)

  const clear = useCallback(() => window.clearTimeout(timer.current), [])

  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
      clear()
    }
  }, [clear])

  const fail = useCallback((error: unknown) => {
    dispatch({
      type: 'replace',
      patch: {
        status: 'failed',
        endedAt: Date.now(),
        error: error instanceof EngineError ? error.message : 'The turn failed.',
      },
    })
  }, [])

  const poll = useCallback(
    async (jobId: string, threadId: string) => {
      if (!live.current || job.current !== jobId) return
      try {
        const current = await get<ApiJob>(`/api/jobs/${seg(jobId)}`)
        const turn: ApiTurn = current.result ?? {}
        if (ACTIVE.has(current.state)) {
          dispatch({
            type: 'replace',
            patch: { rows: rowsFrom(turn.steps ?? [], seen.current), answer: turn.answer ?? '', products: productsFrom(turn.products) },
          })
          timer.current = window.setTimeout(() => void poll(jobId, threadId), POLL_MS)
          return
        }
        if (current.state === 'succeeded') {
          // The thread holds the finished turn, with its answer and products.
          const messages = await get<{ items: ApiMessage[] }>(`/api/chat/threads/${seg(threadId)}/messages`)
          const last = [...messages.items].reverse().find((m) => m.role === 'agent')
          const finished: ApiTurn = last ?? turn
          dispatch({
            type: 'replace',
            patch: {
              rows: rowsFrom(finished.steps ?? [], seen.current),
              answer: last?.text ?? finished.answer ?? '',
              products: productsFrom(finished.products),
            },
          })
          dispatch({ type: 'end', status: 'done', now: Date.now() })
          threadsChanged()
          return
        }
        if (current.state === 'cancelled') {
          dispatch({ type: 'end', status: 'stopped', now: Date.now() })
          return
        }
        dispatch({ type: 'replace', patch: { rows: rowsFrom(turn.steps ?? [], seen.current) } })
        fail(new EngineError(0, current.message || 'The turn did not finish.'))
      } catch (error) {
        // A lost answer is not a lost turn: try again a few times before giving up.
        if (error instanceof EngineError && error.status === 0 && live.current && job.current === jobId) {
          timer.current = window.setTimeout(() => void poll(jobId, threadId), POLL_MS * 3)
          return
        }
        fail(error)
      }
    },
    [fail],
  )

  const start = useCallback<RunApi['start']>(
    (prompt, agent) => {
      clear()
      seen.current = new Map()
      job.current = ''
      const last = turnOf(latest.current)
      if (last) setTurns((now) => [...now, last])
      dispatch({ type: 'start', prompt, now: Date.now() })
      void (async () => {
        try {
          if (!thread.current) {
            thread.current = (await post<{ thread_id: string }>('/api/chat/threads', { title: '' })).thread_id
            setThreadId(thread.current)
          }
          const sent = await post<{ job_id: string }>(`/api/chat/threads/${seg(thread.current)}/messages`, {
            text: prompt,
            harness: agent.backend === 'local' ? '' : agent.id,
            backend: agent.backend,
          })
          job.current = sent.job_id
          threadsChanged()
          await poll(sent.job_id, thread.current)
        } catch (error) {
          fail(error)
        }
      })()
    },
    [clear, poll, fail],
  )

  const stop = useCallback(() => {
    clear()
    const id = job.current
    job.current = ''
    dispatch({ type: 'end', status: 'stopped', now: Date.now() })
    if (id) void post(`/api/jobs/${seg(id)}/cancel`).catch(() => undefined)
  }, [clear])

  const newChat = useCallback(() => {
    opened.current += 1
    clear()
    job.current = ''
    thread.current = ''
    seen.current = new Map()
    setThreadId('')
    setTurns([])
    dispatch({ type: 'reset' })
  }, [clear])

  /** Show a saved chat. Its turns come from the engine. A turn that is still being answered is followed. */
  const open = useCallback(
    async (id: string) => {
      const mine = ++opened.current
      clear()
      job.current = ''
      seen.current = new Map()
      thread.current = id
      setThreadId(id)
      setTurns([])
      dispatch({ type: 'reset' })
      try {
        const data = await get<{ items: ApiMessage[]; job_id?: string }>(`/api/chat/threads/${seg(id)}/messages`)
        if (!live.current || opened.current !== mine) return
        const found: Turn[] = []
        for (const message of data.items) {
          if (message.role === 'reader') found.push({ id: message.message_id, prompt: message.text, answer: '', products: [] })
          else if (found.length) {
            const turn = found[found.length - 1]
            turn.answer = message.text
            turn.products = productsFrom(message.products)
          }
        }
        const waiting = data.job_id && found.length && !found[found.length - 1].answer ? found.pop() : undefined
        setTurns(found)
        if (waiting && data.job_id) {
          dispatch({ type: 'start', prompt: waiting.prompt, now: Date.now() })
          job.current = data.job_id
          await poll(data.job_id, id)
        }
      } catch (error) {
        if (live.current && opened.current === mine) fail(error)
      }
    },
    [clear, poll, fail],
  )

  return { run, turns, threadId, start, stop, newChat, open }
}

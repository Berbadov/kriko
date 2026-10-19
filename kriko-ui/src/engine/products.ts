import { useCallback, useEffect, useRef, useState } from 'react'
import { useCompare } from '../compare'
import { EngineError, post, seg } from './api'
import { useEngine } from './Engine'
import { followJob } from './jobs'

/** What a reader does with a product an answer named. */

export type Step = 'idle' | 'busy' | 'done' | 'failed'

const reasonOf = (error: unknown) => (error instanceof EngineError ? error.message : 'The engine does not answer.')

export function useProductActions(product: { id: string; name: string }) {
  const { mode, preferred } = useEngine()
  const { add } = useCompare()
  const [adding, setAdding] = useState<{ step: Step; note: string }>({ step: 'idle', note: '' })
  const [reading, setReading] = useState<{ step: Step; note: string }>({ step: 'idle', note: '' })
  const [opening, setOpening] = useState<{ step: Step; note: string }>({ step: 'idle', note: '' })
  const lookup = useRef('')
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  /** The product's saved check. The engine keeps one for each product. */
  const ensureCheck = useCallback(async (): Promise<string> => {
    if (lookup.current) return lookup.current
    if (mode !== 'live') return (lookup.current = `demo:${product.name}`)
    const saved = await post<{ lookup_id?: string }>(`/api/products/${seg(product.id)}/check`, {})
    if (!saved.lookup_id) throw new EngineError(0, 'The answer was not saved.')
    return (lookup.current = saved.lookup_id)
  }, [mode, product.id, product.name])

  /**
   * Save the check, then open it.
   *
   * Separate from `ensureCheck` because saving is a request that can fail, and
   * the card used to call `void ensureCheck().then(onOpen).catch(() => {})`:
   * pressing **Open** on an engine that refused did nothing at all — no
   * spinner, no error, no navigation — which reads as a dead button.
   */
  const open = useCallback(async (onOpen: (lookupId: string) => void) => {
    setOpening({ step: 'busy', note: 'Saves' })
    try {
      const id = await ensureCheck()
      if (!alive.current) return
      setOpening({ step: 'done', note: '' })
      onOpen(id)
    } catch (error) {
      if (alive.current) setOpening({ step: 'failed', note: reasonOf(error) })
    }
  }, [ensureCheck])

  const addToCompare = useCallback(async () => {
    setAdding({ step: 'busy', note: '' })
    try {
      const id = await ensureCheck()
      const fits = add(id)
      if (alive.current) setAdding(fits ? { step: 'done', note: '' } : { step: 'failed', note: 'The board holds four.' })
    } catch (error) {
      if (alive.current) setAdding({ step: 'failed', note: reasonOf(error) })
    }
  }, [add, ensureCheck])

  /** Research the product again, then save the new check. */
  const readAgain = useCallback(async () => {
    setReading({ step: 'busy', note: 'Starts' })
    try {
      if (mode === 'live') {
        const started = await post<{ job_id: string }>('/api/research', { subject_id: product.id, harness: preferred })
        const ended = await followJob(
          started.job_id,
          (r) => alive.current && setReading({ step: 'busy', note: r.feed?.length ? r.feed[r.feed.length - 1].text : r.message || 'Reads' }),
          () => alive.current,
        )
        if (!ended) return
        if (ended.state !== 'succeeded') throw new EngineError(0, ended.message || `The research ${ended.state}.`)
        lookup.current = ''
        await ensureCheck()
      } else {
        await new Promise((resolve) => window.setTimeout(resolve, 1600))
      }
      if (alive.current) setReading({ step: 'done', note: '' })
    } catch (error) {
      if (alive.current) setReading({ step: 'failed', note: reasonOf(error) })
    }
  }, [mode, preferred, product.id, ensureCheck])

  return { adding, reading, opening, ensureCheck, open, addToCompare, readAgain }
}

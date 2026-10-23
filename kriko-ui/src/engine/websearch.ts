import { useCallback, useEffect, useRef, useState } from 'react'
import { get, notifyAgentsChanged, post, put } from './api'
import { useEngine } from './Engine'

/** The web search providers and their order. Live, it is the engine's
 *  `/api/search-providers`; the choice itself is saved with the other settings
 *  (`search_provider`, `search_fallback`). Demo mode keeps the same shapes in
 *  the window so the panel can be designed without an engine. */

export interface SearchHealth {
  calls: number
  recent: number
  /** Seconds since the epoch. */
  last_success: number | null
  last_failure: number | null
  last_problem: string
  /** Share of the recent searches that gave nothing, 0 to 1. */
  miss_rate: number | null
}

export interface SearchProviderRow {
  id: string
  label: string
  needs_key: boolean
  key_saved: boolean | null
  ready: boolean
  note: string
  health: SearchHealth
}

export interface SearchProvidersDoc {
  providers: SearchProviderRow[]
  primary: string
  fallback: string[]
  automatic: boolean
  effective: string[]
}

export interface SearchTest {
  provider: string
  label: string
  query: string
  ok: boolean
  results: { title: string; url: string; site: string }[]
  error: string
  ms: number
}

const NO_HEALTH: SearchHealth = { calls: 0, recent: 0, last_success: null, last_failure: null, last_problem: '', miss_rate: null }
const NOW = () => Math.round(Date.now() / 1000)

function demoDoc(): SearchProvidersDoc {
  return {
    primary: 'deepseek',
    fallback: [],
    automatic: true,
    effective: ['deepseek'],
    providers: [
      {
        id: 'openserp',
        label: 'OpenSERP',
        needs_key: false,
        key_saved: null,
        ready: true,
        note: 'Runs on this computer. No key. Sometimes a search engine blocks it or answers nothing.',
        health: { calls: 20, recent: 20, last_success: NOW() - 240, last_failure: NOW() - 900, last_problem: 'the SERP answered with a challenge page', miss_rate: 0.3 },
      },
      {
        id: 'deepseek',
        label: 'DeepSeek',
        needs_key: true,
        key_saved: true,
        ready: true,
        note: 'Hosted. Needs a key. Receives only the words searched.',
        health: { calls: 6, recent: 6, last_success: NOW() - 900, last_failure: null, last_problem: '', miss_rate: 0 },
      },
      { id: 'exa', label: 'Exa', needs_key: true, key_saved: false, ready: false, note: 'Hosted. Needs a key. Receives only the words searched.', health: NO_HEALTH },
      { id: 'tavily', label: 'Tavily', needs_key: true, key_saved: false, ready: false, note: 'Hosted. Needs a key. Receives only the words searched.', health: NO_HEALTH },
    ],
  }
}

export function useSearchProviders() {
  const { mode } = useEngine()
  const [doc, setDoc] = useState<SearchProvidersDoc | null>(null)
  const [problem, setProblem] = useState('')
  const [tested, setTested] = useState<Record<string, SearchTest | 'testing'>>({})
  const demo = useRef<SearchProvidersDoc>(demoDoc())

  const load = useCallback(async () => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setProblem('')
      setDoc(structuredClone(demo.current))
      return
    }
    try {
      setDoc(await get<SearchProvidersDoc>('/api/search-providers'))
      setProblem('')
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not read the search providers.')
    }
  }, [mode])

  useEffect(() => {
    void load()
  }, [load])

  /** Save the first choice and the order behind it. `fallback` is a list, '' for automatic, or 'none'. */
  const save = useCallback(
    async (patch: { search_provider?: string; search_fallback?: string }) => {
      setProblem('')
      if (mode !== 'live') {
        const now = demo.current
        if (patch.search_provider !== undefined) now.primary = patch.search_provider || 'deepseek'
        if (patch.search_fallback !== undefined) {
          now.automatic = patch.search_fallback === ''
          now.fallback = now.automatic ? [] : patch.search_fallback === 'none' ? [] : patch.search_fallback.split(',')
        }
        now.fallback = now.fallback.filter((id) => id !== now.primary)
        now.effective = [now.primary, ...now.fallback.filter((id) => now.providers.find((p) => p.id === id)?.ready)]
        setDoc(structuredClone(now))
        return
      }
      try {
        await put('/api/prefs', patch)
        notifyAgentsChanged()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not save the choice.')
      }
      await load()
    },
    [mode, load],
  )

  /** One query through one provider alone. The reader presses it; a hosted provider answers at their cost. */
  const test = useCallback(
    async (id: string) => {
      setTested((now) => ({ ...now, [id]: 'testing' }))
      if (mode !== 'live') {
        const row = demo.current.providers.find((p) => p.id === id)
        const ok = Boolean(row?.ready)
        window.setTimeout(() => {
          setTested((now) => ({
            ...now,
            [id]: ok
              ? {
                  provider: id,
                  label: row?.label ?? id,
                  query: 'reliability of home electric heaters',
                  ok,
                  ms: 840,
                  error: '',
                  results: [
                    { title: 'Electric heater long-term test', url: 'https://reviews.example/heater', site: 'reviews.example' },
                    { title: 'Why my heater trips the breaker', url: 'https://forum.example/t/884', site: 'forum.example' },
                    { title: 'Recall notice: fan heater, model 4100', url: 'https://safety.example/recalls/4100', site: 'safety.example' },
                  ],
                }
              : { provider: id, label: row?.label ?? id, query: '', ok, ms: 0, error: `${row?.label ?? id} needs a key. Add it under Keys.`, results: [] },
          }))
        }, 500)
        return
      }
      try {
        const result = await post<SearchTest>('/api/search-providers/test', { provider: id }, 40000)
        setTested((now) => ({ ...now, [id]: result }))
      } catch (error) {
        const why = error instanceof Error ? error.message : 'The test did not finish.'
        setTested((now) => ({ ...now, [id]: { provider: id, label: id, query: '', ok: false, ms: 0, error: why, results: [] } }))
      }
      await load()
    },
    [mode, load],
  )

  return { doc, problem, tested, save, test, reload: load }
}

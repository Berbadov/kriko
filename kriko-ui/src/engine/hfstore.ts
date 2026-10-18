import { useCallback, useEffect, useRef, useState } from 'react'
import { get } from './api'
import { useEngine } from './Engine'

/** Models on Hugging Face that Ollama can pull. The list is read from the web
 *  only when the reader asks, and a download starts only from a button. */

export interface HfModel {
  repo: string
  downloads: number
  likes: number
  params_b: number | null
  license: string | null
  updated: string | null
  context: number | null
}

export interface HfQuant {
  quant: string
  bytes: number
  pull: string
}

export type HfSort = 'downloads' | 'likes' | 'new'

export interface HfFilters {
  query: string
  sort: HfSort
  /** Parameter range in billions; `null` is open. */
  min: number | null
  max: number | null
  license: string
}

export const NO_FILTERS: HfFilters = { query: '', sort: 'downloads', min: null, max: null, license: '' }

const DEMO_MODELS: HfModel[] = [
  { repo: 'Qwen/Qwen3-8B-GGUF', downloads: 607951, likes: 331, params_b: 8.2, license: 'apache-2.0', updated: '2025-05-21', context: 40960 },
  { repo: 'bartowski/gemma-2-9b-it-GGUF', downloads: 412300, likes: 210, params_b: 9.2, license: 'gemma', updated: '2025-02-02', context: 8192 },
  { repo: 'unsloth/Mistral-Small-24B-Instruct-2501-GGUF', downloads: 188200, likes: 97, params_b: 23.6, license: 'apache-2.0', updated: '2025-01-31', context: 32768 },
  { repo: 'microsoft/phi-4-gguf', downloads: 95400, likes: 160, params_b: 14.7, license: 'mit', updated: '2025-01-08', context: 16384 },
]

const demoQuants = (repo: string): HfQuant[] =>
  [
    ['Q4_K_M', 5.0e9],
    ['Q5_K_M', 5.9e9],
    ['Q6_K', 6.7e9],
    ['Q8_0', 8.7e9],
  ].map(([quant, bytes]) => ({ quant: quant as string, bytes: bytes as number, pull: `hf.co/${repo}:${quant}` }))

const within = (row: HfModel, filters: HfFilters) =>
  (!filters.query.trim() || row.repo.toLowerCase().includes(filters.query.trim().toLowerCase())) &&
  (filters.min === null || (row.params_b !== null && row.params_b >= filters.min)) &&
  (filters.max === null || (row.params_b !== null && row.params_b <= filters.max)) &&
  (!filters.license || row.license === filters.license)

export function useHfStore() {
  const { mode } = useEngine()
  const [items, setItems] = useState<HfModel[] | null>(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)
  const [quants, setQuants] = useState<Record<string, HfQuant[] | 'loading' | string>>({})
  const alive = useRef(true)
  const latest = useRef(0)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  /** Search with these filters. Called by a button or a changed filter, never by a timer. */
  const search = useCallback(
    async (filters: HfFilters) => {
      const turn = ++latest.current
      setProblem('')
      setBusy(true)
      try {
        if (mode !== 'live') {
          const rows = DEMO_MODELS.filter((row) => within(row, filters))
          const key = filters.sort === 'likes' ? 'likes' : filters.sort === 'new' ? 'updated' : 'downloads'
          rows.sort((a, b) => (key === 'updated' ? String(b.updated).localeCompare(String(a.updated)) : b[key] - a[key]))
          if (latest.current === turn) setItems(rows)
          return
        }
        const params = new URLSearchParams({ sort: filters.sort, limit: '24' })
        if (filters.query.trim()) params.set('q', filters.query.trim())
        if (filters.min !== null) params.set('min_b', String(filters.min))
        if (filters.max !== null) params.set('max_b', String(filters.max))
        if (filters.license) params.set('licence', filters.license)
        const data = await get<{ items: HfModel[] }>(`/api/hf-models?${params}`, 20000)
        if (alive.current && latest.current === turn) setItems(data.items)
      } catch (error) {
        if (alive.current && latest.current === turn) setProblem(error instanceof Error ? error.message : 'Could not read Hugging Face.')
      } finally {
        if (alive.current && latest.current === turn) setBusy(false)
      }
    },
    [mode],
  )

  /** The quantisations of one repository, read when the reader opens its row. */
  const openRepo = useCallback(
    async (repo: string) => {
      if (quants[repo] && quants[repo] !== 'loading' && typeof quants[repo] !== 'string') return
      setQuants((now) => ({ ...now, [repo]: 'loading' }))
      try {
        const rows =
          mode !== 'live'
            ? demoQuants(repo)
            : (await get<{ items: HfQuant[] }>(`/api/hf-models/files?repo=${encodeURIComponent(repo)}`, 20000)).items
        if (alive.current) setQuants((now) => ({ ...now, [repo]: rows.length ? rows : 'This repository has no file Ollama can run.' }))
      } catch (error) {
        if (alive.current) setQuants((now) => ({ ...now, [repo]: error instanceof Error ? error.message : 'Could not read the files.' }))
      }
    },
    [mode, quants],
  )

  return { items, problem, busy, quants, search, openRepo }
}

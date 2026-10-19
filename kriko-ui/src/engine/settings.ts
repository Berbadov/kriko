import { useCallback, useEffect, useRef, useState } from 'react'
import { del, get, notifyAgentsChanged, post, put } from './api'
import { useEngine } from './Engine'

/** What the Settings and Agents panels read and write. Live, it is the engine's
 *  `/api/prefs`, `/api/keys` and `/api/costs`. In demo mode the same shapes are
 *  kept in the window, so the panels can be designed without an engine. */

export interface AgentRow {
  id: string
  label: string
  path?: string
  local?: boolean
  llm: string
  llms: string[]
  llms_note?: string
  effort: string
  efforts: string[]
}

export interface PrefsDoc {
  chosen: Record<string, string>
  effective: { ready: boolean; reason: string; harness: string; harness_ready: boolean; harness_note: string }
  harnesses: AgentRow[]
  unusable: { id: string; label: string; why: string }[]
  missing: { id: string; label: string; install_hint?: string }[]
  source_kinds: { id: string; label: string }[]
  research: { sources: number; kinds: string[] }
  search_providers: { id: string; label: string; ready: boolean }[]
}

export interface KeyRow {
  id: string
  label: string
  purpose: string
  present: boolean
  /** The last characters of the key, never the key. */
  hint: string
  source: string
}

export interface KeysDoc {
  providers: KeyRow[]
  ready: boolean
}

export interface Spent {
  days: number
  runs: number
  tokens: number
  usd: number
}

/** The key the engine stores a choice under, as `app/prefs.py` writes it. */
export const modelKey = (agent: AgentRow) => (agent.local ? 'local_model' : `harness_model_${agent.id}`.replace(/-/g, '_'))
export const effortKey = (agent: AgentRow) => `harness_effort_${agent.id}`.replace(/-/g, '_')

const DEMO_PREFS: PrefsDoc = {
  chosen: { preferred_harness: 'coding', run_concurrency: '2', research_sources: '0', research_source_kinds: 'forums,reviews', search_provider: '' },
  effective: { ready: true, reason: '', harness: 'coding', harness_ready: true, harness_note: '' },
  harnesses: [
    { id: 'coding', label: 'Coding agent', path: 'demo', llm: 'sonnet', llms: ['haiku', 'sonnet', 'opus'], effort: 'low', efforts: ['low', 'medium', 'high'] },
    { id: 'reader', label: 'Reading agent', path: 'demo', llm: '', llms: ['small', 'large'], effort: '', efforts: [] },
    { id: 'local', label: 'Local model', path: 'http://127.0.0.1:11434', local: true, llm: 'gemma4:e2b', llms: ['gemma4:e2b', 'qwen3.5:4b'], effort: '', efforts: [] },
  ],
  unusable: [],
  missing: [{ id: 'other', label: 'Other agent', install_hint: 'Not installed.' }],
  source_kinds: [
    { id: 'forums', label: 'Forums' },
    { id: 'reviews', label: 'Reviews' },
    { id: 'recalls', label: 'Recalls' },
    { id: 'manufacturer', label: 'Maker pages' },
    { id: 'video', label: 'Video' },
    { id: 'news', label: 'News' },
  ],
  research: { sources: 0, kinds: ['forums', 'reviews'] },
  search_providers: [
    { id: 'exa', label: 'Exa', ready: false },
    { id: 'tavily', label: 'Tavily', ready: true },
  ],
}

const DEMO_KEYS: KeysDoc = {
  ready: true,
  providers: [
    { id: 'exa', label: 'Exa', purpose: 'Search words only. Never a page you visited.', present: false, hint: '', source: '' },
    { id: 'tavily', label: 'Tavily', purpose: 'Search words only. Never a page you visited.', present: true, hint: 'a1b2', source: 'file' },
    { id: 'openai', label: 'OpenAI', purpose: 'Reads the pages that research fetched.', present: false, hint: '', source: '' },
  ],
}

export function usePrefsDoc() {
  const { mode, setPreferred } = useEngine()
  const [doc, setDoc] = useState<PrefsDoc | null>(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)
  const demo = useRef<PrefsDoc>(structuredClone(DEMO_PREFS))

  const load = useCallback(
    async (fresh = false) => {
      setProblem('')
      if (mode === 'checking') return
      if (mode !== 'live') {
        setDoc(structuredClone(demo.current))
        return
      }
      setBusy(true)
      try {
        setDoc(await get<PrefsDoc>(fresh ? '/api/prefs?fresh=true' : '/api/prefs', fresh ? 30000 : 8000))
        notifyAgentsChanged()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not read the settings.')
      } finally {
        setBusy(false)
      }
    },
    [mode],
  )

  useEffect(() => {
    void load()
  }, [load])

  /** Store choices. The screen shows them at once, and the engine's answer replaces them. */
  const save = useCallback(
    async (patch: Record<string, string>) => {
      setProblem('')
      setDoc((current) => (current ? { ...current, chosen: { ...current.chosen, ...patch } } : current))
      if ('preferred_harness' in patch) setPreferred(patch.preferred_harness)
      if (mode !== 'live') {
        const now = demo.current
        now.chosen = { ...now.chosen, ...patch }
        for (const agent of now.harnesses) {
          if (patch[modelKey(agent)] !== undefined) agent.llm = patch[modelKey(agent)]
          if (patch[effortKey(agent)] !== undefined) agent.effort = patch[effortKey(agent)]
        }
        if ('research_sources' in patch) now.research.sources = Number(patch.research_sources) || 0
        if ('research_source_kinds' in patch) now.research.kinds = patch.research_source_kinds.split(',').filter(Boolean)
        return
      }
      try {
        setDoc(await put<PrefsDoc>('/api/prefs', patch))
        notifyAgentsChanged()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not save.')
        void load()
      }
    },
    [mode, load, setPreferred],
  )

  return { doc, problem, busy, save, reload: load }
}

export function useKeys() {
  const { mode } = useEngine()
  const [doc, setDoc] = useState<KeysDoc | null>(null)
  const [problem, setProblem] = useState('')
  const [tested, setTested] = useState<Record<string, string>>({})
  const demo = useRef<KeysDoc>(structuredClone(DEMO_KEYS))

  useEffect(() => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setDoc(structuredClone(demo.current))
      return
    }
    get<KeysDoc>('/api/keys')
      .then(setDoc)
      .catch((error: unknown) => setProblem(error instanceof Error ? error.message : 'Could not read the keys.'))
  }, [mode])

  /** The key goes to the engine and is not kept here. The engine never sends it back. */
  const set = useCallback(
    async (id: string, value: string) => {
      setProblem('')
      if (mode !== 'live') {
        const row = demo.current.providers.find((p) => p.id === id)
        if (row) Object.assign(row, { present: true, hint: value.trim().slice(-4), source: 'file' })
        setDoc(structuredClone(demo.current))
        return
      }
      try {
        setDoc(await put<KeysDoc>('/api/keys', { values: { [id]: value } }))
        notifyAgentsChanged()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not save the key.')
      }
    },
    [mode],
  )

  const remove = useCallback(
    async (id: string) => {
      setProblem('')
      setTested((now) => ({ ...now, [id]: '' }))
      if (mode !== 'live') {
        const row = demo.current.providers.find((p) => p.id === id)
        if (row) Object.assign(row, { present: false, hint: '', source: '' })
        setDoc(structuredClone(demo.current))
        return
      }
      try {
        setDoc(await del<KeysDoc>(`/api/keys/${encodeURIComponent(id)}`))
        notifyAgentsChanged()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not remove the key.')
      }
    },
    [mode],
  )

  /** One small call with that key. It is the reader who presses the button. */
  const test = useCallback(
    async (id: string) => {
      setTested((now) => ({ ...now, [id]: 'Testing…' }))
      if (mode !== 'live') {
        setTested((now) => ({ ...now, [id]: 'Works.' }))
        return
      }
      try {
        const result = await post<{ error?: string; detail?: string }>('/api/keys/test', { provider: id })
        setTested((now) => ({ ...now, [id]: result.error ? result.detail || 'Does not work.' : 'Works.' }))
      } catch (error) {
        setTested((now) => ({ ...now, [id]: error instanceof Error ? error.message : 'Does not work.' }))
      }
    },
    [mode],
  )

  return { doc, problem, tested, set, remove, test }
}

export function useSpent() {
  const { mode } = useEngine()
  const [spent, setSpent] = useState<Spent | null>(null)
  useEffect(() => {
    if (mode !== 'live') {
      setSpent({ days: 30, runs: 12, tokens: 184000, usd: 0.42 })
      return
    }
    get<{ spent?: Spent }>('/api/costs')
      .then((r) => setSpent(r.spent ?? null))
      .catch(() => setSpent(null))
  }, [mode])
  return spent
}

export function useAbout() {
  const { mode } = useEngine()
  const [about, setAbout] = useState<{ version: string; folder: string } | null>(null)
  useEffect(() => {
    if (mode !== 'live') {
      setAbout({ version: 'demo', folder: '—' })
      return
    }
    get<{ version?: string; app_state?: string }>('/api/health')
      .then((r) => setAbout({ version: r.version ?? '', folder: (r.app_state ?? '').replace(/[\\/][^\\/]*$/, '') }))
      .catch(() => setAbout(null))
  }, [mode])
  return about
}

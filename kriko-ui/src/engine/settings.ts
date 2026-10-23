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
  llm_hint?: string
  llm_selectable?: boolean
  model_freeform?: boolean
  effort: string
  efforts: string[]
  /** Which web search this agent uses: 'own' or 'kriko'. */
  search?: string
  search_choices?: { id: string; label: string }[]
}

export interface PrefsDoc {
  chosen: Record<string, string>
  effective: { ready: boolean; reason: string; harness: string; harness_ready: boolean; harness_note: string }
  harnesses: AgentRow[]
  unusable: { id: string; label: string; why: string }[]
  missing: { id: string; label: string; install_hint?: string }[]
  source_kinds: { id: string; label: string }[]
  research: {
    sources: number
    kinds: string[]
    thoroughness: number
    validation_sensitivity: number
  }
  search_providers: { id: string; label: string; ready: boolean }[]
  classification_providers: { id: string; label: string; ready: boolean }[]
  market_regions: { id: string; label: string }[]
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
  unpriced_runs?: number
}

/** The key the engine stores a choice under, as `app/prefs.py` writes it. */
export const modelKey = (agent: AgentRow) => (agent.local ? 'local_model' : `harness_model_${agent.id}`.replace(/-/g, '_'))
export const effortKey = (agent: AgentRow) => `harness_effort_${agent.id}`.replace(/-/g, '_')
/** The third dial: whose web search this agent uses (`prefs.HARNESS_SEARCH_KEYS`). */
export const searchKey = (agent: AgentRow) => `harness_search_${agent.id}`.replace(/-/g, '_')

const DEMO_SEARCHES = [
  { id: 'own', label: "The agent's own web search" },
  { id: 'kriko', label: "Kriko's web search (experimental)" },
]

const DEMO_PREFS: PrefsDoc = {
  chosen: { preferred_harness: 'coding', run_concurrency: '2', research_sources: '0', research_source_kinds: 'forums,reviews', search_provider: '', chat_product_only: '0' },
  effective: { ready: true, reason: '', harness: 'coding', harness_ready: true, harness_note: '' },
  harnesses: [
    { id: 'coding', label: 'Coding agent', path: 'demo', llm: 'sonnet', llms: ['haiku', 'sonnet', 'opus'], effort: 'low', efforts: ['low', 'medium', 'high'], search: 'own', search_choices: DEMO_SEARCHES },
    { id: 'reader', label: 'Reading agent', path: 'demo', llm: '', llms: ['small', 'large'], effort: '', efforts: [], search: 'own', search_choices: DEMO_SEARCHES },
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
  research: {
    sources: 0,
    kinds: ['forums', 'reviews'],
    thoroughness: 50,
    validation_sensitivity: 50,
  },
  search_providers: [
    { id: 'exa', label: 'Exa', ready: false },
    { id: 'tavily', label: 'Tavily', ready: true },
  ],
  classification_providers: [
    { id: 'agent', label: 'Selected agent (default)', ready: true },
    { id: 'typesafe', label: 'Jev (TypeSafe)', ready: false },
  ],
  market_regions: [
    { id: 'auto', label: 'Automatic' },
    { id: 'US', label: 'United States' },
    { id: 'CA', label: 'Canada' },
    { id: 'GB', label: 'United Kingdom' },
    { id: 'EU', label: 'European Union' },
    { id: 'AU', label: 'Australia' },
    { id: 'JP', label: 'Japan' },
    { id: 'TR', label: 'Türkiye' },
  ],
}

/** The engine's key providers, as `app/keys.py` declares them in its `PROVIDERS`
 *  tuple: the same ids in the same order, because the Keys panel draws whatever
 *  list it is handed and demo mode hands it this one. A provider missing here is
 *  a row the reader cannot see and cannot set while the window says demo — this
 *  list had drifted, with no anthropic, mistral or mercury, and the hosted page
 *  reader's `parallel` arrived to the engine only.
 *
 *  Demo mode has no engine to ask, so the rows themselves stay static; the
 *  contract they copy is the ids, and `tests/demo_engine_lists.test.mjs` reads
 *  that tuple and fails while the two disagree. Adding a provider to the engine
 *  is one entry here, and the test is what remembers it. */
const DEMO_KEYS: KeysDoc = {
  ready: true,
  providers: [
    { id: 'exa', label: 'Exa', purpose: 'Search words only. Never a page you visited.', present: false, hint: '', source: '' },
    { id: 'tavily', label: 'Tavily', purpose: 'Search words only. Never a page you visited.', present: true, hint: 'a1b2', source: 'file' },
    { id: 'deepseek', label: 'DeepSeek', purpose: 'Searches when OpenSERP fails or finds nothing. Receives only the words searched.', present: true, hint: 'c3d4', source: 'file' },
    { id: 'parallel', label: 'Parallel (hosted page reader)', purpose: 'Reads a page the plain fetcher was refused, on your own account. Set it and the fallback runs; leave it empty and no page address leaves this machine.', present: false, hint: '', source: '' },
    { id: 'openai', label: 'OpenAI', purpose: 'Reads the pages that research fetched.', present: false, hint: '', source: '' },
    { id: 'anthropic', label: 'Anthropic', purpose: 'The other completion provider. Reads the pages that research fetched.', present: false, hint: '', source: '' },
    { id: 'mistral', label: 'Mistral', purpose: 'Runs a Mistral API agent for the run, and can complete for the paid plane.', present: false, hint: '', source: '' },
    { id: 'mercury', label: 'Mercury', purpose: 'Runs the Mercury API model Kriko Agent uses, and can complete for the paid plane.', present: false, hint: '', source: '' },
    { id: 'proxy', label: 'Proxy login', purpose: 'The user:password your proxies ask for, if they ask. Sent only to the proxies you list.', present: false, hint: '', source: '' },
    { id: 'typesafe', label: 'TypeSafe (Jev)', purpose: 'Used for product classification when selected.', present: false, hint: '', source: '' },
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
      const was = doc?.chosen.preferred_harness
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
        if ('kriko_agent_thoroughness' in patch) now.research.thoroughness = Number(patch.kriko_agent_thoroughness) || 0
        if ('kriko_agent_validation_sensitivity' in patch) now.research.validation_sensitivity = Number(patch.kriko_agent_validation_sensitivity) || 0
        return
      }
      try {
        setDoc(await put<PrefsDoc>('/api/prefs', patch))
        notifyAgentsChanged()
      } catch (error) {
        const why = error instanceof Error ? error.message : 'Could not save.'
        // Read the saved settings back first: `load` clears the problem as it starts, and the
        // message was gone before it was drawn. The composer's agent goes back to the saved one too.
        await load()
        setProblem(why)
        if ('preferred_harness' in patch && was) setPreferred(was)
      }
    },
    [mode, load, setPreferred, doc],
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

/** Someone else's keys, in this app only (`src/app/sharekeys.py`). */
export interface SharedStatus {
  /** Whether this build carries a pepper — without one a code is not app-bound. */
  bound: boolean
  /** How the opened grant is kept here: 'dpapi' on Windows, else 'file'. */
  device: string
  grant: { present: boolean; label: string; providers: string[]; state: string }
  trial: { limit: number; used: number; left: number; available: boolean }
  providers: string[]
}

const DEMO_SHARED: SharedStatus = {
  bound: true,
  device: 'demo',
  grant: { present: false, label: '', providers: [], state: '' },
  trial: { limit: 10, used: 3, left: 7, available: true },
  providers: ['mercury', 'deepseek'],
}

export function useSharedAccess() {
  const { mode } = useEngine()
  const [doc, setDoc] = useState<SharedStatus | null>(null)
  const [problem, setProblem] = useState('')
  /** The code the owner just made, shown once and kept nowhere. */
  const [code, setCode] = useState('')

  const read = useCallback(async () => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setDoc(structuredClone(DEMO_SHARED))
      return
    }
    try {
      setDoc(await get<SharedStatus>('/api/keys/shared/status'))
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not read the shared access.')
    }
  }, [mode])

  useEffect(() => {
    void read()
  }, [read])

  const unlock = useCallback(
    async (accessCode: string, password: string, label: string) => {
      setProblem('')
      if (mode !== 'live') {
        setDoc({ ...structuredClone(DEMO_SHARED), grant: { present: true, label, providers: ['mercury', 'deepseek'], state: 'shared' } })
        return
      }
      try {
        await post('/api/keys/shared/unlock', { code: accessCode, password, label })
        await read()
        notifyAgentsChanged()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'That code did not open.')
      }
    },
    [mode, read],
  )

  const forget = useCallback(async () => {
    setProblem('')
    if (mode !== 'live') {
      setDoc(structuredClone(DEMO_SHARED))
      return
    }
    try {
      setDoc(await del<SharedStatus>('/api/keys/shared'))
      notifyAgentsChanged()
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not forget it.')
    }
  }, [mode])

  const make = useCallback(
    async (password: string) => {
      setProblem('')
      setCode('')
      if (mode !== 'live') {
        setCode('demo-code-not-a-real-one')
        return
      }
      try {
        const made = await post<{ code: string }>('/api/keys/shared/make', { password })
        setCode(made.code)
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not make a code.')
      }
    },
    [mode],
  )

  return { doc, problem, code, unlock, forget, make }
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

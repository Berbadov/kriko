import { useCallback, useEffect, useRef, useState } from 'react'
import { get, post, seg, type ApiJob } from './api'
import { useEngine } from './Engine'
import { followJob } from './jobs'

/** The models on this computer, the computer itself, and getting more models.
 *  Live, these are `/api/machine` and `/api/local-models`. In demo mode the same
 *  shapes are kept in the window. */

/** The steps to run vLLM here, with the torch build that the driver can run. */
export interface VllmPlan {
  ready: boolean
  build: string | null
  driver_cuda: string | null
  summary: string
  model?: string
  steps: { title: string; where: string; command: string }[]
  notes: string[]
}

/** A vLLM server that answers, found by its address. */
export interface VllmServer {
  url: string
  models: string[]
}

export interface Machine {
  cuda?: { driver: string | null }
  vllm?: VllmPlan
  /** Every field is `null` when the machine did not report it. */
  gpu?: { name: string | null; vram_total_mb: number | null; vram_used_mb: number | null } | null
  ram_total_mb?: number | null
  cpu?: { name: string | null; cores: number | null } | null
  runtimes: { id: string; name: string; installed: boolean; can_pull: boolean }[]
}

export interface Model {
  name: string
  /** The server's own count. `null` or 0 when it did not say. */
  size_bytes: number | null
  params: string
  quant: string
}

export interface Library {
  name: string
  sizes: string[]
  about: string
}

export interface Pull {
  model: string
  progress: number
  message: string
  /** Set when the download ended without a model. */
  error: string
}

const DEMO_VLLM: VllmPlan = {
  ready: true,
  build: 'cu130',
  driver_cuda: '13.4',
  summary: 'The driver supports CUDA 13.4. Use the CUDA 13.0 build.',
  model: 'Qwen/Qwen2.5-3B-Instruct',
  steps: [
    { title: 'Install WSL 2 with Ubuntu, once', where: 'PowerShell', command: 'wsl --install -d Ubuntu' },
    { title: 'Install uv', where: 'Ubuntu', command: 'curl -LsSf https://astral.sh/uv/install.sh | sh' },
    { title: 'Install vLLM for CUDA 13.0', where: 'Ubuntu', command: 'uv pip install vllm --torch-backend=cu130' },
    { title: 'Start the server', where: 'Ubuntu', command: 'vllm serve Qwen/Qwen2.5-3B-Instruct --host 127.0.0.1 --port 8000 --max-model-len 4096' },
  ],
  notes: ['vLLM does not run on Windows itself. WSL 2 shares the Windows NVIDIA driver, so do not install a driver in Ubuntu.'],
}
const DEMO_MACHINE: Machine = {
  gpu: { name: 'Demo GPU 8 GB', vram_total_mb: 8192, vram_used_mb: 1400 },
  ram_total_mb: 16384,
  cpu: { name: 'Demo CPU', cores: 12 },
  cuda: { driver: '13.4' },
  vllm: DEMO_VLLM,
  runtimes: [
    { id: 'ollama', name: 'Ollama', installed: true, can_pull: true },
    { id: 'lmstudio', name: 'LM Studio', installed: false, can_pull: false },
  ],
}
const DEMO_MODELS: Model[] = [
  { name: 'gemma4:e2b', size_bytes: 4587156505, params: '4.6B', quant: 'Q4_K_M' },
  { name: 'qwen3.5:4b', size_bytes: 3324173934, params: '4.2B', quant: 'Q4_K_M' },
]
const DEMO_RECOMMENDED = 'gemma4:e2b'
const DEMO_LIBRARY: Library[] = [
  { name: 'llama3.1', sizes: ['8b', '70b'], about: 'A general model from Meta.' },
  { name: 'qwen2.5', sizes: ['3b', '7b', '14b'], about: 'A model for many languages.' },
  { name: 'gemma3', sizes: ['4b', '12b', '27b'], about: 'A small model from Google.' },
]

export function useLocal() {
  const { mode } = useEngine()
  const [machine, setMachine] = useState<Machine | null>(null)
  const [machineProblem, setMachineProblem] = useState('')
  const [runtime, setRuntime] = useState<{ runtime: string | null; url: string | null } | null>(null)
  const [models, setModels] = useState<Model[]>([])
  /** The model the engine recommends, and whether the server already holds it. Named by the engine, never here. */
  const [recommended, setRecommended] = useState<{ model: string; installed: boolean }>({ model: '', installed: false })
  /** False until the installed list has been read once, so the screen can draw rows that are loading. */
  const [modelsLoaded, setModelsLoaded] = useState(false)
  const [library, setLibrary] = useState<Library[] | null>(null)
  const [libraryProblem, setLibraryProblem] = useState('')
  const [pull, setPull] = useState<Pull | null>(null)
  const [problem, setProblem] = useState('')
  const [starting, setStarting] = useState(false)
  const [vllm, setVllm] = useState<VllmServer | null>(null)
  const [checking, setChecking] = useState(false)
  const alive = useRef(true)
  const job = useRef('')

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const readModels = useCallback(async () => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setRuntime({ runtime: 'ollama', url: 'http://127.0.0.1:11434' })
      setModels(DEMO_MODELS)
      setRecommended({ model: DEMO_RECOMMENDED, installed: DEMO_MODELS.some((row) => row.name === DEMO_RECOMMENDED) })
      setModelsLoaded(true)
      return
    }
    try {
      const data = await get<{ runtime: string | null; url: string | null; models: Model[]; recommended_model?: string; recommended_installed?: boolean }>('/api/local-models', 8000)
      if (!alive.current) return
      setRuntime({ runtime: data.runtime, url: data.url })
      setModels(data.models)
      setRecommended({ model: data.recommended_model ?? '', installed: Boolean(data.recommended_installed) })
    } catch (error) {
      if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not read the models.')
    } finally {
      if (alive.current) setModelsLoaded(true)
    }
  }, [mode])

  /** The vLLM server, if one answers at its address. */
  const readVllm = useCallback(async () => {
    if (mode !== 'live') return
    try {
      const plane = await get<{ servers?: { name: string; url: string; up: boolean; models: string[] }[] }>('/api/local-plane', 10000)
      if (!alive.current) return
      const found = plane.servers?.find((row) => row.name === 'vLLM' && row.up)
      setVllm(found ? { url: found.url, models: found.models } : null)
    } catch {
      /* the card then shows the steps, which is the safe answer */
    }
  }, [mode])

  /** The computer, read once on mount: a subprocess and a few stat calls, cached by the engine for a minute. */
  const readMachine = useCallback(async () => {
    setMachineProblem('')
    if (mode === 'checking') return
    if (mode !== 'live') {
      setMachine(DEMO_MACHINE)
      return
    }
    try {
      const data = await get<Machine>('/api/machine', 10000)
      if (alive.current) setMachine(data)
    } catch (error) {
      if (alive.current) setMachineProblem(error instanceof Error ? error.message : 'Could not read this computer.')
    }
  }, [mode])

  // Only the computer and the installed models are read on mount. The vLLM probe
  // waits for a press, the public library for the reader to ask, and neither
  // downloads anything.
  useEffect(() => {
    if (mode === 'checking') return
    void readMachine()
    void readModels()
  }, [mode, readMachine, readModels])

  /** Ask the machine again, after the reader changed a driver or started a server. */
  const recheck = useCallback(async () => {
    setChecking(true)
    try {
      if (mode === 'live') {
        const data = await get<Machine>('/api/machine?fresh=true', 15000)
        if (alive.current) setMachine(data)
        await readVllm()
      }
    } catch {
      /* the last answer stays */
    } finally {
      if (alive.current) setChecking(false)
    }
  }, [mode, readVllm])

  /** The public list is read from the web, so it waits for the reader to ask. */
  const openLibrary = useCallback(async () => {
    setLibraryProblem('')
    if (mode !== 'live') {
      setLibrary(DEMO_LIBRARY)
      return
    }
    try {
      const data = await get<{ library?: Library[]; catalogue_error?: string }>('/api/local-models?available=true', 20000)
      if (!alive.current) return
      setLibrary(data.library ?? [])
      if (data.catalogue_error) setLibraryProblem(data.catalogue_error)
    } catch (error) {
      if (alive.current) setLibraryProblem(error instanceof Error ? error.message : 'Could not read the list.')
    }
  }, [mode])

  const startPull = useCallback(
    async (model: string) => {
      setProblem('')
      setPull({ model, progress: 0, message: 'Starting…', error: '' })
      if (mode !== 'live') {
        for (let step = 1; step <= 10 && alive.current; step++) {
          await new Promise((resolve) => window.setTimeout(resolve, 250))
          setPull({ model, progress: step / 10, message: 'Downloading', error: '' })
        }
        if (!alive.current) return
        setModels((now) => [...now, { name: model, size_bytes: 2e9, params: 'n/a', quant: '' }])
        setPull(null)
        return
      }
      try {
        const started = await post<{ job_id: string }>('/api/local-models/pull', { runtime: 'ollama', model })
        job.current = started.job_id
        const end = await followJob(
          started.job_id,
          (reading: ApiJob) => setPull({ model, progress: reading.progress ?? 0, message: reading.message ?? '', error: '' }),
          () => alive.current,
        )
        if (!end) return
        if (end.state === 'succeeded') setPull(null)
        else setPull({ model, progress: end.progress ?? 0, message: '', error: end.state === 'cancelled' ? 'Stopped.' : end.message || 'The download failed.' })
      } catch (error) {
        setPull({ model, progress: 0, message: '', error: error instanceof Error ? error.message : 'The download failed.' })
      } finally {
        job.current = ''
        void readModels()
      }
    },
    [mode, readModels],
  )

  const stopPull = useCallback(async () => {
    if (mode === 'live' && job.current) await post(`/api/jobs/${seg(job.current)}/cancel`).catch(() => undefined)
  }, [mode])

  const dismissPull = useCallback(() => setPull(null), [])

  const remove = useCallback(
    async (model: string) => {
      setProblem('')
      if (mode === 'live') {
        try {
          await post('/api/local-models/remove', { runtime: 'ollama', model })
        } catch (error) {
          setProblem(error instanceof Error ? error.message : 'Could not remove it.')
          return
        }
      }
      setModels((now) => now.filter((row) => row.name !== model))
      void readModels()
    },
    [mode, readModels],
  )

  const startRuntime = useCallback(async () => {
    setProblem('')
    setStarting(true)
    try {
      if (mode === 'live') {
        const started = await post<{ job_id: string }>('/api/local-models/start')
        const ended = await followJob(started.job_id, () => undefined, () => alive.current)
        // The engine says why it could not start it ("Ollama is not installed"); the button used to
        // go quiet and show nothing.
        if (ended && ended.state !== 'succeeded') throw new Error(ended.message || 'Could not start it.')
      }
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not start it.')
    } finally {
      if (alive.current) setStarting(false)
      void readModels()
    }
  }, [mode, readModels])

  return { machine, machineProblem, readMachine, runtime, models, modelsLoaded, recommended, library, libraryProblem, pull, problem, starting, vllm, checking, recheck, readVllm, readModels, openLibrary, startPull, stopPull, dismissPull, remove, startRuntime }
}

/** The answer to one question put to the local model. */
export interface TryAnswer {
  text: string
  model: string
  seconds: number
  /** `null` when the server counted no tokens: no speed is then claimed. */
  output_tokens: number | null
  tokens_per_second: number | null
  truncated: boolean
}

/** One short question to the model on this computer. It runs only when `ask` is
 *  called, and the engine bounds it (a short reply, a minute's wait). It is
 *  local, so it costs nothing. */
export function useTryLocal() {
  const { mode } = useEngine()
  const [busy, setBusy] = useState(false)
  const [answer, setAnswer] = useState<TryAnswer | null>(null)
  const [problem, setProblem] = useState('')
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const ask = useCallback(
    async (prompt: string, model = '') => {
      setBusy(true)
      setProblem('')
      setAnswer(null)
      try {
        if (mode !== 'live') {
          await new Promise((resolve) => window.setTimeout(resolve, 600))
          if (alive.current) setAnswer({ text: 'Hello. I am running on this computer.', model: model || DEMO_RECOMMENDED, seconds: 2.4, output_tokens: 29, tokens_per_second: 12.1, truncated: false })
          return
        }
        const reply = await post<{ ok: boolean } & TryAnswer>('/api/local-models/try', { prompt, ...(model ? { model } : {}) }, 90000)
        if (alive.current) setAnswer(reply)
      } catch (error) {
        if (alive.current) setProblem(error instanceof Error ? error.message : 'The model did not answer.')
      } finally {
        if (alive.current) setBusy(false)
      }
    },
    [mode],
  )

  return { busy, answer, problem, ask }
}

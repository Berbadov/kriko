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
  gpu?: { name: string; vram_total_mb: number; vram_used_mb: number }
  ram_total_mb?: number
  cpu?: { name: string; cores: number }
  runtimes: { id: string; name: string; installed: boolean; can_pull: boolean }[]
}

export interface Model {
  name: string
  size_bytes: number
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
const DEMO_LIBRARY: Library[] = [
  { name: 'llama3.1', sizes: ['8b', '70b'], about: 'A general model from Meta.' },
  { name: 'qwen2.5', sizes: ['3b', '7b', '14b'], about: 'A model for many languages.' },
  { name: 'gemma3', sizes: ['4b', '12b', '27b'], about: 'A small model from Google.' },
]

export function useLocal() {
  const { mode } = useEngine()
  const [machine, setMachine] = useState<Machine | null>(null)
  const [runtime, setRuntime] = useState<{ runtime: string | null; url: string | null } | null>(null)
  const [models, setModels] = useState<Model[]>([])
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
    if (mode !== 'live') {
      setRuntime({ runtime: 'ollama', url: 'http://127.0.0.1:11434' })
      setModels(DEMO_MODELS)
      return
    }
    try {
      const data = await get<{ runtime: string | null; url: string | null; models: Model[] }>('/api/local-models', 8000)
      if (!alive.current) return
      setRuntime({ runtime: data.runtime, url: data.url })
      setModels(data.models)
    } catch (error) {
      if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not read the models.')
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

  useEffect(() => {
    if (mode !== 'live') {
      setMachine(DEMO_MACHINE)
    } else {
      get<Machine>('/api/machine', 10000)
        .then((data) => alive.current && setMachine(data))
        .catch(() => undefined)
    }
    void readModels()
    void readVllm()
  }, [mode, readModels, readVllm])

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
        setModels((now) => [...now, { name: model, size_bytes: 2e9, params: '—', quant: '' }])
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
        await followJob(started.job_id, () => undefined, () => alive.current)
      }
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not start it.')
    } finally {
      if (alive.current) setStarting(false)
      void readModels()
    }
  }, [mode, readModels])

  return { machine, runtime, models, library, libraryProblem, pull, problem, starting, vllm, checking, recheck, openLibrary, startPull, stopPull, dismissPull, remove, startRuntime }
}

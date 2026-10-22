import { useCallback, useEffect, useRef, useState } from 'react'
import { get, notifyAgentsChanged, post, put } from './api'
import { useEngine } from './Engine'

/** The program the local model is served by, and a check that it answers.
 *  Live, the engine's `/api/local-runtimes`; the choice is saved with the other
 *  settings (`local_runtime`, `local_url`). Nothing here installs or starts a server. */

export interface RuntimeRow {
  id: string
  name: string
  /** Where the program listens by default. Empty for "any endpoint". */
  url: string
}

export interface RuntimesDoc {
  runtimes: RuntimeRow[]
  chosen: string
  url: string
}

export interface RuntimeCheck {
  url: string
  up: boolean
  models: string[]
  detected: string
  message: string
  busy?: boolean
  loader: { supported: boolean; help: string } | null
}

const DEMO: RuntimesDoc = {
  chosen: '',
  url: '',
  runtimes: [
    { id: 'ollama', name: 'Ollama', url: 'http://127.0.0.1:11434' },
    { id: 'lm-studio', name: 'LM Studio', url: 'http://127.0.0.1:1234' },
    { id: 'llama-server', name: 'llama.cpp server', url: 'http://127.0.0.1:8080' },
    { id: 'vllm', name: 'vLLM', url: 'http://127.0.0.1:8000' },
    { id: 'custom', name: 'Any OpenAI-compatible endpoint', url: '' },
  ],
}

export function useLocalRuntimes() {
  const { mode } = useEngine()
  const [doc, setDoc] = useState<RuntimesDoc | null>(null)
  const [problem, setProblem] = useState('')
  const [checked, setChecked] = useState<RuntimeCheck | 'checking' | null>(null)
  const demo = useRef<RuntimesDoc>(structuredClone(DEMO))

  const load = useCallback(async () => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setProblem('')
      setDoc(structuredClone(demo.current))
      return
    }
    try {
      setDoc(await get<RuntimesDoc>('/api/local-runtimes'))
      setProblem('')
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not read the runtimes.')
    }
  }, [mode])

  useEffect(() => {
    void load()
  }, [load])

  const save = useCallback(
    async (runtime: string, url: string) => {
      setProblem('')
      setChecked(null)
      if (mode !== 'live') {
        demo.current = { ...demo.current, chosen: runtime, url }
        setDoc(structuredClone(demo.current))
        return
      }
      try {
        await put('/api/prefs', { local_runtime: runtime, local_url: url })
        notifyAgentsChanged()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not save the choice.')
      }
      await load()
    },
    [mode, load],
  )

  const check = useCallback(
    async (runtime: string, url: string) => {
      setChecked('checking')
      if (mode !== 'live') {
        const row = demo.current.runtimes.find((one) => one.id === runtime)
        const address = url || row?.url || ''
        window.setTimeout(() => {
          setChecked(
            runtime === 'vllm' || !address
              ? { url: address, up: false, models: [], detected: '', loader: null, message: address ? `Nothing answers at ${address}. Start \`vllm serve <model>\`; the steps for this computer are below.` : 'Type the address the server listens on, for example http://127.0.0.1:1234.' }
              : {
                  url: address,
                  up: true,
                  models: ['gemma4:e2b', 'qwen3.5:4b', 'llama3.2:3b'],
                  detected: runtime === 'ollama' ? 'Ollama' : 'OpenAI-compatible server',
                  message: `${row?.name ?? 'The server'} answers at ${address} and lists 3 models.`,
                  loader: runtime === 'ollama' ? { supported: true, help: 'Ollama applies device, GPU layers and context to the next request.' } : { supported: false, help: "Set GPU offload and context in your runtime's model loader, then reload the model." },
                },
          )
        }, 500)
        return
      }
      try {
        setChecked(await post<RuntimeCheck>('/api/local-runtimes/check', { runtime, url }, 20000))
      } catch (error) {
        setChecked({ url, up: false, models: [], detected: '', loader: null, message: error instanceof Error ? error.message : 'The check did not finish.' })
      }
    },
    [mode],
  )

  return { doc, problem, checked, save, check, reload: load }
}

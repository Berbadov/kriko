/** The engine's HTTP API, from the side of the window. Every call is JSON.
 *  In development Vite forwards `/api` to the engine. The packaged app will
 *  use the port that the sidecar reports. */

const BASE = (import.meta.env.VITE_ENGINE_BASE as string | undefined) ?? ''

export class EngineError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Inside the packaged window the call goes through the shell, which makes it
 *  from outside the page. The engine refuses an origin it does not know, and
 *  a call from the shell carries none. */
export const inShell = () => '__TAURI_INTERNALS__' in window

async function send(method: string, path: string, body: unknown, timeoutMs: number): Promise<{ status: number; text: string }> {
  if (inShell()) {
    const { invoke } = await import('@tauri-apps/api/core')
    const reply = await invoke<{ status: number; body: string }>('engine_request', {
      method,
      path,
      body: body === undefined ? null : JSON.stringify(body),
      timeoutMs,
    })
    return { status: reply.status, text: reply.body }
  }
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(BASE + path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
    return { status: response.status, text: await response.text() }
  } finally {
    window.clearTimeout(timer)
  }
}

async function call<T>(method: string, path: string, body?: unknown, timeoutMs = 15000): Promise<T> {
  try {
    const { status, text } = await send(method, path, body, timeoutMs)
    let data: unknown = null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      /* the body is not JSON; the status below tells the story */
    }
    if (status < 200 || status >= 300) {
      const detail = (data as { detail?: unknown } | null)?.detail
      throw new EngineError(status, typeof detail === 'string' ? detail : `The engine answered ${status}.`)
    }
    // A page that is not JSON is not the engine: a dev server's own index, or a proxy's error page.
    if (data === null && text.trim()) throw new EngineError(0, 'The engine does not answer.')
    return data as T
  } catch (error) {
    if (error instanceof EngineError) throw error
    throw new EngineError(0, 'The engine does not answer.')
  }
}

export const get = <T>(path: string, timeoutMs?: number) => call<T>('GET', path, undefined, timeoutMs)
export const post = <T>(path: string, body?: unknown) => call<T>('POST', path, body ?? {})
export const put = <T>(path: string, body: unknown) => call<T>('PUT', path, body)
export const patch = <T>(path: string, body: unknown) => call<T>('PATCH', path, body)
export const del = <T>(path: string) => call<T>('DELETE', path)

/** A path segment from an id the engine gave us. */
export const seg = (id: string) => encodeURIComponent(id)

// ---- the shapes the interface reads. Fields it does not use are left out. ----

export interface ApiHistoryItem {
  lookup_id: string
  created_at: string
  label: string
  claim_count: number
  category: string
}

export interface ApiQueueItem {
  queue_id: string
  url: string
  name: string
  lookup_id: string
  state: 'waiting' | 'researching' | 'done' | string
  note: string
}

export interface ApiQueue {
  items: ApiQueueItem[]
  /** How many researches the reader allows at once. */
  concurrency?: number
}

export interface ApiTarget {
  subject_id: string
  pack_id: string
}

export interface ApiHarness {
  id: string
  label: string
  local?: boolean
}

export interface ApiStep {
  id: string
  source: string
  label: string
  state: 'running' | 'done' | 'empty' | 'error' | string
  rows: number
  ms: number
}

export interface ApiProduct {
  subject_id: string
  label: string
  claims: number
  identity?: Record<string, unknown>
}

export interface ApiTurn {
  steps?: ApiStep[]
  answer?: string
  products?: ApiProduct[]
}

export interface ApiJob {
  job_id: string
  state: string
  message?: string
  done?: boolean
  /** 0 to 1. */
  progress?: number
  /** The newest thing the agent did, last. */
  feed?: { kind: string; text: string }[]
  result?: ApiTurn | null
}

export interface ApiMessage extends ApiTurn {
  message_id: string
  role: 'reader' | 'agent'
  text: string
}

/** The engine's HTTP API, from the side of the window. Every call is JSON.
 *  In development Vite forwards `/api` to the engine. The packaged app will
 *  use the port that the sidecar reports. */

const BASE = (import.meta.env.VITE_ENGINE_BASE as string | undefined) ?? ''

export const AGENTS_CHANGED_EVENT = 'kriko:agents-changed'

export function notifyAgentsChanged() {
  window.dispatchEvent(new Event(AGENTS_CHANGED_EVENT))
}

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
      const structured = detail && typeof detail === 'object' ? (detail as { message?: string }).message : ''
      throw new EngineError(status, typeof detail === 'string' ? detail : structured || (Array.isArray(detail) ? 'The request contains an invalid or oversized field. Please shorten it and try again.' : `The engine answered ${status}.`))
    }
    // A page that is not JSON is not the engine: a dev server's own index, or a proxy's error page.
    if (data === null && text.trim()) throw new EngineError(0, 'The engine does not answer.')
    return data as T
  } catch (error) {
    if (error instanceof EngineError) throw error
    throw new EngineError(0, error instanceof Error && error.name === 'AbortError' ? 'The request timed out. Reconnect to check whether the work started before sending it again.' : 'Could not reach Kriko. Check the engine connection and try again.')
  }
}

export const get = <T>(path: string, timeoutMs?: number) => call<T>('GET', path, undefined, timeoutMs)
export const post = <T>(path: string, body?: unknown, timeoutMs?: number) => call<T>('POST', path, body ?? {}, timeoutMs)
export const put = <T>(path: string, body: unknown) => call<T>('PUT', path, body)
export const patch = <T>(path: string, body: unknown) => call<T>('PATCH', path, body)
export const del = <T>(path: string) => call<T>('DELETE', path)

/** A path segment from an id the engine gave us. */
export const seg = (id: string) => encodeURIComponent(id)

/** Retain the logical send ID after a lost response, including across reloads. */
export async function postQuestion<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(path + JSON.stringify(body)))
  const key = `kriko.pending.${Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')}`
  let id: string = crypto.randomUUID()
  try { id = sessionStorage.getItem(key) || id; sessionStorage.setItem(key, id) } catch { /* request still carries its identity */ }
  try {
    const result = await post<T>(path, { ...body, client_request_id: id })
    try { sessionStorage.removeItem(key) } catch { /* no persisted identity */ }
    return result
  } catch (error) {
    if (error instanceof EngineError && error.status !== 0) {
      try { sessionStorage.removeItem(key) } catch { /* no persisted identity */ }
    }
    throw error
  }
}

/** Small local artifacts cross the native JSON bridge as base64. */
export async function uploadArtifact<T>(path: string, file: File): Promise<T> {
  if (file.size > 32 * 1024 * 1024) throw new EngineError(413, 'Choose a file up to 32 MB.')
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
  return post<T>(path, { filename: file.name, data: btoa(binary) }, 60000)
}

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

export interface ApiActivity {
  id: string
  kind: 'search' | 'read' | string
  query?: string
  title?: string
  url?: string
  state?: 'done' | 'failed' | string
  search_results?: string[]
  pages_attempted?: number
  pages_read?: number
  attempted?: boolean
  text?: string
  /** The kind of site behind a page that was read, as the engine classified it. */
  trust?: { domain: string; tier: string; label: string; trust: number; standing?: 'trusted' | 'neutral' | 'low' | string }
}

export interface ApiFeedEvent {
  kind: string
  text: string
}

export interface ApiProduct {
  subject_id: string
  label: string
  claims: number
  identity?: Record<string, unknown>
}

export interface ApiQuestion {
  id: string
  ask: string
  options: string[]
  key?: string
  why?: string
}

/** What a turn spent and how full the model's window is. A field a plane did not report is null. */
export interface ApiUsage {
  spent_usd?: number | null
  tokens?: number | null
  tokens_in?: number | null
  tokens_out?: number | null
  usage?: { calls?: number; peak_in?: number | null }
  context?: {
    model?: string
    window?: number | null
    window_source?: string
    used?: number | null
    state?: 'measured' | 'not_reported' | 'pending' | string
    fill?: number | null
    history?: { messages?: number; sent?: number; trimmed?: boolean; dropped_replies?: number; omitted_requests?: number }
  }
}

export interface ApiTurn extends ApiUsage {
  steps?: ApiStep[]
  activity?: ApiActivity[]
  sources?: string[]
  answer?: string
  products?: ApiProduct[]
  followups?: string[]
  /** The one question a turn asked instead of answering. */
  questions?: ApiQuestion[]
  /** The answer is final although the job may still be naming follow-ups. */
  answer_final?: boolean
}

export interface ApiJob {
  job_id: string
  state: string
  message?: string
  done?: boolean
  /** 0 to 1. */
  progress?: number
  /** The newest thing the agent did, last. */
  feed?: ApiFeedEvent[]
  result?: ApiTurn | null
}

export interface ApiMessage extends ApiTurn {
  feed?: ApiFeedEvent[]
  message_id: string
  role: 'reader' | 'agent'
  text: string
  /** The agent that wrote the answer. Empty for a message from before it was kept. */
  agent?: { id?: string; label?: string; model?: string }
  /** What the turn spent, read back from the job that answered it. */
  spend?: ApiUsage
}

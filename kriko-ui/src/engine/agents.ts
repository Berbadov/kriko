import { get, post, seg } from './api'

/**
 * The agent-integration surface, from the window's side.
 *
 * `src/app/web/routers/agent.py` has answered all of this since the research
 * protocol got an address, and until now no screen called any of it: the
 * window could list the agents it had discovered and could not read the
 * market, wire a harness, ask for the protocol, check that a harness can run
 * one, or install a CLI. So this module is the one place those calls are
 * named — which is also what the repository's route guard
 * (`src/app/tests/test_the_clients_call_routes_that_exist.py`) reads, so a
 * route renamed on one side fails there rather than at a reader's press.
 *
 * Two rules hold the screen honest:
 *
 * * **Reads may happen on mount; everything else is a press.** `agent-market`,
 *   `agent-targets` and `agent-skill` change nothing on disk and are safe the
 *   moment the panel opens. Connect writes into the reader's own harness
 *   config, the skill refresh rewrites a file, install runs a vendor installer
 *   as a job, and verify *starts a process* — none of those may happen because
 *   a drawer opened.
 * * **No screen invents a row.** Every id, label, state and reason drawn here
 *   comes back from the engine; where a call answers nothing, the panel says
 *   the engine reported nothing rather than filling the gap with a list.
 */

export type MarketKind = 'local' | 'api' | 'cli'
/** `ready`, `needs_setup` or `not_installed`, as `agent._market_row` sets it. */
export type MarketStanding = 'ready' | 'needs_setup' | 'not_installed' | string
/** The one thing left to press: `use`, `connect`, `install` or `setup`. */
export type MarketAction = 'use' | 'connect' | 'install' | 'setup' | string
export type Wiring = 'connected' | 'stale' | 'absent' | 'unreadable' | ''
export type TargetStanding = 'connected' | 'stale' | 'absent' | 'unreadable' | string

/** Whether this harness has the current protocol on disk (`agentconfig.skill_status`). */
export interface SkillStatus {
  supported: boolean
  path: string | null
  present: boolean
  stale: boolean
}

/** One row of `GET /api/agent-market`. */
export interface MarketAgent {
  id: string
  label: string
  kind: MarketKind
  state: MarketStanding
  /** The engine's own sentence for why it is not ready, or what a run bills. */
  detail: string
  /** How this installation knows: a binary, an address, or the command it looked for. */
  where: string
  wiring: Wiring
  action: MarketAction
  can_install: boolean
  url: string
  chosen: boolean
  local: boolean
}

export interface MarketDoc {
  agents: MarketAgent[]
  chosen: string
}

/** One row of `GET /api/agent-targets`. */
export interface AgentTarget {
  id: string
  label: string
  /** The config file this harness reads its MCP servers from. */
  path: string
  exists: boolean
  state: TargetStanding
  detail?: string
  skill: SkillStatus
}

export interface TargetsDoc {
  server_name: string
  store: string
  targets: AgentTarget[]
}

export interface SkillStep {
  tool: string
  input: string
  output: string
}

/** `GET /api/agent-skill`: the protocol as this installation would write it. */
export interface SkillDoc {
  name: string
  steps: SkillStep[]
  body: string
}

/** `POST /api/agent-targets/{id}/connect`: the harness as it stands now, and
 *  where the protocol went (`null` where it has nowhere to put one). The
 *  engine's own response reuses the key `skill` here for the *path* it just
 *  wrote, where `GET /api/agent-targets` uses it for the protocol's status —
 *  two different shapes under one word, so the two types say so. */
export interface ConnectAnswer extends Omit<AgentTarget, 'skill'> {
  skill: string | null
}

/** `POST /api/agent-targets/{id}/skill`. */
export interface SkillAnswer {
  target: string
  skill: string | null
  status: SkillStatus
}

export type StepState = 'ok' | 'failed' | 'skipped'

export interface VerifyStep {
  id: string
  state: StepState
}

/** `POST /api/agent-verify`. Always a 200: a command that will not start is a
 *  verdict (`ok: false` with the engine's `detail`), not a transport failure. */
export interface VerifyAnswer {
  ok: boolean
  server?: string
  tools?: string[]
  detail?: string
  steps: VerifyStep[]
  log: string
}

/** What a job-starting route answers. `kind` is the engine's own handler name. */
export interface JobRef {
  job_id: string
  kind: string
}

/** The four states one press passes through. `say` is the engine's sentence at
 *  every step; `detail` is a path or a model it named, never a guess. */
export type PressPhase = 'idle' | 'working' | 'done' | 'failed'

export interface Press {
  phase: PressPhase
  say: string
  detail: string
}

export const IDLE: Press = { phase: 'idle', say: '', detail: '' }

export const working = (say: string): Press => ({ phase: 'working', say, detail: '' })

export const finished = (say: string, detail = ''): Press => ({ phase: 'done', say, detail })

/** A failure, in the engine's words. `EngineError` carries the route's own
 *  `detail`; a sentence written here would be a second description of a
 *  failure the engine has already named, and would drift from it. */
export const failed = (error: unknown, fallback: string): Press => ({
  phase: 'failed',
  say: error instanceof Error && error.message ? error.message : fallback,
  detail: '',
})

// ---- the calls. Paths are literal on purpose: `test_the_clients_call_routes_that_exist.py`
// reads this file to know which of the engine's verbs the window uses. ----

/** The market. Read-only, but it probes the CLIs and the local server, so it is
 *  given room rather than the default timeout. */
export const readMarket = () => get<MarketDoc>('/api/agent-market', 20000)

export const readTargets = () => get<TargetsDoc>('/api/agent-targets', 15000)

/** The protocol document. Read-only, and it renders every installed catalog and
 *  the agenda, so it is a press rather than part of opening the panel. */
export const readSkill = () => get<SkillDoc>('/api/agent-skill', 30000)

/** Writes one `mcpServers` entry into that harness's config, then the protocol. */
export const connectTarget = (targetId: string) =>
  post<ConnectAnswer>(`/api/agent-targets/${seg(targetId)}/connect`, {}, 30000)

/** Rewrites one harness's protocol from what is installed right now. */
export const rewriteTargetSkill = (targetId: string) =>
  post<SkillAnswer>(`/api/agent-targets/${seg(targetId)}/skill`, {}, 30000)

/** Starts the advertised command, completes `initialize` and lists its tools.
 *  The engine's own budget for the two reads is 30s, plus the process start. */
export const verifyAgent = () => post<VerifyAnswer>('/api/agent-verify', {}, 60000)

/** A durable id comes back at once; the installer itself is a job the screen
 *  follows with `followJob`, so a long vendor install cannot hold a request. */
export const installAgent = (agentId: string) =>
  post<JobRef>(`/api/agents/${seg(agentId)}/install`, {})

/** Where an `agent_install` job's result says the agent went, or "". */
export function installedAt(result: unknown): string {
  const row = (result ?? {}) as { path?: unknown; model?: unknown }
  if (typeof row.path === 'string' && row.path) return row.path
  return typeof row.model === 'string' ? row.model : ''
}

/** The protocol status for one target, replaced with the engine's newest answer. */
export function withSkill(doc: TargetsDoc, targetId: string, status: SkillStatus): TargetsDoc {
  return {
    ...doc,
    targets: doc.targets.map((row) => (row.id === targetId ? { ...row, skill: status } : row)),
  }
}

/** What the reader sees for one wiring state. The words are this screen's; the
 *  state and the reason beside it are the engine's. */
export function wiringWords(state: TargetStanding): string {
  if (state === 'connected') return 'Connected to this store'
  if (state === 'stale') return 'Wired to a different store'
  if (state === 'unreadable') return 'Its config could not be read'
  if (state === 'absent') return 'Not connected yet'
  return 'The engine reported no state'
}

/** What the reader sees for the protocol on disk, from `SkillStatus` alone. */
export function skillWords(status: SkillStatus): string {
  if (!status.supported) return 'This harness has nowhere to keep the protocol'
  if (!status.present) return 'No protocol written yet'
  if (status.stale) return 'The protocol on disk is not the one this build would write'
  return 'The protocol on disk is current'
}

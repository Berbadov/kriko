import type { Agent } from '../engine/Engine'
import type { ApiJob } from '../engine/api'

export interface CompareDraft {
  draft_id: string
  name: string
  lookup_ids: string[]
}

export interface ResearchJob {
  job_id: string
  state: string
  done?: boolean
  message?: string
}

export interface ResearchResult extends CompareDraft {
  research_job_id: string
}

export function selectCompareAgent(agents: Agent[], preferred: string, available: boolean): Agent | undefined {
  if (!available) return undefined
  return preferred ? agents.find((agent) => agent.id === preferred) : agents[0]
}

/** The engine's own "no pick named" shape: an empty id, the harness plane.
 *  Sent when a column has no agent it can name, so the engine resolves one
 *  itself and answers with what it did — or with the key, trial or install it
 *  is missing. This is a request the engine already understands (`ask` sends
 *  the same empty id when the reader has picked nothing), not a fifth agent. */
export const ENGINE_CHOOSES: Agent = { id: '', label: 'Default agent', backend: 'harness' }

/** The agent a press that names a product uses.
 *
 *  An empty roster is not a crash: it is the engine's own "no pick named"
 *  shape, which the engine resolves or refuses with the key, trial or install
 *  it is missing. Never `undefined`, so a caller cannot read `agent.id`. */
export function pressAgent(agents: Agent[], preferred: string): Agent {
  return agents.find((agent) => agent.id === preferred) ?? agents[0] ?? ENGINE_CHOOSES
}

export interface Recovery {
  /** What the reader may press. Never invented here: it is the engine's own
   *  availability list, and empty when the engine listed no agent at all. */
  choices: Agent[]
  /** What the column says, using only what the engine reported. */
  note: string
  /** Nothing was listed, so the only press left asks the engine to resolve an
   *  agent and say what is missing. */
  engineChooses: boolean
}

/** The way out of a column whose stored agent this engine does not offer.
 *
 *  The reader is standing on Compare, so the choice belongs there. Which
 *  agents may be offered is the engine's to say (`/api/agent-availability`);
 *  this decides only what to show and what to say about it. The stored pick is
 *  named back in the engine's own terms — an id it reported and then did not
 *  list — rather than paraphrased, because Compare knows no reason the engine
 *  has not given it. */
export function compareRecovery(agents: Agent[], preferred: string, available: boolean): Recovery {
  const choices = available ? agents : []
  if (choices.length) {
    return {
      choices,
      note: preferred && !choices.some((agent) => agent.id === preferred)
        ? `The engine does not list “${preferred}” on this machine.`
        : 'The engine lists no research agent on this machine.',
      engineChooses: false,
    }
  }
  return {
    choices: [],
    note: 'The engine lists no research agent on this machine.',
    engineChooses: true,
  }
}

/** The new-product quick looks this comparison should pick back up.
 *
 *  A product researched in Compare is a `quick_look` job with `compare_add`;
 *  it joins the draft only when it succeeds. Before then it is not a column, so
 *  a reload would hide the work without this list. Finished jobs are excluded:
 *  their column is already in the draft, or they failed. */
export function resumableNewProducts(jobs: ApiJob[], draftId: string, lookupIds: string[]): { jobId: string; name: string }[] {
  const found: { jobId: string; name: string }[] = []
  for (const job of jobs) {
    const params = job.params ?? {}
    if (job.kind !== 'quick_look' || job.done || params.compare_add !== true) continue
    if (params.compare_draft_id !== draftId || lookupIds.includes(job.job_id)) continue
    found.push({ jobId: job.job_id, name: String(params.product || 'Product') })
  }
  return found
}

export interface CompareResearchIO {
  start: (path: string, body: Record<string, string>) => Promise<{ job_id: string }>
  follow: (jobId: string, stillWanted: () => boolean) => Promise<ResearchJob | null>
  drafts: () => Promise<{ items: CompareDraft[] }>
  waitForSaves: () => Promise<void>
  pause: () => Promise<void>
}

/** Start and follow one compare quick look, then reconcile with the durable
 *  draft. The injected IO keeps the request contract and concurrent edits
 *  testable without a browser or live engine. */
export async function researchCompareSlot(
  draftId: string,
  lookupId: string,
  agent: Agent,
  io: CompareResearchIO,
  stillWanted: () => boolean,
  onJob: (jobId: string) => void,
): Promise<ResearchResult | null> {
  const path = `/api/compare-drafts/${encodeURIComponent(draftId)}/research`
  const sent = await io.start(path, { lookup_id: lookupId, harness: agent.id, backend: agent.backend })
  onJob(sent.job_id)
  const ended = await io.follow(sent.job_id, stillWanted)
  if (!stillWanted()) return null
  if (!ended || ended.state !== 'succeeded') {
    const note = !ended || !['failed', 'interrupted', 'cancelled'].includes(ended.state)
      ? 'This research is still running. Reopen Compare later to see its result.'
      : ended.message || (ended.state === 'cancelled' ? 'Research was cancelled.' : 'The quick look did not finish.')
    throw new Error(note)
  }

  for (let attempt = 0; attempt < 4; attempt += 1) {
    await io.waitForSaves()
    if (!stillWanted()) return null
    const reply = await io.drafts()
    if (!stillWanted()) return null
    const current = reply.items.find((item) => item.draft_id === draftId)
    if (!current) throw new Error('The quick look finished, but the comparison could not refresh. Reopen Compare and try again.')
    if (current.lookup_ids.includes(sent.job_id) || !current.lookup_ids.includes(lookupId)) {
      return { ...current, research_job_id: sent.job_id }
    }
    if (attempt < 3) await io.pause()
  }
  throw new Error('The quick look finished, but its result has not appeared in this comparison yet. Reopen Compare shortly to check it.')
}

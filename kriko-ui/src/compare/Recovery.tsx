import { compareRecovery, ENGINE_CHOOSES } from './research'
import type { Agent } from '../engine/Engine'

/** The choice a column offers when the agent its comparison was saved on is
 *  not on this machine.
 *
 *  Presentational on purpose. The rows arrive as a prop — the engine's own
 *  availability list — so nothing here can invent an agent, and every press is
 *  reported upward, to where the research and the stored pick live. The reader
 *  is standing on Compare; being sent to Settings was the dead end. */
export function AgentRecovery({ agents, preferred, available, busy, onResearch }: {
  agents: Agent[]
  preferred: string
  available: boolean
  busy: boolean
  onResearch: (agent: Agent) => void
}) {
  const { choices, note, engineChooses } = compareRecovery(agents, preferred, available)
  return (
    <div className="mx-recover" role="group" aria-label="Research this product">
      <p className="muted">{note}</p>
      <div className="mx-research-actions">
        {choices.map((agent) => (
          <button
            key={agent.id}
            className="btn ghost mx-research"
            disabled={busy}
            title={`Research with ${agent.label}`}
            onClick={() => onResearch(agent)}
          >
            {busy ? 'Researching…' : `Research with ${agent.label}`}
          </button>
        ))}
        {engineChooses && (
          <button
            className="btn ghost mx-research"
            disabled={busy}
            title="Ask the engine to resolve an agent and report what it found"
            onClick={() => onResearch(ENGINE_CHOOSES)}
          >
            {busy ? 'Researching…' : 'Let the engine pick'}
          </button>
        )}
      </div>
    </div>
  )
}

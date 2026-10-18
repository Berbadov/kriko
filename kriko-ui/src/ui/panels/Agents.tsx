import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { effortKey, modelKey, usePrefsDoc, type AgentRow } from '../../engine/settings'
import { usePrefs } from '../../prefs'
import { Icon } from '../Icon'
import { Select } from '../controls'

/** Who answers. One agent is the default, and each agent keeps its own model and effort. */
export function AgentsPanel(_: { onOpen?: (lookupId: string) => void }) {
  const { motion: m } = usePrefs()
  const { doc, problem, busy, save, reload } = usePrefsDoc()
  const [open, setOpen] = useState<string | null>(null)

  if (!doc) return <p className="panel-note">{problem || 'Reading the agents…'}</p>
  const chosen = doc.chosen.preferred_harness || doc.effective.harness

  return (
    <div className="panel-body">
      <p className="panel-note" data-ok={doc.effective.harness_ready}>
        {doc.effective.harness_ready ? 'The default agent is ready.' : doc.effective.harness_note || 'The default agent is not ready.'}
      </p>
      {problem && <p className="error-note">{problem}</p>}

      <ul className="agent-list" role="radiogroup" aria-label="Default agent">
        {doc.harnesses.map((agent) => (
          <AgentItem
            key={agent.id}
            agent={agent}
            isDefault={agent.id === chosen}
            open={open === agent.id}
            onToggle={() => setOpen(open === agent.id ? null : agent.id)}
            onDefault={() => void save({ preferred_harness: agent.id })}
            onChange={(patch) => void save(patch)}
            enter={m.tx.soft}
          />
        ))}
      </ul>

      {doc.unusable.length > 0 && (
        <section className="panel-group">
          <h3>Found, but not usable</h3>
          <ul className="plain-list">
            {doc.unusable.map((row) => (
              <li key={row.id}>
                <strong>{row.label}</strong>
                <small>{row.why}</small>
              </li>
            ))}
          </ul>
        </section>
      )}

      {doc.missing.length > 0 && (
        <section className="panel-group">
          <h3>Not installed</h3>
          <ul className="plain-list">
            {doc.missing.map((row) => (
              <li key={row.id}>
                <strong>{row.label}</strong>
                {row.install_hint && <small>{row.install_hint}</small>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <button className="btn ghost" onClick={() => void reload(true)} disabled={busy}>
        {busy ? 'Looking…' : 'Look for models again'}
      </button>
    </div>
  )
}

function AgentItem({
  agent,
  isDefault,
  open,
  onToggle,
  onDefault,
  onChange,
  enter,
}: {
  agent: AgentRow
  isDefault: boolean
  open: boolean
  onToggle: () => void
  onDefault: () => void
  onChange: (patch: Record<string, string>) => void
  enter: object
}) {
  const withCurrent = (list: string[], current: string) => (current && !list.includes(current) ? [current, ...list] : list)
  const models = withCurrent(agent.llms, agent.llm)
  const efforts = withCurrent(agent.efforts, agent.effort)
  const summary = [agent.llm || 'Own default', agent.effort].filter(Boolean).join(' · ')

  return (
    <li className="agent" data-open={open} data-default={isDefault}>
      <div className="agent-head">
        <button className="radio" role="radio" aria-checked={isDefault} aria-label={`Use ${agent.label} by default`} onClick={onDefault}>
          <i />
        </button>
        <button className="agent-main" onClick={onToggle} aria-expanded={open}>
          <span>
            <strong>{agent.label}</strong>
            <small>{summary}</small>
          </span>
          {isDefault && <span className="tag">Default</span>}
          <Icon name="chevron" size={15} />
        </button>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            className="agent-set"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={enter}
          >
            <div className="setting">
              <span>Model</span>
              <Select
                label={`${agent.label} model`}
                value={agent.llm}
                options={[{ value: '', label: 'Own default' }, ...models.map((id) => ({ value: id, label: id }))]}
                onChange={(value) => onChange({ [modelKey(agent)]: value })}
              />
            </div>
            {efforts.length > 0 && (
              <div className="setting">
                <span>Effort</span>
                <Select
                  label={`${agent.label} effort`}
                  value={agent.effort}
                  options={[{ value: '', label: 'Own default' }, ...efforts.map((id) => ({ value: id, label: id }))]}
                  onChange={(value) => onChange({ [effortKey(agent)]: value })}
                />
              </div>
            )}
            {agent.path && <small className="panel-path">{agent.path}</small>}
            {agent.llms_note && <small className="panel-path">{agent.llms_note}</small>}
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

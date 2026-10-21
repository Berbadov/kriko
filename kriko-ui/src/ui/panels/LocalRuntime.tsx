import { useState } from 'react'
import { useLocalRuntimes } from '../../engine/runtimes'
import { Select } from '../controls'
import '../../styles/providers.css'

const SHOWN_MODELS = 12

/** Which program serves the local model, where it listens, and whether it answers. Installs nothing. */
export function LocalRuntimeGroup({ stepsBelow = false }: { stepsBelow?: boolean }) {
  const { doc, problem, checked, save, check } = useLocalRuntimes()
  // What is typed in the field, for the Check beside it. The field itself owns the typing.
  const [typed, setTyped] = useState<string | null>(null)
  if (!doc) return null
  const picked = doc.runtimes.find((row) => row.id === doc.chosen)
  const address = (typed ?? doc.url).trim() || picked?.url || ''

  return (
    <section className="panel-group">
      <h3>Server software</h3>
      <p className="panel-note">The program the local agent talks to. Kriko does not install it or start it for you.</p>
      {problem && <p className="error-note">{problem}</p>}
      <div className="setting">
        <span>
          Program
          <small>{picked ? (picked.url ? `Usually at ${picked.url}.` : 'Any server that speaks the OpenAI protocol.') : 'Automatic looks for each of these on this computer.'}</small>
        </span>
        <Select
          label="Local server program"
          value={doc.chosen}
          options={[{ value: '', label: 'Automatic' }, ...doc.runtimes.map((row) => ({ value: row.id, label: row.name }))]}
          onChange={(value) => void save(value, doc.runtimes.find((row) => row.id === value)?.url ?? '')}
        />
      </div>
      <div className="setting stack">
        <span>
          Address
          <small>{doc.chosen ? 'Where the server listens.' : 'Leave blank to look in the usual places.'}</small>
        </span>
        <AddressField
          key={`${doc.chosen}|${doc.url}`}
          saved={doc.url}
          placeholder={picked?.url || 'http://127.0.0.1:1234'}
          disabled={!doc.chosen}
          onTyped={setTyped}
          onSave={(next) => void save(doc.chosen, next)}
        />
      </div>
      <div className="setting">
        <span>
          Check
          <small>Asks the address which models it lists.</small>
        </span>
        <button className="btn" onClick={() => void check(doc.chosen, address)} disabled={checked === 'checking' || (!doc.chosen && !address)}>
          {checked === 'checking' ? 'Checking…' : 'Check it answers'}
        </button>
      </div>
      {checked && checked !== 'checking' && (
        <div className="test-result" data-ok={checked.up && checked.models.length > 0} role="status">
          <small>{checked.message}</small>
          {checked.models.length > 0 && (
            <ul>
              {checked.models.slice(0, SHOWN_MODELS).map((name) => (
                <li key={name}>
                  <span>{name}</span>
                </li>
              ))}
              {checked.models.length > SHOWN_MODELS && (
                <li>
                  <small>and {checked.models.length - SHOWN_MODELS} more</small>
                </li>
              )}
            </ul>
          )}
          {checked.loader && <small>{checked.loader.help}</small>}
          {!checked.up && doc.chosen === 'vllm' && stepsBelow && <small>The steps for this computer are below.</small>}
        </div>
      )}
    </section>
  )
}

function AddressField({ saved, placeholder, disabled, onTyped, onSave }: { saved: string; placeholder: string; disabled: boolean; onTyped: (value: string) => void; onSave: (value: string) => void }) {
  const [draft, setDraft] = useState(saved)
  return (
    <input
      className="field"
      type="url"
      autoComplete="off"
      spellCheck={false}
      aria-label="Local server address"
      placeholder={placeholder}
      value={draft}
      disabled={disabled}
      onChange={(event) => {
        setDraft(event.target.value)
        onTyped(event.target.value)
      }}
      onBlur={() => {
        const next = draft.trim()
        if (next !== saved) onSave(next)
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') event.currentTarget.blur()
      }}
    />
  )
}

import { useState } from 'react'
import { useLocalRuntimes } from '../../engine/runtimes'
import { Setting, SelectField } from './settingsParts'

const SHOWN_MODELS = 12

/** Which program serves the local model, where it listens, and whether it answers.
 *  Drawn as rows inside the On this computer section. Installs nothing. */
export function LocalRuntimeRows({ stepsBelow = false }: { stepsBelow?: boolean }) {
  const { doc, problem, checked, save, check, reload } = useLocalRuntimes()
  // What is typed in the address field, for the check beside it. The field owns the typing.
  const [typed, setTyped] = useState<string | null>(null)
  if (!doc)
    return problem ? (
      <Setting
        icon="alert"
        label="Server"
        note={`Could not read local server settings. ${problem}`}
        control={
          <button type="button" className="k-btn" onClick={() => void reload()}>
            Try again
          </button>
        }
      />
    ) : null
  const picked = doc.runtimes.find((row) => row.id === doc.chosen)
  const address = (typed ?? doc.url).trim() || picked?.url || ''

  return (
    <>
      {problem && <p className="error-note" role="alert">{problem}</p>}
      <Setting
        icon="server"
        label="Server program"
        note={picked ? (picked.url ? `Usually at ${picked.url}.` : 'Any server that speaks the OpenAI protocol.') : 'Automatic looks for each of these on this computer.'}
        control={
          <SelectField
            label="Local server program"
            value={doc.chosen}
            options={[{ value: '', label: 'Automatic' }, ...doc.runtimes.map((row) => ({ value: row.id, label: row.name }))]}
            onChange={(value) => void save(value, doc.runtimes.find((row) => row.id === value)?.url ?? '')}
          />
        }
      />
      <Setting
        icon="link"
        label="Address"
        stack
        note={doc.chosen ? 'Where the server listens.' : 'Leave blank to look in the usual places.'}
        control={
          <AddressField
            key={`${doc.chosen}|${doc.url}`}
            saved={doc.url}
            placeholder={picked?.url || 'http://127.0.0.1:1234'}
            disabled={!doc.chosen}
            onTyped={setTyped}
            onSave={(next) => void save(doc.chosen, next)}
          />
        }
      />
      <Setting
        icon="check"
        label="Answering"
        stack
        note="Asks the address which models it lists."
        control={
          <div className="keys-stack">
            <span className="keys-actions">
              <button type="button" className="k-btn" onClick={() => void check(doc.chosen, address)} disabled={checked === 'checking' || (!doc.chosen && !address)}>
                {checked === 'checking' ? 'Checking…' : 'Check it answers'}
              </button>
            </span>
            {checked && checked !== 'checking' && (
              <div className="keys-check" data-ok={checked.up && checked.models.length > 0} role="status">
                <span>{checked.message}</span>
                {checked.models.length > 0 && (
                  <ul className="keys-names">
                    {checked.models.slice(0, SHOWN_MODELS).map((name) => (
                      <li key={name}>{name}</li>
                    ))}
                    {checked.models.length > SHOWN_MODELS && <li>and {checked.models.length - SHOWN_MODELS} more</li>}
                  </ul>
                )}
                {checked.loader && <small>{checked.loader.help}</small>}
                {!checked.up && doc.chosen === 'vllm' && stepsBelow && <small>The steps for this computer are below.</small>}
              </div>
            )}
          </div>
        }
      />
    </>
  )
}

function AddressField({ saved, placeholder, disabled, onTyped, onSave }: { saved: string; placeholder: string; disabled: boolean; onTyped: (value: string) => void; onSave: (value: string) => void }) {
  const [draft, setDraft] = useState(saved)
  return (
    <input
      className="k-input"
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

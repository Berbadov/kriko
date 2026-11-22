import { useState } from 'react'
import type { useLocalRuntimes } from '../../engine/runtimes'
import { Setting, SelectField } from './settingsParts'

const SHOWN_MODELS = 12

type Runtimes = ReturnType<typeof useLocalRuntimes>

/** Which program serves the local model and where it listens, as two rows. The
 *  state is owned by the caller, so the check that asks the address (a press in
 *  Quick actions) and these fields share one answer. Installs nothing. */
export function LocalRuntimeRows({ rt }: { rt: Runtimes }) {
  const { doc, problem, save, reload } = rt
  if (!doc)
    return problem ? (
      <Setting
        icon="alert"
        label="Server"
        note={`Could not read the local server settings. ${problem}`}
        control={
          <button type="button" className="k-btn" onClick={() => void reload()}>
            Try again
          </button>
        }
      />
    ) : (
      <div className="localai-skeleton-row" aria-hidden="true">
        <span className="localai-skeleton" />
        <span className="localai-skeleton" data-short="" />
      </div>
    )
  const picked = doc.runtimes.find((row) => row.id === doc.chosen)

  return (
    <>
      {problem && (
        <p className="error-note" role="alert">
          {problem}
        </p>
      )}
      <Setting
        icon="server"
        label="Server program"
        note={picked ? (picked.url ? `Usually at ${picked.url}.` : 'Any server that speaks the OpenAI protocol.') : 'Automatic looks for each of these programs on this computer.'}
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
        note={doc.chosen ? 'Where the server listens. Saved when you leave the field.' : 'Choose a program above to set its address. Automatic looks in the usual places.'}
        control={<AddressField key={`${doc.chosen}|${doc.url}`} saved={doc.url} placeholder={picked?.url || 'http://127.0.0.1:1234'} disabled={!doc.chosen} onSave={(next) => void save(doc.chosen, next)} />}
      />
    </>
  )
}

/** What the check found: whether the address answers, which models it lists, and what Kriko can set on it. */
export function CheckResult({ checked, vllmStepsBelow }: { checked: Runtimes['checked']; vllmStepsBelow?: boolean }) {
  if (!checked || checked === 'checking') return null
  return (
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
      {!checked.up && vllmStepsBelow && <small>The steps for this computer are below.</small>}
    </div>
  )
}

function AddressField({ saved, placeholder, disabled, onSave }: { saved: string; placeholder: string; disabled: boolean; onSave: (value: string) => void }) {
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
      onChange={(event) => setDraft(event.target.value)}
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

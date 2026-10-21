import { useMemo, useState } from 'react'
import { usePrefsDoc } from '../../engine/settings'
import { useLocal, type Library, type Model, type VllmPlan, type VllmServer } from '../../engine/local'
import { Icon } from '../Icon'
import { PixelBar, Select } from '../controls'
import { HfStore } from './HfStore'
import { LocalRuntimeGroup } from './LocalRuntime'

const gb = (bytes: number) => `${(bytes / 1e9).toFixed(1)} GB`
const mb = (value: number) => `${(value / 1024).toFixed(value >= 10240 ? 0 : 1)} GB`
const CONTEXTS = ['', '2048', '4096', '8192', '16384', '32768']

/** The computer, the models on it, and getting more. */
export function LocalPanel(_: { onOpen?: (lookupId: string) => void }) {
  const local = useLocal()
  const { doc, save } = usePrefsDoc()
  const { machine, runtime, models, pull } = local
  const chosen = doc?.chosen.local_model ?? ''
  const running = Boolean(runtime?.runtime)
  const ollama = machine?.runtimes.find((r) => r.id === 'ollama')

  return (
    <div className="panel-body">
      {machine && (
        <section className="panel-group">
          <h3>This computer</h3>
          <div className="tiles">
            <div>
              <strong>{machine.gpu ? mb(machine.gpu.vram_total_mb) : 'None'}</strong>
              <small>{machine.gpu ? 'graphics memory' : 'no graphics card'}</small>
            </div>
            <div>
              <strong>{machine.ram_total_mb ? mb(machine.ram_total_mb) : '—'}</strong>
              <small>memory</small>
            </div>
            <div>
              <strong>{machine.cpu?.cores ?? '—'}</strong>
              <small>processor cores</small>
            </div>
          </div>
          {machine.gpu && <small className="panel-path">{machine.gpu.name}</small>}
        </section>
      )}

      {local.problem && <p className="error-note">{local.problem}</p>}

      <section className="panel-group">
        <h3>Runtime</h3>
        <ul className="plain-list">
          {(machine?.runtimes ?? []).map((one) => (
            <li key={one.id}>
              <strong>{one.name}</strong>
              <small>
                {one.id === 'ollama' && one.installed ? (running ? `Running at ${runtime?.url}` : 'Installed, not running') : one.installed ? 'Installed. Get models in its own app.' : 'Not installed'}
              </small>
            </li>
          ))}
        </ul>
        {ollama?.installed && !running && (
          <button className="btn" onClick={() => void local.startRuntime()} disabled={local.starting}>
            {local.starting ? 'Starting…' : 'Start Ollama'}
          </button>
        )}
      </section>

      <LocalRuntimeGroup stepsBelow={Boolean(machine?.vllm)} />

      {machine?.vllm && <VllmCard plan={machine.vllm} server={local.vllm} checking={local.checking} onCheck={() => void local.recheck()} />}

      {running && (
        <section className="panel-group">
          <h3>Models on this computer</h3>
          {models.length === 0 && <p className="panel-note">No models yet. Get one below.</p>}
          <ul className="past-list" role="radiogroup" aria-label="Local model">
            {models.map((model) => (
              <ModelRow key={model.name} model={model} active={model.name === chosen} onUse={() => void save({ local_model: model.name })} onRemove={() => local.remove(model.name)} />
            ))}
          </ul>
        </section>
      )}

      {running && (
        <section className="panel-group">
          <h3>Get a model</h3>
          {pull && (
            <div className="pull" data-failed={Boolean(pull.error)}>
              <span>
                <strong>{pull.model}</strong>
                <small>{pull.error || pull.message || 'Downloading'}</small>
              </span>
              {pull.error ? (
                <span className="pull-actions">
                  <button onClick={() => void local.startPull(pull.model)}>Try again</button>
                  <button onClick={local.dismissPull}>Close</button>
                </span>
              ) : (
                <>
                  <PixelBar value={pull.progress} active cells={26} />
                  <button onClick={() => void local.stopPull()}>Stop</button>
                </>
              )}
            </div>
          )}
          <Browse local={local} pulling={Boolean(pull) && !pull?.error} installed={models.map((m) => m.name)} />
          <h4 className="hf-title">Hugging Face</h4>
          <HfStore vramMb={machine?.gpu?.vram_total_mb ?? null} installed={models.map((m) => m.name)} pulling={Boolean(pull) && !pull?.error} onGet={(name) => void local.startPull(name)} />
        </section>
      )}

      {doc && (
        <section className="panel-group">
          <h3>How it runs</h3>
          <div className="setting">
            <span>
              Device
              <small>Automatic uses the graphics card when it fits.</small>
            </span>
            <Select
              label="Device"
              value={doc.chosen.local_device ?? ''}
              options={[
                { value: '', label: 'Automatic' },
                { value: 'gpu', label: 'Graphics card' },
                { value: 'cpu', label: 'Processor' },
              ]}
              onChange={(value) => void save({ local_device: value })}
            />
          </div>
          <div className="setting">
            <span>
              Context size
              <small>Tokens the model reads at once. More needs more memory.</small>
            </span>
            <Select
              label="Context size"
              value={CONTEXTS.includes(doc.chosen.local_context_tokens ?? '') ? (doc.chosen.local_context_tokens ?? '') : ''}
              options={CONTEXTS.map((value) => ({ value, label: value || 'Default' }))}
              onChange={(value) => void save({ local_context_tokens: value })}
            />
          </div>
        </section>
      )}
    </div>
  )
}

/** vLLM. Kriko does not install it. It shows the steps for this driver, and finds the server when it runs. */
function VllmCard({ plan, server, checking, onCheck }: { plan: VllmPlan; server: VllmServer | null; checking: boolean; onCheck: () => void }) {
  const [copied, setCopied] = useState('')
  const copy = (command: string) => {
    void navigator.clipboard?.writeText(command).then(
      () => {
        setCopied(command)
        window.setTimeout(() => setCopied((now) => (now === command ? '' : now)), 1600)
      },
      () => undefined,
    )
  }
  return (
    <section className="panel-group vllm">
      <h3>vLLM</h3>
      {server ? (
        <>
          <p className="panel-note" data-ok="true">
            Running at {server.url}
          </p>
          {server.models.length > 0 && <small className="panel-path">{server.models.join(', ')}</small>}
        </>
      ) : (
        <>
          <p className="panel-note" data-ok={plan.ready}>
            {plan.summary}
          </p>
          {plan.ready && (
            <details className="steps">
              <summary>Show the steps</summary>
              <ol>
                {plan.steps.map((step) => (
                  <li key={step.command}>
                    <span>
                      <strong>{step.title}</strong>
                      <small className="tag">{step.where}</small>
                    </span>
                    <div className="command">
                      <code>{step.command}</code>
                      <button onClick={() => copy(step.command)} aria-label={`Copy: ${step.title}`}>
                        {copied === step.command ? 'Copied' : 'Copy'}
                      </button>
                    </div>
                  </li>
                ))}
              </ol>
              {plan.notes.map((note) => (
                <small key={note} className="panel-path">
                  {note}
                </small>
              ))}
            </details>
          )}
          <button className="btn ghost" onClick={onCheck} disabled={checking}>
            {checking ? 'Checking…' : 'Check again'}
          </button>
        </>
      )}
    </section>
  )
}

/** The public list. It is read from the web, so it opens when the reader asks. */
function Browse({ local, pulling, installed }: { local: ReturnType<typeof useLocal>; pulling: boolean; installed: string[] }) {
  const { library } = local
  const [query, setQuery] = useState('')
  const [typed, setTyped] = useState('')
  const rows = useMemo(() => (library ?? []).filter((row) => !query.trim() || `${row.name} ${row.about}`.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 40), [library, query])

  return (
    <>
      <form
        className="key-form"
        onSubmit={(event) => {
          event.preventDefault()
          if (typed.trim() && !pulling) {
            void local.startPull(typed.trim())
            setTyped('')
          }
        }}
      >
        <input placeholder="Model name, for example qwen2.5:7b" aria-label="Model name" value={typed} onChange={(event) => setTyped(event.target.value)} spellCheck={false} />
        <button type="submit" className="btn" disabled={!typed.trim() || pulling}>
          Get
        </button>
      </form>

      {!library ? (
        <button className="btn ghost" onClick={() => void local.openLibrary()}>
          Browse the Ollama library
        </button>
      ) : (
        <>
          <label className="search-field">
            <Icon name="search" size={15} />
            <input type="search" placeholder="Search the library" aria-label="Search the library" value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          {local.libraryProblem && <p className="error-note">{local.libraryProblem}</p>}
          <ul className="library">
            {rows.map((row) => (
              <LibraryRow key={row.name} row={row} installed={installed} disabled={pulling} onGet={(name) => void local.startPull(name)} />
            ))}
          </ul>
        </>
      )}
    </>
  )
}

function LibraryRow({ row, installed, disabled, onGet }: { row: Library; installed: string[]; disabled: boolean; onGet: (name: string) => void }) {
  return (
    <li>
      <strong>{row.name}</strong>
      <small>{row.about}</small>
      <span className="choices">
        {(row.sizes.length ? row.sizes : ['']).map((size) => {
          const name = size ? `${row.name}:${size}` : row.name
          const has = installed.includes(name)
          return (
            <button key={name} className="choice" data-on={has} disabled={disabled || has} onClick={() => onGet(name)} title={has ? 'Installed' : `Get ${name}`}>
              {size || 'latest'}
            </button>
          )
        })}
      </span>
    </li>
  )
}

function ModelRow({ model, active, onUse, onRemove }: { model: Model; active: boolean; onUse: () => void; onRemove: () => Promise<void> }) {
  const [asking, setAsking] = useState(false)
  const meta = [gb(model.size_bytes), model.params !== '—' && model.params, model.quant].filter(Boolean).join(' · ')
  return (
    <li className="past" data-asking={asking}>
      <button className="radio" role="radio" aria-checked={active} aria-label={`Use ${model.name}`} onClick={onUse}>
        <i />
      </button>
      <button className="past-main" onClick={onUse}>
        <strong>{model.name}</strong>
        <small>{meta}</small>
      </button>
      {asking ? (
        <span className="past-ask">
          <span>Remove?</span>
          <button
            onClick={() => {
              setAsking(false)
              void onRemove()
            }}
          >
            Remove
          </button>
          <button onClick={() => setAsking(false)}>Keep</button>
        </span>
      ) : (
        <span className="past-actions">
          <button className="icon-btn sm" onClick={() => setAsking(true)} aria-label={`Remove ${model.name}`} title="Remove from this computer">
            <Icon name="x" size={15} />
          </button>
        </span>
      )}
    </li>
  )
}

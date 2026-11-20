import { useMemo, useState } from 'react'
import { usePrefsDoc } from '../../engine/settings'
import { useLocal, type Library, type Model, type VllmPlan, type VllmServer } from '../../engine/local'
import { Disclosure } from '../Disclosure'
import { Icon } from '../Icon'
import { ProgressBar } from '../controls'
import { HfStore } from './HfStore'
import { LocalRuntimeRows } from './LocalRuntime'
import { Section, Setting, SelectField, State } from './settingsParts'

const gb = (bytes: number) => `${(bytes / 1e9).toFixed(1)} GB`
const mb = (value: number) => `${(value / 1024).toFixed(value >= 10240 ? 0 : 1)} GB`
const CONTEXTS = ['', '2048', '4096', '8192', '16384', '32768']

/** The model on this computer, as rows of one section: the computer, the runtime
 *  and its state, the server, the model in use, getting a model, and how it runs. */
export function LocalGroup() {
  const local = useLocal()
  const { doc, save } = usePrefsDoc()
  const { machine, runtime, models, pull } = local
  const [installOpen, setInstallOpen] = useState(false)
  const chosen = doc?.chosen.local_model ?? ''
  const running = Boolean(runtime?.runtime)
  const installed = machine?.runtimes.filter((one) => one.installed) ?? []
  const inUse = models.some((model) => model.name === chosen)

  return (
    <Section title="On this computer" aside={<State tone={running ? 'ok' : 'none'}>{running ? 'Runtime running' : 'Runtime not running'}</State>}>
      {local.problem && <p className="error-note">{local.problem}</p>}

      {machine && (
        <Setting
          icon="cpu"
          label="This computer"
          value={`${machine.gpu ? mb(machine.gpu.vram_total_mb) : 'No graphics card'} · ${machine.ram_total_mb ? mb(machine.ram_total_mb) : 'memory not known'} · ${machine.cpu?.cores ?? 'n/a'} cores`}
          note={machine.gpu ? `${machine.gpu.name}. A model has to fit in this memory to run well.` : 'A model has to fit in this memory to run well.'}
        />
      )}

      {(machine?.runtimes ?? []).map((one) => {
        const state =
          one.id === 'ollama' && one.installed ? (running ? `Running at ${runtime?.url}` : 'Installed, not running') : one.installed ? 'Installed' : 'Not installed'
        return (
          <Setting
            key={one.id}
            icon="server"
            label={one.name}
            value={<State tone={one.installed && (one.id !== 'ollama' || running) ? 'ok' : 'none'}>{state}</State>}
            note={one.installed && one.id !== 'ollama' ? 'Get models in its own app.' : one.installed ? 'Kriko can start it and download models into it.' : 'Install it from its own website, then press Check again.'}
            control={
              one.id === 'ollama' && one.installed && !running ? (
                <button type="button" className="k-btn" onClick={() => void local.startRuntime()} disabled={local.starting}>
                  {local.starting ? 'Starting…' : 'Start Ollama'}
                </button>
              ) : undefined
            }
          />
        )
      })}
      {machine && installed.length === 0 && (
        <Setting
          icon="download"
          label="Install runtime"
          note="Kriko does not install a runtime for you. Install one from its own website, then press Check again."
          stack
          control={
            <div className="keys-stack">
              <span className="keys-actions">
                <button type="button" className="k-btn" aria-expanded={installOpen} onClick={() => setInstallOpen((now) => !now)}>
                  {installOpen ? 'Hide the steps' : 'Install runtime'}
                </button>
                <button type="button" className="k-btn" onClick={() => void local.recheck()} disabled={local.checking}>
                  {local.checking ? 'Checking…' : 'Check again'}
                </button>
              </span>
              {installOpen && <small className="keys-result">Install one of the programs listed above, then press Check again. Kriko finds it on this computer.</small>}
            </div>
          }
        />
      )}

      <LocalRuntimeRows stepsBelow={Boolean(machine?.vllm)} />

      {machine?.vllm && <VllmRow plan={machine.vllm} server={local.vllm} checking={local.checking} onCheck={() => void local.recheck()} />}

      {running && (
        <Setting
          icon="cube"
          label="Model in use"
          value={<State tone={inUse ? 'ok' : 'none'}>{inUse ? chosen : 'None chosen'}</State>}
          note={models.length === 0 ? 'No models on this computer yet. Download one below.' : 'Press a model to use it. Remove takes it off this computer.'}
          stack
          control={
            <ul className="keys-models" role="radiogroup" aria-label="Local model">
              {models.map((model) => (
                <ModelRow key={model.name} model={model} active={model.name === chosen} onUse={() => void save({ local_model: model.name })} onRemove={() => local.remove(model.name)} />
              ))}
            </ul>
          }
        />
      )}

      {running ? (
        <Setting
          icon="download"
          label="Download a model"
          note="A download starts only when you press Get or a Get button, and Stop ends it."
          stack
          control={
            <div className="keys-stack">
              {pull && <PullStatus local={local} pull={pull} />}
              <GetModel local={local} pulling={Boolean(pull) && !pull?.error} installed={models.map((m) => m.name)} />
              <HuggingFace vramMb={machine?.gpu?.vram_total_mb ?? null} installed={models.map((m) => m.name)} pulling={Boolean(pull) && !pull?.error} onGet={(name) => void local.startPull(name)} />
            </div>
          }
        />
      ) : (
        <Setting icon="download" label="Download a model" note="Start the runtime to download a model into it." />
      )}

      {doc && (
        <>
          <Setting
            icon="gauge"
            label="Device"
            note="Automatic uses the graphics card when it fits."
            control={
              <SelectField
                label="Device"
                value={doc.chosen.local_device ?? ''}
                options={[
                  { value: '', label: 'Automatic' },
                  { value: 'gpu', label: 'Graphics card' },
                  { value: 'cpu', label: 'Processor' },
                ]}
                onChange={(value) => void save({ local_device: value })}
              />
            }
          />
          <Setting
            icon="layers"
            label="Context size"
            note="Tokens the model reads at once. More needs more memory."
            control={
              <SelectField
                label="Context size"
                value={CONTEXTS.includes(doc.chosen.local_context_tokens ?? '') ? (doc.chosen.local_context_tokens ?? '') : ''}
                options={CONTEXTS.map((value) => ({ value, label: value || 'Default' }))}
                onChange={(value) => void save({ local_context_tokens: value })}
              />
            }
          />
        </>
      )}
    </Section>
  )
}

/** A model download in progress, or the one that failed, with the words to act on it. */
function PullStatus({ local, pull }: { local: ReturnType<typeof useLocal>; pull: NonNullable<ReturnType<typeof useLocal>['pull']> }) {
  return (
    <div className="keys-pull" data-failed={Boolean(pull.error)} role="status">
      <strong>{pull.model}</strong>
      <small>{pull.error || pull.message || 'Downloading'}</small>
      {pull.error ? (
        <span className="keys-actions">
          <button type="button" className="k-btn" onClick={() => void local.startPull(pull.model)}>
            Try again
          </button>
          <button type="button" className="k-btn" onClick={local.dismissPull}>
            Close
          </button>
        </span>
      ) : (
        <>
          <ProgressBar value={pull.progress} active />
          <span className="keys-actions">
            <button type="button" className="k-btn" onClick={() => void local.stopPull()}>
              Stop
            </button>
          </span>
        </>
      )}
    </div>
  )
}

/** vLLM. Kriko does not install it. It shows the steps for this driver, and finds the server when it runs. */
function VllmRow({ plan, server, checking, onCheck }: { plan: VllmPlan; server: VllmServer | null; checking: boolean; onCheck: () => void }) {
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
  if (server) {
    return <Setting icon="server" label="vLLM" value={<State tone="ok">Running</State>} note={`Running at ${server.url}.${server.models.length ? ` Models: ${server.models.join(', ')}.` : ''}`} />
  }
  return (
    <Setting
      icon="server"
      label="vLLM"
      value={<State tone={plan.ready ? 'ok' : 'none'}>{plan.ready ? 'Steps ready' : 'Not ready'}</State>}
      note={plan.summary}
      stack
      control={
        <div className="keys-stack">
          {plan.ready && (
            <Disclosure title="Show the steps">
              <ol className="keys-steps">
                {plan.steps.map((step) => (
                  <li key={step.command}>
                    <span>
                      <strong>{step.title}</strong> <small>{step.where}</small>
                    </span>
                    <div className="keys-command">
                      <code>{step.command}</code>
                      <button type="button" className="k-btn" data-size="sm" onClick={() => copy(step.command)} aria-label={`Copy: ${step.title}`}>
                        {copied === step.command ? 'Copied' : 'Copy'}
                      </button>
                    </div>
                  </li>
                ))}
              </ol>
              {plan.notes.map((text) => (
                <small key={text} className="keys-result">
                  {text}
                </small>
              ))}
            </Disclosure>
          )}
          <span className="keys-actions">
            <button type="button" className="k-btn" onClick={onCheck} disabled={checking}>
              {checking ? 'Checking…' : 'Check again'}
            </button>
          </span>
        </div>
      }
    />
  )
}

/** Type a model name to get it, or browse the Ollama library. Both start a download only on a press. */
function GetModel({ local, pulling, installed }: { local: ReturnType<typeof useLocal>; pulling: boolean; installed: string[] }) {
  const [typed, setTyped] = useState('')
  return (
    <>
      <form
        className="keys-actions"
        onSubmit={(event) => {
          event.preventDefault()
          if (typed.trim() && !pulling) {
            void local.startPull(typed.trim())
            setTyped('')
          }
        }}
      >
        <input className="k-input" placeholder="Model name, for example qwen2.5:7b" aria-label="Model name" value={typed} onChange={(event) => setTyped(event.target.value)} spellCheck={false} />
        <button type="submit" className="k-btn" data-kind="primary" disabled={!typed.trim() || pulling}>
          Get
        </button>
      </form>
      {!local.library ? (
        <span className="keys-actions">
          <button type="button" className="k-btn" onClick={() => void local.openLibrary()}>
            Browse the Ollama library
          </button>
        </span>
      ) : (
        <Library local={local} pulling={pulling} installed={installed} />
      )}
    </>
  )
}

/** The public Ollama list. It is read from the web, so it opens when the reader asks. */
function Library({ local, pulling, installed }: { local: ReturnType<typeof useLocal>; pulling: boolean; installed: string[] }) {
  const { library } = local
  const [query, setQuery] = useState('')
  const rows = useMemo(() => (library ?? []).filter((row) => !query.trim() || `${row.name} ${row.about}`.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 40), [library, query])
  return (
    <>
      <label className="keys-search">
        <Icon name="search" size={15} />
        <input type="search" placeholder="Search the library" aria-label="Search the library" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      {local.libraryProblem && <p className="error-note">{local.libraryProblem}</p>}
      <ul className="keys-list">
        {rows.map((row) => (
          <LibraryRow key={row.name} row={row} installed={installed} disabled={pulling} onGet={(name) => void local.startPull(name)} />
        ))}
      </ul>
    </>
  )
}

function LibraryRow({ row, installed, disabled, onGet }: { row: Library; installed: string[]; disabled: boolean; onGet: (name: string) => void }) {
  return (
    <li className="keys-item">
      <span>
        <strong>{row.name}</strong> <small>{row.about}</small>
      </span>
      <span className="keys-actions">
        {(row.sizes.length ? row.sizes : ['']).map((size) => {
          const name = size ? `${row.name}:${size}` : row.name
          const has = installed.includes(name)
          return (
            <button key={name} type="button" className="k-btn" data-size="sm" disabled={disabled || has} onClick={() => onGet(name)} aria-label={has ? `${name} is installed` : `Get ${name}`}>
              {has ? `${size || 'latest'}, installed` : size || 'latest'}
            </button>
          )
        })}
      </span>
    </li>
  )
}

/** Hugging Face models Ollama can pull. An expandable block: the search runs when
 *  the reader opens it, and a download starts only from a Get button. */
function HuggingFace({ vramMb, installed, pulling, onGet }: { vramMb: number | null; installed: string[]; pulling: boolean; onGet: (name: string) => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="keys-hf-block">
      <span className="keys-actions">
        <button type="button" className="k-btn" aria-expanded={open} onClick={() => setOpen((now) => !now)}>
          {open ? 'Hide Hugging Face' : 'Browse Hugging Face'}
        </button>
      </span>
      {open && <HfStore vramMb={vramMb} installed={installed} pulling={pulling} onGet={onGet} />}
    </div>
  )
}

function ModelRow({ model, active, onUse, onRemove }: { model: Model; active: boolean; onUse: () => void; onRemove: () => Promise<void> }) {
  const [asking, setAsking] = useState(false)
  const meta = [gb(model.size_bytes), model.params !== 'n/a' && model.params, model.quant].filter(Boolean).join(' · ')
  return (
    <li className="keys-model" data-asking={asking}>
      <button type="button" className="keys-model-use" role="radio" aria-checked={active} aria-label={`Use ${model.name}`} onClick={onUse}>
        <strong>{model.name}</strong>
        <small>{meta}</small>
      </button>
      {asking ? (
        <span className="keys-actions">
          <span>Remove?</span>
          <button
            type="button"
            className="k-btn"
            data-kind="danger"
            onClick={() => {
              setAsking(false)
              void onRemove()
            }}
          >
            Remove
          </button>
          <button type="button" className="k-btn" onClick={() => setAsking(false)}>
            Keep
          </button>
        </span>
      ) : (
        <button type="button" className="k-btn" data-size="sm" onClick={() => setAsking(true)} aria-label={`Remove ${model.name}`}>
          Remove
        </button>
      )}
    </li>
  )
}

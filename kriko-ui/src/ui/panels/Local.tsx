import { useMemo, useState } from 'react'
import { FIT_WORDS, fitOf, fitRows, isRecommended, type Facts, type Fit } from '../../engine/fit'
import { useLocal, type Model, type VllmPlan, type VllmServer } from '../../engine/local'
import { Disclosure } from '../Disclosure'
import { Icon } from '../Icon'
import { ProgressBar } from '../controls'
import { HfStore } from './HfStore'
import { Section, Setting, State } from './settingsParts'

const gb = (bytes: number) => `${(bytes / 1e9).toFixed(1)} GB`
const FIT_TONE: Record<Fit, 'ok' | 'warn' | 'risk' | 'none'> = { well: 'ok', slow: 'warn', big: 'risk', unknown: 'none' }
/** Library rows drawn before "Show more". The list is long and a reader wants the top. */
const FIRST_ROWS = 12

type LocalState = ReturnType<typeof useLocal>

/** A line of loading rows, drawn instead of a blank card while something is read. */
export function Loading({ rows = 2 }: { rows?: number }) {
  return (
    <div className="localai-skeleton-row" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, at) => (
        <span key={at} className="localai-skeleton" data-short={at % 2 ? '' : undefined} />
      ))}
    </div>
  )
}

/** The models on this computer: the one in use, each with its size and whether it
 *  fits, a press to use one, and a confirmed removal. A download in progress is
 *  drawn above them with Stop. */
export function InstalledModels({ local, facts, chosen, running, onUse }: { local: LocalState; facts: Facts; chosen: string; running: boolean; onUse: (name: string) => void }) {
  const { models, pull } = local
  const inUse = models.some((model) => model.name === chosen)
  return (
    <Section title="Models on this computer" tour="local-models">
      {local.problem && <p className="error-note">{local.problem}</p>}
      {pull && <PullStatus local={local} pull={pull} />}
      {!local.modelsLoaded && !local.problem ? (
        <Loading />
      ) : !running ? (
        <Setting icon="cube" label="Model in use" note="The runtime is not running, so Kriko cannot list its models. Start it in step 1 of the set-up." />
      ) : (
        <Setting
          icon="cube"
          label="Model in use"
          value={<State tone={inUse ? 'ok' : 'none'}>{inUse ? chosen : 'None chosen'}</State>}
          note={models.length === 0 ? 'No models on this computer yet. Get one below.' : 'Press a model to use it. Remove takes it off this computer and frees its disk space.'}
          stack={models.length > 0}
          control={
            models.length > 0 ? (
              <ul className="keys-models" role="radiogroup" aria-label="Local model">
                {models.map((model) => (
                  <ModelRow key={model.name} model={model} fit={fitOf(model.size_bytes, facts)} active={model.name === chosen} onUse={() => onUse(model.name)} onRemove={() => local.remove(model.name)} />
                ))}
              </ul>
            ) : undefined
          }
        />
      )}
    </Section>
  )
}

/** A model download in progress, or the one that failed, with the words to act on it. */
function PullStatus({ local, pull }: { local: LocalState; pull: NonNullable<LocalState['pull']> }) {
  return (
    <div className="keys-pull localai-pull" data-failed={Boolean(pull.error)} role="status">
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
export function VllmRow({ plan, server, checking, onCheck }: { plan: VllmPlan; server: VllmServer | null; checking: boolean; onCheck: () => void }) {
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

/** Get a model: browse what fits this computer, type a name, or search Hugging
 *  Face. Each starts a download only on a press, and only while the runtime runs. */
export function FitModels({ local, facts, running }: { local: LocalState; facts: Facts; running: boolean }) {
  const pulling = Boolean(local.pull) && !local.pull?.error
  const installed = local.models.map((model) => model.name)
  return (
    <Section
      title="Models that fit this computer"
      note="A verdict compares the size of a model with the memory this computer reported. Sizes are estimates from the name, at 4 bits. Nothing downloads until you press Get."
    >
      <Setting icon="download" label="Get a model by name" note={running ? 'Type the name Ollama uses, for example qwen2.5:7b.' : 'Start the runtime first. Downloads go through Ollama.'} stack control={<GetModel local={local} pulling={pulling} running={running} />} />
      <Setting
        icon="search"
        label="Ollama library"
        note="The public list, read from the web only when you ask. What fits this computer comes first."
        stack
        control={
          !local.library ? (
            <span className="keys-actions">
              <button type="button" className="k-btn" onClick={() => void local.openLibrary()}>
                Show models that fit
              </button>
            </span>
          ) : (
            <Library local={local} facts={facts} pulling={pulling} running={running} installed={installed} />
          )
        }
      />
      <Setting icon="globe" label="Hugging Face" note="Models from Hugging Face that Ollama can run, with the size of each quantisation." stack control={<HuggingFace facts={facts} installed={installed} pulling={pulling || !running} onGet={(name) => void local.startPull(name)} />} />
    </Section>
  )
}

/** Type a model name to get it. A download starts only from the Get press or Enter. */
function GetModel({ local, pulling, running }: { local: LocalState; pulling: boolean; running: boolean }) {
  const [typed, setTyped] = useState('')
  return (
    <form
      className="keys-actions"
      onSubmit={(event) => {
        event.preventDefault()
        if (typed.trim() && !pulling && running) {
          void local.startPull(typed.trim())
          setTyped('')
        }
      }}
    >
      <input className="k-input" placeholder="Model name, for example qwen2.5:7b" aria-label="Model name" value={typed} onChange={(event) => setTyped(event.target.value)} spellCheck={false} />
      <button type="submit" className="k-btn" disabled={!typed.trim() || pulling || !running}>
        Get
      </button>
    </form>
  )
}

/** The public Ollama list, each size with its verdict. It is read from the web, so it opens when the reader asks. */
function Library({ local, facts, pulling, running, installed }: { local: LocalState; facts: Facts; pulling: boolean; running: boolean; installed: string[] }) {
  const { library } = local
  const [query, setQuery] = useState('')
  const [all, setAll] = useState(false)
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return fitRows(library ?? [], facts, local.recommended.model).filter((row) => !needle || `${row.name} ${row.about}`.toLowerCase().includes(needle))
  }, [library, facts, query, local.recommended.model])
  const shown = all || query.trim() ? rows : rows.slice(0, FIRST_ROWS)
  return (
    <div className="keys-stack">
      <label className="keys-search">
        <Icon name="search" size={15} />
        <input type="search" className="k-input" placeholder="Search the library" aria-label="Search the library" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      {local.libraryProblem && <p className="error-note">{local.libraryProblem}</p>}
      {rows.length === 0 && !local.libraryProblem && <small className="keys-result">Nothing matches. Try another word.</small>}
      <ul className="localai-fit-list">
        {shown.map((row) => {
          const has = installed.includes(row.name)
          const recommended = isRecommended(row.name, local.recommended.model)
          return (
            <li key={row.name} className="localai-fit" data-fit={row.fit}>
              <span className="localai-fit-main">
                <strong>{row.name}</strong>
                <small>{[row.bytes ? `About ${gb(row.bytes)}` : 'Size not listed', row.about].filter(Boolean).join(' · ')}</small>
              </span>
              <span className="localai-fit-tags">
                {recommended && <State tone="ok">Recommended</State>}
                <State tone={FIT_TONE[row.fit]}>{FIT_WORDS[row.fit]}</State>
              </span>
              <LibraryGet name={row.name} has={has} disabled={pulling || !running} onGet={(name) => void local.startPull(name)} />
            </li>
          )
        })}
      </ul>
      {!all && !query.trim() && rows.length > FIRST_ROWS && (
        <span className="keys-actions">
          <button type="button" className="k-btn" onClick={() => setAll(true)}>
            Show all {rows.length}
          </button>
        </span>
      )}
    </div>
  )
}

function LibraryGet({ name, has, disabled, onGet }: { name: string; has: boolean; disabled: boolean; onGet: (name: string) => void }) {
  return (
    <button type="button" className="k-btn" data-size="sm" disabled={disabled || has} onClick={() => onGet(name)} aria-label={has ? `${name} is installed` : `Get ${name}`}>
      {has ? 'Installed' : 'Get'}
    </button>
  )
}

/** Hugging Face models Ollama can pull. An expandable block: the search runs when
 *  the reader opens it, and a download starts only from a Get button. */
function HuggingFace({ facts, installed, pulling, onGet }: { facts: Facts; installed: string[]; pulling: boolean; onGet: (name: string) => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="keys-hf-block">
      <span className="keys-actions">
        <button type="button" className="k-btn" aria-expanded={open} onClick={() => setOpen((now) => !now)}>
          {open ? 'Hide Hugging Face' : 'Browse Hugging Face'}
        </button>
      </span>
      {open && <HfStore facts={facts} installed={installed} pulling={pulling} onGet={onGet} />}
    </div>
  )
}

function ModelRow({ model, fit, active, onUse, onRemove }: { model: Model; fit: Fit; active: boolean; onUse: () => void; onRemove: () => Promise<void> }) {
  const [asking, setAsking] = useState(false)
  const meta = [model.size_bytes ? gb(model.size_bytes) : 'Size not reported', model.params && model.params !== 'n/a' && model.params, model.quant].filter(Boolean).join(' · ')
  return (
    <li className="keys-model" data-asking={asking}>
      <button type="button" className="keys-model-use" role="radio" aria-checked={active} aria-label={`Use ${model.name}`} onClick={onUse}>
        <strong>{model.name}</strong>
        <small>{meta}</small>
      </button>
      {fit !== 'unknown' && <State tone={FIT_TONE[fit]}>{FIT_WORDS[fit]}</State>}
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

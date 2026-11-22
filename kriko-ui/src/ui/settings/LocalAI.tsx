import { useState } from 'react'
import { FIT_WORDS, estimateBytes, factsOf, fitOf, isRecommended, largestThatRunsWell, speedWords } from '../../engine/fit'
import { useLocal, useTryLocal } from '../../engine/local'
import { useLocalRuntimes } from '../../engine/runtimes'
import { usePrefsDoc } from '../../engine/settings'
import { ExternalLink } from '../ExternalLink'
import { FitModels, InstalledModels, Loading, VllmRow } from '../panels/Local'
import { CheckResult, LocalRuntimeRows } from '../panels/LocalRuntime'
import { showSettingsPage } from '../panels/settingsPages'
import { Section, Setting, SelectField, State } from '../panels/settingsParts'

const CONTEXTS = ['', '2048', '4096', '8192', '16384', '32768']
/** Where a reader gets the runtime. Kriko installs none for them. */
const RUNTIME_DOWNLOAD = 'https://ollama.com/download'
/** The longest question the engine takes; the box stops there so Send never meets a refusal. */
const MAX_PROMPT = 2000
const gbMb = (value: number) => `${(value / 1024).toFixed(value >= 10240 ? 0 : 1)} GB`

/** Bring a part of this section into view and, when asked, put the cursor in it. */
function reveal(id: string, focus = false) {
  const node = document.getElementById(id)
  node?.scrollIntoView({ block: 'center' })
  if (focus) node?.focus({ preventScroll: true })
}

/** Local AI: the model that runs on this computer, in the order a reader needs it.
 *  This computer, a four-step set-up, the models, a place to try one, quick
 *  actions, and the server details. Nothing is downloaded, started or asked
 *  unless the reader presses its button. */
export function LocalAI() {
  const local = useLocal()
  const rt = useLocalRuntimes()
  const trial = useTryLocal()
  const { doc, save } = usePrefsDoc()
  const { machine, runtime, models, recommended } = local
  const facts = factsOf(machine)
  const running = Boolean(runtime?.runtime)
  const ollama = machine?.runtimes.find((one) => one.id === 'ollama')
  const found = machine?.runtimes.filter((one) => one.installed).map((one) => one.name) ?? []
  const chosen = doc?.chosen.local_model ?? ''
  const inUse = models.some((model) => model.name === chosen)
  const installedRecommended = models.find((model) => isRecommended(model.name, recommended.model))
  const toUse = inUse ? chosen : (installedRecommended?.name ?? '')
  const forResearch = doc?.chosen.preferred_harness === 'local' && inUse
  const pulling = Boolean(local.pull) && !local.pull?.error
  const tried = Boolean(trial.answer)
  const done = [running, inUse, tried, forResearch]
  // One blue press per view: the first step not yet done.
  const next = done.indexOf(false)
  const tone = (step: number) => (next === step ? 'primary' : undefined)

  return (
    <>
      <ThisComputer local={local} />

      <Section
        title="Set up in 4 steps"
        aside={<State tone={done.every(Boolean) ? 'ok' : undefined}>{done.filter(Boolean).length} of 4 done</State>}
        note="Kriko marks a step done only when it can see that it is. A local model costs nothing to run, and it is slower than a hosted one."
      >
        {!local.modelsLoaded && !local.problem ? (
          <Loading rows={4} />
        ) : (
          <>
            <Setting
              label="1. Runtime"
              icon="server"
              state={<State tone={running ? 'ok' : undefined}>{running ? 'Done' : 'To do'}</State>}
              note={
                running
                  ? `Ollama is running at ${runtime?.url}. It loads the model and answers for Kriko.`
                  : ollama?.installed
                    ? 'Ollama is installed but not running. Start it and Kriko can list and download models.'
                    : `A runtime is the program that runs a model on this computer. ${found.length ? `Found: ${found.join(', ')}. Kriko downloads models through Ollama only.` : 'None found yet. Get Ollama, install it, then press Check again.'}`
              }
              control={
                running ? undefined : ollama?.installed ? (
                  <button type="button" className="k-btn" data-kind={tone(0)} onClick={() => void local.startRuntime()} disabled={local.starting}>
                    {local.starting ? 'Starting…' : 'Start Ollama'}
                  </button>
                ) : (
                  <>
                    <button type="button" className="k-btn" data-kind="quiet" onClick={() => void local.recheck()} disabled={local.checking}>
                      {local.checking ? 'Checking…' : 'Check again'}
                    </button>
                    <ExternalLink className="k-btn" data-kind={tone(0)} href={RUNTIME_DOWNLOAD}>
                      Get Ollama
                    </ExternalLink>
                  </>
                )
              }
            />
            <Setting
              label="2. Model"
              icon="cube"
              state={<State tone={inUse ? 'ok' : undefined}>{inUse ? 'Done' : 'To do'}</State>}
              value={inUse ? chosen : undefined}
              note={
                inUse
                  ? 'This is the model Kriko uses when research runs on this computer.'
                  : recommended.model
                    ? `${recommended.model} is the recommended model: ${fitSentence(recommended.model, facts)}`
                    : 'Choose a model that fits this computer.'
              }
              control={
                inUse ? (
                  <button type="button" className="k-btn" data-kind="quiet" onClick={() => reveal('local-models')}>
                    Choose another
                  </button>
                ) : installedRecommended ? (
                  <button type="button" className="k-btn" data-kind={tone(1)} onClick={() => void save({ local_model: installedRecommended.name })}>
                    Use it
                  </button>
                ) : recommended.model ? (
                  <button type="button" className="k-btn" data-kind={tone(1)} disabled={!running || pulling} onClick={() => void local.startPull(recommended.model)}>
                    {pulling ? 'Downloading…' : 'Get it'}
                  </button>
                ) : undefined
              }
            />
            <Setting
              label="3. Try it"
              icon="play"
              state={<State tone={tried ? 'ok' : undefined}>{tried ? 'Done' : 'To do'}</State>}
              note={tried ? 'The model answered.' : 'Ask it one question to see that it answers, and how fast.'}
              control={
                <button type="button" className="k-btn" data-kind={tone(2)} disabled={!running} onClick={() => reveal('local-try-input', true)}>
                  Try it
                </button>
              }
            />
            <Setting
              label="4. Use it for research"
              icon="check"
              state={<State tone={forResearch ? 'ok' : undefined}>{forResearch ? 'Done' : 'To do'}</State>}
              note={forResearch ? 'Research runs on this computer. Change it under Research.' : 'Makes this model the one that does your research, free of charge. You can switch back under Research.'}
              control={
                forResearch ? (
                  <button type="button" className="k-btn" data-kind="quiet" onClick={() => showSettingsPage('research')}>
                    Open Research
                  </button>
                ) : (
                  <button type="button" className="k-btn" data-kind={tone(3)} disabled={!toUse} onClick={() => void save({ preferred_harness: 'local', local_model: toUse })}>
                    Use it
                  </button>
                )
              }
            />
          </>
        )}
      </Section>

      <InstalledModels local={local} facts={facts} chosen={chosen} running={running} onUse={(name) => void save({ local_model: name })} />

      <FitModels local={local} facts={facts} running={running} />

      <TryIt trial={trial} model={toUse} enabled={running} />

      <Section title="Quick actions">
        <Setting
          icon="check"
          label="Check connection"
          note="Asks the server which models it lists and refreshes what Kriko knows about this computer."
          stack
          control={
            <div className="keys-stack">
              <span className="keys-actions">
                <button
                  type="button"
                  className="k-btn"
                  disabled={rt.checked === 'checking' || local.checking}
                  onClick={() => {
                    void rt.check(rt.doc?.chosen ?? '', rt.doc?.url ?? '')
                    void local.recheck()
                    void local.readModels()
                  }}
                >
                  {rt.checked === 'checking' ? 'Checking…' : 'Check connection'}
                </button>
              </span>
              <CheckResult checked={rt.checked} vllmStepsBelow={rt.doc?.chosen === 'vllm' && Boolean(machine?.vllm)} />
            </div>
          }
        />
        <Setting
          icon="play"
          label="Start Ollama"
          note={running ? 'Ollama is already running.' : ollama?.installed ? 'Opens Ollama in the background. It stays open until you quit it.' : 'Ollama is not installed on this computer.'}
          control={
            <button type="button" className="k-btn" onClick={() => void local.startRuntime()} disabled={running || !ollama?.installed || local.starting}>
              {local.starting ? 'Starting…' : 'Start Ollama'}
            </button>
          }
        />
        <Setting
          icon="retry"
          label="Reset to the recommended model"
          note={
            !recommended.model
              ? 'The recommended model is not known until the engine answers.'
              : installedRecommended
                ? `Uses ${installedRecommended.name} for local research.`
                : `${recommended.model} is not on this computer. This downloads it first${running ? '.' : ', so start the runtime.'}`
          }
          control={
            installedRecommended ? (
              <button type="button" className="k-btn" onClick={() => void save({ local_model: installedRecommended.name })}>
                Reset to recommended
              </button>
            ) : (
              <button type="button" className="k-btn" disabled={!recommended.model || !running || pulling} onClick={() => void local.startPull(recommended.model)}>
                {pulling ? 'Downloading…' : 'Get recommended'}
              </button>
            )
          }
        />
        {doc && (
          <>
            <Setting
              icon="gauge"
              label="Device"
              note="Automatic uses the graphics card when the model fits in it."
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
              note="Tokens the model reads at once. More lets it read longer pages and needs more memory."
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

      <Section title="Server program and address" note="Most readers never change these. Automatic finds the usual servers on this computer.">
        <LocalRuntimeRows rt={rt} />
        {machine?.vllm && <VllmRow plan={machine.vllm} server={local.vllm} checking={local.checking} onCheck={() => void local.recheck()} />}
      </Section>
    </>
  )
}

/** The verdict for a model by name, in a sentence. A model nobody has downloaded has only its name to go by. */
function fitSentence(name: string, facts: ReturnType<typeof factsOf>): string {
  const fit = fitOf(estimateBytes(name), facts)
  return fit === 'unknown' ? 'whether it fits this computer is not known.' : `${FIT_WORDS[fit].toLowerCase()} on this computer.`
}

/** The computer in plain facts. A field the machine did not report says so. */
function ThisComputer({ local }: { local: ReturnType<typeof useLocal> }) {
  const { machine, machineProblem } = local
  const facts = factsOf(machine)
  const big = largestThatRunsWell(facts)
  const words = (value: string | null | undefined) => (value && value.trim() ? value.trim() : 'Not reported')
  if (!machine) {
    return (
      <Section title="This computer">
        {machineProblem ? (
          <Setting
            icon="alert"
            label="This computer"
            note={`Could not read this computer. ${machineProblem}`}
            control={
              <button type="button" className="k-btn" onClick={() => void local.readMachine()}>
                Try again
              </button>
            }
          />
        ) : (
          <Loading rows={4} />
        )}
      </Section>
    )
  }
  return (
    <Section title="This computer" note="A model has to fit in memory to run well. The graphics card is the fastest place for it.">
      <Setting icon="cpu" label="Graphics card" value={words(machine.gpu?.name)} note="Runs a model many times faster than the processor." />
      <Setting icon="layers" label="Graphics memory" value={facts.vramMb !== null ? gbMb(facts.vramMb) : 'Not reported'} note="The model has to fit here, with some room left, to run well." />
      <Setting icon="layers" label="Memory" value={facts.ramMb !== null ? gbMb(facts.ramMb) : 'Not reported'} note="Used when there is no graphics card, or a model does not fit on it." />
      <Setting icon="cpu" label="Processor" value={words(machine.cpu?.name)} note={machine.cpu?.cores ? `${machine.cpu.cores} cores.` : 'The number of cores is not reported.'} />
      <Setting icon="gauge" label="What fits" value={big !== null ? `About ${big}B parameters` : 'Not reported'} note="The largest model that should run well here, from the memory above." />
    </Section>
  )
}

/** One question to the model, on a press. The engine bounds it and it costs nothing. */
function TryIt({ trial, model, enabled }: { trial: ReturnType<typeof useTryLocal>; model: string; enabled: boolean }) {
  const [prompt, setPrompt] = useState('')
  const { answer, busy, problem } = trial
  const speed = answer ? speedWords(answer.tokens_per_second) : null
  const send = () => {
    if (prompt.trim() && !busy && enabled) void trial.ask(prompt.trim(), model)
  }
  return (
    <Section title="Try it" tour="local-try" note="Runs on this computer, so it costs nothing. The first answer also loads the model, which can take a minute. Ask twice for a truer speed.">
      <Setting
        icon="chat"
        label="Ask the local model something"
        note={enabled ? 'It sends one short question and shows the answer here. Nothing is sent until you press Send.' : 'Start the runtime and choose a model first.'}
        stack
        control={
          <div className="keys-stack">
            <textarea
              id="local-try-input"
              className="k-input localai-try-input"
              aria-label="Ask the local model something"
              placeholder="For example: say hello in one sentence"
              rows={3}
              maxLength={MAX_PROMPT}
              value={prompt}
              disabled={!enabled}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) send()
              }}
            />
            <span className="keys-actions">
              <button type="button" className="k-btn" disabled={!prompt.trim() || busy || !enabled} onClick={send}>
                {busy ? 'Asking…' : 'Send'}
              </button>
              <small className="keys-result">{prompt.length} of {MAX_PROMPT} characters</small>
            </span>
            {problem && (
              <p className="error-note" role="alert">
                {problem}
              </p>
            )}
            {answer && (
              <div className="keys-check localai-answer" data-ok="true" role="status">
                <span className="localai-answer-text">{answer.text}</span>
                <small>
                  {answer.model} answered in {answer.seconds} seconds{answer.output_tokens ? `, ${answer.output_tokens} tokens` : ''}.
                </small>
                {speed ? <State tone={speed.tone}>{speed.text}</State> : <small>The server did not count tokens, so no speed is shown.</small>}
                {answer.truncated && <small>The answer was cut short to keep this quick.</small>}
              </div>
            )}
          </div>
        }
      />
    </Section>
  )
}

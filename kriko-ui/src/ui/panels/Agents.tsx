import { Disclosure } from '../Disclosure'
import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { effortKey, modelKey, searchKey, usePrefsDoc, type AgentRow } from '../../engine/settings'
import {
  IDLE,
  connectTarget,
  failed,
  finished,
  installAgent,
  installedAt,
  readMarket,
  readSkill,
  readTargets,
  rewriteTargetSkill,
  skillWords,
  verifyAgent,
  withSkill,
  working,
  wiringWords,
  type AgentTarget,
  type MarketAgent,
  type MarketDoc,
  type Press,
  type SkillDoc,
  type TargetsDoc,
  type VerifyAnswer,
} from '../../engine/agents'
import { followJob } from '../../engine/jobs'
import { useEngine } from '../../engine/Engine'
import { usePrefs } from '../../prefs'
import { ExternalLink } from '../ExternalLink'
import { Icon } from '../Icon'
import { Select } from '../controls'

/** Who answers, and how each of them is wired to *this* store.
 *
 *  Two surfaces live here and they are not the same question. The dials above
 *  are the reader's arrangement — which agent answers by default, with which
 *  model, effort and search. Everything below the market is the engine's own
 *  agent-integration surface (`src/app/web/routers/agent.py`), which no window
 *  called at all until now: what this installation can run, where each harness
 *  reads its config from, whether the protocol on disk is the one this build
 *  would write, whether the advertised command actually starts, and the one
 *  press that installs a CLI it cannot find.
 *
 *  The rule under all of it: every row, state and reason drawn here is one the
 *  engine reported. Nothing on this screen is a list kept in the window, so
 *  nothing on it can go stale against the machine. */
export function AgentsPanel(_: { onOpen?: (lookupId: string) => void }) {
  const { motion: m } = usePrefs()
  const { mode } = useEngine()
  const { doc, problem, busy, save, reload } = usePrefsDoc()
  const [open, setOpen] = useState<string | null>(null)
  const [market, setMarket] = useState<MarketDoc | null>(null)
  const [targets, setTargets] = useState<TargetsDoc | null>(null)
  /** True until the first read settles, so the screen never draws "the engine
   *  reported nothing" over a question it has not finished asking. */
  const [reading, setReading] = useState(true)
  const [surface, setSurface] = useState('')
  const [presses, setPresses] = useState<Record<string, Press>>({})
  const [skill, setSkill] = useState<SkillDoc | null>(null)
  const [skillPress, setSkillPress] = useState<Press>(IDLE)
  const [verifyPress, setVerifyPress] = useState<Press>(IDLE)
  const [verified, setVerified] = useState<VerifyAnswer | null>(null)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const put = (key: string, next: Press) => setPresses((now) => ({ ...now, [key]: next }))

  /** The market and the harnesses, read together: they are two views of one
   *  machine, and a row that arrived before its wiring would draw a state the
   *  engine has already left. */
  const readSurface = useCallback(async () => {
    if (mode !== 'live') return
    setReading(true)
    setSurface('')
    try {
      const [found, wired] = await Promise.all([readMarket(), readTargets()])
      if (!alive.current) return
      setMarket(found ?? null)
      setTargets(wired ?? null)
    } catch (error) {
      if (!alive.current) return
      setSurface(error instanceof Error ? error.message : 'The agents could not be read.')
    } finally {
      if (alive.current) setReading(false)
    }
  }, [mode])

  useEffect(() => {
    void readSurface()
  }, [readSurface])

  /** The reader's own "the machine changed" press. `/api/agent-market` reads
   *  what discovery already found, and only `prefs`' fresh read forgets it, so
   *  a CLI installed outside Kriko would otherwise stay invisible behind a
   *  button that looked like it checked. */
  const checkAgain = async () => {
    await reload(true)
    await readSurface()
  }

  /** Install runs a vendor's own installer, so it is a job: the id comes back at
   *  once and the log arrives as the job's own messages. */
  const install = async (agent: MarketAgent) => {
    const key = `install:${agent.id}`
    put(key, working('Starting the installer…'))
    try {
      const sent = await installAgent(agent.id)
      const ended = await followJob(
        sent.job_id,
        (reading) => put(key, working(reading.message || 'Installing…')),
        () => alive.current,
      )
      if (ended?.state !== 'succeeded') throw new Error(ended?.message || 'The install did not finish.')
      put(key, finished(ended.message || 'Installed.', installedAt(ended.result)))
      await readSurface()
    } catch (error) {
      put(key, failed(error, 'The install failed.'))
    }
  }

  /** Connect writes one entry into the harness's own config. What the screen
   *  then draws is read back from the engine, never assumed from the press. */
  const connect = async (target: AgentTarget) => {
    const key = `connect:${target.id}`
    put(key, working('Writing the config…'))
    try {
      const row = await connectTarget(target.id)
      await readSurface()
      put(key, finished(
        row.state === 'connected'
          ? `${row.label} now reads this store.`
          : `${row.label} is ${wiringWords(row.state).toLowerCase()}.`,
        row.skill ? `Protocol written to ${row.skill}` : '',
      ))
    } catch (error) {
      put(key, failed(error, 'The config could not be written.'))
    }
  }

  const refreshSkill = async (target: AgentTarget) => {
    const key = `skill:${target.id}`
    put(key, working('Writing the protocol…'))
    try {
      const answer = await rewriteTargetSkill(target.id)
      setTargets((now) => (now ? withSkill(now, target.id, answer.status) : now))
      put(key, finished(answer.skill ? `Protocol written to ${answer.skill}.` : 'The engine wrote nothing for this harness.'))
    } catch (error) {
      put(key, failed(error, 'The protocol could not be written.'))
    }
  }

  const readProtocol = async () => {
    setSkillPress(working('Rendering the protocol…'))
    try {
      const protocol = await readSkill()
      setSkill(protocol)
      setSkillPress(finished(`${protocol.name} · ${protocol.steps.length} step(s)`))
    } catch (error) {
      setSkillPress(failed(error, 'The protocol could not be read.'))
    }
  }

  /** A verdict, not a request: the engine answers 200 either way, and `ok` is
   *  what the reader needs. The command is the one this installation advertises
   *  — nothing here can name one. */
  const verify = async () => {
    setVerifyPress(working('Starting the advertised command…'))
    try {
      const answer = await verifyAgent()
      setVerified(answer)
      setVerifyPress(answer.ok
        ? finished(`${answer.server || 'The server'} answered with ${(answer.tools || []).length} tool(s).`)
        : { phase: 'failed', say: answer.detail || 'The command did not answer.', detail: '' })
    } catch (error) {
      setVerifyPress(failed(error, 'The verification could not run.'))
    }
  }

  return (
    <div className="panel-body">
      {!doc && problem && <p className="error-note" role="alert">Your agents could not be read. {problem}</p>}
      {!doc && !problem && <p className="panel-note">Reading the agents…</p>}

      {doc && (
        <>
          <p className="panel-note" data-ok={doc.effective.harness_ready}>
            {doc.effective.harness_ready ? 'The default agent is ready.' : doc.effective.harness_note || 'The default agent is not ready.'}
          </p>

          <ul className="agent-list" role="radiogroup" aria-label="Default agent">
            {doc.harnesses.map((agent) => (
              <AgentItem
                key={agent.id}
                agent={agent}
                isDefault={agent.id === (doc.chosen.preferred_harness || doc.effective.harness)}
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
        </>
      )}

      {mode !== 'live' ? (
        <section className="panel-group">
          <h3>The agents on this machine</h3>
          <p className="panel-note">
            {mode === 'checking'
              ? 'Looking for the engine…'
              : 'No engine is connected, so it has reported no market and no harness. Nothing is drawn here that the engine did not say.'}
          </p>
        </section>
      ) : (
        <>
          <section className="panel-group">
            <h3>The market</h3>
            <p className="panel-note">Every way of answering a question this installation can run, and what the engine found behind it.</p>
            {surface && <p className="error-note" role="alert">{surface}</p>}
            {market
              ? <MarketRows doc={market} presses={presses} onInstall={(agent) => void install(agent)} />
              : !surface && <p className="panel-note">{reading ? 'Reading the market…' : 'The engine reported no market.'}</p>}
            <button className="btn ghost" disabled={reading || busy} onClick={() => void checkAgain()}>
              {reading ? 'Looking…' : 'Check this machine again'}
            </button>
          </section>

          <section className="panel-group">
            <h3>Connected agents</h3>
            <p className="panel-note">Where this store is written for each harness the engine knows. Connect merges one entry into the harness's own config and leaves everything else in it alone.</p>
            {targets
              ? <TargetsRows doc={targets} presses={presses} onConnect={(one) => void connect(one)} onSkill={(one) => void refreshSkill(one)} />
              : !surface && <p className="panel-note">{reading ? 'Reading the harnesses…' : 'The engine reported no harness.'}</p>}
          </section>

          <section className="panel-group">
            <h3>The protocol</h3>
            <p className="panel-note">The document an agent is given: what it is asked to do, and where each answer must come from. It is rendered from the catalogs installed right now.</p>
            <button className="btn" disabled={skillPress.phase === 'working'} onClick={() => void readProtocol()}>
              {skillPress.phase === 'working' ? 'Rendering…' : 'Read the protocol'}
            </button>
            <PressNote press={skillPress} />
            {skill && <SkillReport doc={skill} />}
          </section>

          <section className="panel-group">
            <h3>Does it actually run?</h3>
            <p className="panel-note">Starts the command this installation advertises, completes an MCP handshake with it and asks it for its tools. Only that command is ever started.</p>
            <button className="btn" disabled={verifyPress.phase === 'working'} onClick={() => void verify()}>
              {verifyPress.phase === 'working' ? 'Verifying…' : 'Verify the connection'}
            </button>
            <PressNote press={verifyPress} />
            {verified && <VerifyReport answer={verified} />}
          </section>
        </>
      )}
    </div>
  )
}

/** One press, in its state. The sentence is the engine's from the moment it has
 *  one; `detail` is the path or model the engine named, never a guess at one. */
export function PressNote({ press }: { press: Press }) {
  if (press.phase === 'idle' || !press.say) return null
  return (
    <p
      className="press"
      data-state={press.phase}
      role={press.phase === 'failed' ? 'alert' : 'status'}
    >
      {press.say}
      {press.detail && <small className="panel-path">{press.detail}</small>}
    </p>
  )
}

/** The market as the engine reported it. Exported so the test can render it
 *  over a response it wrote, the way `KeysGroup` is in `Settings.tsx`. */
export function MarketRows({
  doc,
  presses,
  onInstall,
}: {
  doc: MarketDoc
  presses: Record<string, Press>
  onInstall: (agent: MarketAgent) => void
}) {
  if (doc.agents.length === 0) {
    return <p className="panel-note">The engine reported no way to answer on this machine. Nothing was found, so nothing is listed.</p>
  }
  return (
    <ul className="plain-list">
      {doc.agents.map((agent) => {
        const press = presses[`install:${agent.id}`] ?? IDLE
        const meta = [kindWords(agent.kind), standingWords(agent.state), agent.detail].filter(Boolean).join(' · ')
        return (
          <li key={agent.id} data-chosen={agent.chosen}>
            <strong>
              {agent.label}
              {agent.chosen && <span className="tag">Default</span>}
            </strong>
            <small>{meta}</small>
            {agent.where && <small className="panel-path">{agent.where}</small>}
            {agent.action && <small>Next: {agent.action}</small>}
            <div className="card-actions">
              {agent.can_install && (
                <button className="btn" disabled={press.phase === 'working'} onClick={() => onInstall(agent)}>
                  {press.phase === 'working' ? 'Installing…' : 'Install'}
                </button>
              )}
              {agent.url && <ExternalLink className="btn" href={agent.url}>Get it</ExternalLink>}
            </div>
            <PressNote press={press} />
          </li>
        )
      })}
    </ul>
  )
}

/** The harnesses the engine knows, and the two things it can do for each. */
export function TargetsRows({
  doc,
  presses,
  onConnect,
  onSkill,
}: {
  doc: TargetsDoc
  presses: Record<string, Press>
  onConnect: (target: AgentTarget) => void
  onSkill: (target: AgentTarget) => void
}) {
  if (doc.targets.length === 0) {
    return <p className="panel-note">The engine reported no harness on this machine. Nothing is wired, and nothing is listed.</p>
  }
  return (
    <>
      <p className="panel-note">The engine serves this store as <code>{doc.server_name}</code>.</p>
      <p className="panel-path">{doc.store}</p>
      <ul className="plain-list">
        {doc.targets.map((target) => {
          const connect = presses[`connect:${target.id}`] ?? IDLE
          const skill = presses[`skill:${target.id}`] ?? IDLE
          const busy = connect.phase === 'working' || skill.phase === 'working'
          return (
            <li key={target.id} data-state={target.state}>
              <strong>{target.label}</strong>
              <small>{wiringWords(target.state)}{target.detail ? ` · ${target.detail}` : ''}</small>
              <small className="panel-path">{target.path}</small>
              <small>{skillWords(target.skill)}</small>
              <div className="card-actions">
                <button className="btn" disabled={busy} onClick={() => onConnect(target)}>
                  {connect.phase === 'working' ? 'Connecting…' : target.state === 'connected' ? 'Write it again' : 'Connect'}
                </button>
                <button
                  className="btn ghost"
                  disabled={busy || !target.skill.supported}
                  onClick={() => onSkill(target)}
                >
                  {skill.phase === 'working' ? 'Writing…' : 'Write the protocol'}
                </button>
              </div>
              <PressNote press={connect} />
              <PressNote press={skill} />
            </li>
          )
        })}
      </ul>
    </>
  )
}

/** The handshake as the engine broke it down: one state per step, and the log
 *  behind a summary for the reader who asks (`agentconfig.handshake`). */
export function VerifyReport({ answer }: { answer: VerifyAnswer }) {
  return (
    <div className="press-report" data-state={answer.ok ? 'done' : 'failed'}>
      <p className="panel-note" data-ok={answer.ok}>
        {answer.ok ? `${answer.server || 'The server'} answered.` : answer.detail || 'The command did not answer.'}
      </p>
      <ul className="plain-list">
        {answer.steps.map((step) => (
          <li key={step.id}>
            <strong>{step.id}</strong>
            <small>{step.state}</small>
          </li>
        ))}
      </ul>
      {answer.ok && (answer.tools?.length ?? 0) > 0 && (
        <p className="panel-note">{answer.tools?.length} tool(s): {(answer.tools ?? []).join(', ')}</p>
      )}
      {answer.log && (
        <Disclosure title="Show the log">
          <pre className="press-log">{answer.log}</pre>
        </Disclosure>
      )}
    </div>
  )
}

/** The protocol, as the engine renders it for this store. */
export function SkillReport({ doc }: { doc: SkillDoc }) {
  return (
    <div className="press-report">
      <p className="panel-note">{doc.name} · {doc.steps.length} step(s)</p>
      {doc.steps.length > 0 && (
        <ul className="plain-list">
          {doc.steps.map((step) => (
            <li key={step.tool}>
              <strong>{step.tool}</strong>
              <small>{step.input} → {step.output}</small>
            </li>
          ))}
        </ul>
      )}
      {doc.body
        ? (
            <Disclosure title="Show the document">
              <pre className="press-log">{doc.body}</pre>
            </Disclosure>
          )
        : <p className="panel-note">The engine rendered no document.</p>}
    </div>
  )
}

/** What kind of thing a market row is, in the reader's words. The fact under
 *  them is `agent._kind`'s; this screen owns only the sentence. */
function kindWords(kind: string): string {
  if (kind === 'local') return 'A model on this machine'
  if (kind === 'api') return 'A keyed API agent'
  return 'A command-line agent'
}

function standingWords(state: string): string {
  if (state === 'ready') return 'Ready'
  if (state === 'needs_setup') return 'Needs setup'
  if (state === 'not_installed') return 'Not installed'
  return 'The engine reported no state'
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
  const summary = [agent.llm || 'Own default', agent.effort, agent.search === 'kriko' ? "Kriko's search" : ''].filter(Boolean).join(' · ')

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
            {agent.model_freeform ? (
              <FreeformModel agent={agent} onChange={onChange} />
            ) : (
              <div className="setting">
                <span>Model</span>
                <Select
                  label={`${agent.label} model`}
                  value={agent.llm}
                  options={[{ value: '', label: 'Own default' }, ...models.map((id) => ({ value: id, label: id }))]}
                  onChange={(value) => onChange({ [modelKey(agent)]: value })}
                />
              </div>
            )}
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
            {agent.search_choices && agent.search_choices.length > 0 && (
              <div className="setting">
                <span>
                  Web search
                  <small>
                    {agent.search === 'kriko'
                      ? 'Kriko searches and reads the pages, so every quote is checked against a page Kriko fetched.'
                      : 'The agent searches and opens pages with its own tools.'}
                  </small>
                </span>
                <Select
                  label={`${agent.label} web search`}
                  value={agent.search || 'own'}
                  options={agent.search_choices.map((one) => ({ value: one.id, label: one.label }))}
                  onChange={(value) => onChange({ [searchKey(agent)]: value })}
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

function FreeformModel({ agent, onChange }: { agent: AgentRow; onChange: (patch: Record<string, string>) => void }) {
  const [draft, setDraft] = useState(agent.llm)
  useEffect(() => setDraft(agent.llm), [agent.llm])
  return (
    <div className="setting">
      <span>
        Model
        <small>{agent.llm_hint || 'Model name accepted by this endpoint.'}</small>
      </span>
      <input
        type="text"
        autoComplete="off"
        spellCheck={false}
        aria-label={`${agent.label} model`}
        placeholder="gpt-4o-mini or provider model ID"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => {
          const next = draft.trim()
          if (next !== agent.llm) onChange({ [modelKey(agent)]: next })
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur()
        }}
      />
    </div>
  )
}

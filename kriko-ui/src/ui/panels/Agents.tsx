import { useCallback, useEffect, useRef, useState } from 'react'
import { ReportButton } from '../ReportButton'
import { Disclosure } from '../Disclosure'
import { ExternalLink } from '../ExternalLink'
import { effortKey, modelKey, searchKey, type AgentRow, type PrefsDoc } from '../../engine/settings'
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
import { SelectField, Section, Setting, State } from './settingsParts'

/** Research's first section: who answers. The reader's choice is the first row,
 *  and `Change` opens the list of agents in place, under it. Each agent is a row
 *  with a state word and the words that can be pressed on it.
 *
 *  Two sources meet here. The reader's arrangement (the default agent, its model,
 *  effort and web search) is the store's own `/api/prefs`, handed in as `doc`.
 *  What this machine can run, and how each harness is wired to this store, is the
 *  engine's market and harness reads. Every state word and reason drawn here is
 *  one the engine reported; a row is never invented, and with no engine the
 *  presses that would touch the machine are not offered. */

export interface AgentsSectionProps {
  doc: PrefsDoc
  busy: boolean
  save: (patch: Record<string, string>) => unknown
  reload: (fresh?: boolean) => Promise<void>
}

/** One agent as a row: from the engine's market when it has answered, otherwise
 *  from the store's own lists (usable, not installed, found but not usable). */
interface AgentLine {
  id: string
  label: string
  kind: string
  state: string
  detail: string
  url: string
  canInstall: boolean
  usable: boolean
}

export function AgentsSection({ doc, busy, save, reload }: AgentsSectionProps) {
  const { mode } = useEngine()
  const live = mode === 'live'
  const [open, setOpen] = useState(false)
  const [market, setMarket] = useState<MarketDoc | null>(null)
  const [targets, setTargets] = useState<TargetsDoc | null>(null)
  /** True until the first read settles, so the list never shows "nothing" over a
   *  question the engine has not finished answering. */
  const [reading, setReading] = useState(false)
  const [surface, setSurface] = useState('')
  const [presses, setPresses] = useState<Record<string, Press>>({})
  const [verified, setVerified] = useState<VerifyAnswer | null>(null)
  const [protocol, setProtocol] = useState<SkillDoc | null>(null)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const put = (key: string, next: Press) => setPresses((now) => ({ ...now, [key]: next }))

  /** The market and the harnesses are two views of one machine, so they are read
   *  together and drawn together. */
  const readSurface = useCallback(async () => {
    if (mode !== 'live') {
      setMarket(null)
      setTargets(null)
      setReading(false)
      return
    }
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

  /** Looks at the machine again. The engine's market is a cached read until the
   *  preferences are read fresh, so both happen. */
  const checkAgain = async () => {
    await reload(true)
    await readSurface()
  }

  /** Install runs a vendor's installer, so it is a job: the id comes back at once
   *  and the log arrives as the job's own messages. */
  const install = async (agent: AgentLine) => {
    const key = `install:${agent.id}`
    put(key, working('Starting the installer…'))
    try {
      const sent = await installAgent(agent.id)
      const ended = await followJob(
        sent.job_id,
        (step) => put(key, working(step.message || 'Installing…')),
        () => alive.current,
      )
      if (ended?.state !== 'succeeded') throw new Error(ended?.message || 'The install did not finish.')
      put(key, finished(ended.message || 'Installed.', installedAt(ended.result)))
      await readSurface()
    } catch (error) {
      put(key, failed(error, 'The install failed.'))
    }
  }

  /** Set up writes one entry into the agent's own config, so it reads this store. */
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
        row.skill ? `Instructions written to ${row.skill}` : '',
      ))
    } catch (error) {
      put(key, failed(error, 'The config could not be written.'))
    }
  }

  const writeInstructions = async (target: AgentTarget) => {
    const key = 'instructions'
    put(key, working('Writing the instructions…'))
    try {
      const answer = await rewriteTargetSkill(target.id)
      setTargets((now) => (now ? withSkill(now, target.id, answer.status) : now))
      put(key, finished(answer.skill ? `Instructions written to ${answer.skill}.` : 'Nothing was written for this agent.'))
    } catch (error) {
      put(key, failed(error, 'The instructions could not be written.'))
    }
  }

  const readInstructions = async () => {
    put('read', working('Reading the instructions…'))
    try {
      const found = await readSkill()
      setProtocol(found)
      put('read', finished(`${found.name} · ${found.steps.length} step(s)`))
    } catch (error) {
      put('read', failed(error, 'The instructions could not be read.'))
    }
  }

  /** A verdict, not a request: the engine answers 200 either way, and `ok` is what
   *  the reader needs. The command is the one this installation advertises. */
  const verify = async () => {
    put('verify', working('Starting the command Kriko gives agents…'))
    try {
      const answer = await verifyAgent()
      setVerified(answer)
      put('verify', answer.ok
        ? finished(`${answer.server || 'The server'} answered with ${(answer.tools || []).length} tool(s).`)
        : { phase: 'failed', say: answer.detail || 'The command did not answer.', detail: '' })
    } catch (error) {
      put('verify', failed(error, 'The check could not run.'))
    }
  }

  const chosenId = doc.chosen.preferred_harness || doc.effective.harness
  const lines = linesOf(doc, market)
  const chosen = lines.find((line) => line.id === chosenId)
  const chosenName = chosen?.label || doc.harnesses.find((one) => one.id === chosenId)?.label || chosenId
  const chosenAgent = doc.harnesses.find((one) => one.id === chosenId)
  const chosenTarget = targets?.targets.find((one) => one.id === chosenId)
  const ready = doc.effective.harness_ready
  const readyNote = ready
    ? 'The agent that answers chat and runs research. Change it to pick another.'
    : doc.effective.harness_note || 'The agent that answers is not ready. Pick another, or set this one up.'

  return (
    <Section title="Agent">
      <Setting
        label="Answering agent"
        note={readyNote}
        state={<State tone={ready ? 'ok' : 'warn'}>{ready ? 'Ready' : 'Not ready'}</State>}
        value={chosenName}
        control={
          <button type="button" className="k-btn" data-size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? 'Close' : 'Change'}
          </button>
        }
      />

      {open && (
        <>
          {lines.length === 0 && !reading && <p className="research-agent-note">No agent was reported, so none is listed.</p>}
          {lines.map((line) => (
            <AgentLineRow
              key={line.id}
              line={line}
              chosen={line.id === chosenId}
              live={live}
              target={targets?.targets.find((one) => one.id === line.id)}
              presses={presses}
              verified={line.id === chosenId ? verified : null}
              onUse={() => void save({ preferred_harness: line.id })}
              onInstall={() => void install(line)}
              onSetUp={(target) => void connect(target)}
              onVerify={() => void verify()}
            />
          ))}
          <div className="k-row research-agent-foot">
            <span className="k-row-main">
              <span className="k-row-note">
                {surface || (reading ? 'Reading the agents…' : live ? '' : mode === 'checking' ? 'Looking for the engine…' : 'No engine is connected, so Install, Verify and Set up are off.')}
              </span>
              {surface && <ReportButton note={surface} />}
            </span>
            <span className="k-row-control">
              {live && (
                <button type="button" className="k-btn" data-size="sm" disabled={reading || busy} onClick={() => void checkAgain()}>
                  {reading ? 'Looking…' : 'Check again'}
                </button>
              )}
            </span>
          </div>
        </>
      )}

      {chosenAgent?.model_freeform && (
        <FreeformModel agent={chosenAgent} onSave={(patch) => void save(patch)} />
      )}
      {chosenAgent && !chosenAgent.model_freeform && (
        <Setting
          label="Model"
          note={chosenAgent.llms_note || 'The model this agent answers with. Own default leaves the choice to the agent.'}
          control={
            <SelectField
              label={`${chosenAgent.label} model`}
              value={chosenAgent.llm}
              options={[{ value: '', label: 'Own default' }, ...withCurrent(chosenAgent.llms, chosenAgent.llm).map((id) => ({ value: id, label: id }))]}
              onChange={(value) => void save({ [modelKey(chosenAgent)]: value })}
            />
          }
        />
      )}
      {chosenAgent && chosenAgent.efforts.length > 0 && (
        <Setting
          label="Effort"
          note="How hard the agent works on each question. A higher effort takes longer and uses more of its allowance."
          control={
            <SelectField
              label={`${chosenAgent.label} effort`}
              value={chosenAgent.effort}
              options={[{ value: '', label: 'Own default' }, ...withCurrent(chosenAgent.efforts, chosenAgent.effort).map((id) => ({ value: id, label: id }))]}
              onChange={(value) => void save({ [effortKey(chosenAgent)]: value })}
            />
          }
        />
      )}
      {chosenAgent?.search_choices && chosenAgent.search_choices.length > 0 && (
        <Setting
          label="Web search"
          note={
            chosenAgent.search === 'kriko'
              ? 'Kriko searches and reads the pages, so every quote is checked against a page Kriko fetched.'
              : 'The agent searches and opens pages with its own tools.'
          }
          control={
            <SelectField
              label={`${chosenAgent.label} web search`}
              value={chosenAgent.search || 'own'}
              options={chosenAgent.search_choices.map((one) => ({ value: one.id, label: one.label }))}
              onChange={(value) => void save({ [searchKey(chosenAgent)]: value })}
            />
          }
        />
      )}

      <Setting
        label="Instructions for the agent"
        note="The instructions it is given: what it must ask for, and where each answer must come from. Written from the catalogs installed now."
        control={
          <span className="research-agent-buttons">
            <button type="button" className="k-btn" data-size="sm" disabled={!live} onClick={() => void readInstructions()}>
              Read them
            </button>
            {chosenTarget?.skill.supported && (
              <button type="button" className="k-btn" data-size="sm" disabled={!live || busy} onClick={() => void writeInstructions(chosenTarget)}>
                Write them
              </button>
            )}
          </span>
        }
      />
      <div className="research-agent-extra">
        {chosenTarget && <p className="research-agent-note">{skillWords(chosenTarget.skill)}.</p>}
        <PressNote press={presses.read ?? IDLE} />
        <PressNote press={presses.instructions ?? IDLE} />
        {protocol && <SkillReport doc={protocol} />}
      </div>
    </Section>
  )
}

/** One agent as a row: its name, its state as a word, its own note, and the
 *  presses that can be made on it. Verify and its report belong to the agent that
 *  answers, since that is the command the window checks. */
function AgentLineRow({
  line,
  chosen,
  live,
  target,
  presses,
  verified,
  onUse,
  onInstall,
  onSetUp,
  onVerify,
}: {
  line: AgentLine
  chosen: boolean
  live: boolean
  target?: AgentTarget
  presses: Record<string, Press>
  verified: VerifyAnswer | null
  onUse: () => void
  onInstall: () => void
  onSetUp: (target: AgentTarget) => void
  onVerify: () => void
}) {
  const install = presses[`install:${line.id}`] ?? IDLE
  const connect = presses[`connect:${line.id}`] ?? IDLE
  const verify = presses.verify ?? IDLE
  const standing = standingOf(line)
  const note = [kindWords(line.kind), line.detail].filter(Boolean).join(' · ')
  return (
    <>
      <div className="k-row research-agent" data-state={line.state} data-chosen={chosen || undefined}>
        <span className="k-row-main">
          <span className="k-row-title">
            {line.label}
            {standing.word && <State tone={standing.tone}>{standing.word}</State>}
          </span>
          {note && <span className="k-row-note">{chosen ? `Answers now. ${note}` : note}</span>}
          <PressNote press={install} />
          {target && live && <PressNote press={connect} />}
          {chosen && <PressNote press={verify} />}
        </span>
        <span className="k-row-control research-agent-buttons">
          {!chosen && line.usable && (
            <button type="button" className="k-btn" data-size="sm" onClick={onUse}>
              Use
            </button>
          )}
          {chosen && live && (
            <button type="button" className="k-btn" data-size="sm" disabled={verify.phase === 'working'} onClick={onVerify}>
              {verify.phase === 'working' ? 'Verifying…' : 'Verify'}
            </button>
          )}
          {live && line.canInstall && line.state !== 'ready' && (
            <button type="button" className="k-btn" data-size="sm" disabled={install.phase === 'working'} onClick={onInstall}>
              {install.phase === 'working' ? 'Installing…' : 'Install'}
            </button>
          )}
          {live && target && (
            <button type="button" className="k-btn" data-size="sm" disabled={connect.phase === 'working'} onClick={() => onSetUp(target)}>
              {connect.phase === 'working' ? 'Setting up…' : target.state === 'connected' ? 'Set up again' : 'Set up'}
            </button>
          )}
          {line.url && (
            <ExternalLink className="k-btn" data-size="sm" href={line.url}>
              Get it
            </ExternalLink>
          )}
        </span>
      </div>
      {chosen && verified && (
        <div className="research-agent-extra">
          <VerifyReport answer={verified} />
        </div>
      )}
    </>
  )
}

/** A model name typed by hand, for an endpoint that takes any name. */
function FreeformModel({ agent, onSave }: { agent: AgentRow; onSave: (patch: Record<string, string>) => void }) {
  const [draft, setDraft] = useState(agent.llm)
  useEffect(() => setDraft(agent.llm), [agent.llm])
  return (
    <Setting
      label="Model"
      note={agent.llm_hint || 'Model name accepted by this endpoint.'}
      stack
      control={
        <input
          className="k-input"
          type="text"
          autoComplete="off"
          spellCheck={false}
          aria-label={`${agent.label} model`}
          placeholder="gpt-4o-mini or provider model ID"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => {
            const next = draft.trim()
            if (next !== agent.llm) onSave({ [modelKey(agent)]: next })
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') event.currentTarget.blur()
          }}
        />
      }
    />
  )
}

/** One press, in its state. The sentence is the engine's from the moment it has
 *  one; `detail` is the path or model the engine named, never a guess at one. */
export function PressNote({ press }: { press: Press }) {
  if (press.phase === 'idle' || !press.say) return null
  return (
    <p className="press" data-state={press.phase} role={press.phase === 'failed' ? 'alert' : 'status'}>
      {press.say}
      {press.detail && <small className="panel-path">{press.detail}</small>}
    </p>
  )
}

/** The handshake as the engine broke it down: one state per step, and the log
 *  behind a summary for the reader who asks. */
export function VerifyReport({ answer }: { answer: VerifyAnswer }) {
  return (
    <div className="press-report" data-state={answer.ok ? 'done' : 'failed'}>
      <p className="research-agent-note" data-ok={answer.ok}>
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
        <p className="research-agent-note">{answer.tools?.length} tool(s): {(answer.tools ?? []).join(', ')}</p>
      )}
      {answer.log && (
        <Disclosure title="Show the log">
          <pre className="press-log">{answer.log}</pre>
        </Disclosure>
      )}
    </div>
  )
}

/** The instructions as the engine renders them for this store. */
export function SkillReport({ doc }: { doc: SkillDoc }) {
  return (
    <div className="press-report">
      <p className="research-agent-note">{doc.name} · {doc.steps.length} step(s)</p>
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
        : <p className="research-agent-note">The engine rendered no document.</p>}
    </div>
  )
}

/** The rows: the engine's market when it has answered, otherwise the store's own
 *  lists. Each agent appears once. */
function linesOf(doc: PrefsDoc, market: MarketDoc | null): AgentLine[] {
  const usable = new Set(doc.harnesses.map((one) => one.id))
  if (market) {
    return market.agents.map((agent: MarketAgent) => ({
      id: agent.id,
      label: agent.label,
      kind: agent.kind,
      state: agent.state,
      detail: agent.detail || agent.where,
      url: agent.url,
      canInstall: agent.can_install,
      usable: usable.has(agent.id) || agent.state === 'ready',
    }))
  }
  const seen = new Set<string>()
  const lines: AgentLine[] = []
  const add = (line: AgentLine) => {
    if (seen.has(line.id)) return
    seen.add(line.id)
    lines.push(line)
  }
  for (const one of doc.harnesses) {
    add({ id: one.id, label: one.label, kind: one.local ? 'local' : 'cli', state: 'ready', detail: one.path ?? '', url: '', canInstall: false, usable: true })
  }
  for (const one of doc.unusable) {
    add({ id: one.id, label: one.label, kind: '', state: 'needs_setup', detail: one.why, url: '', canInstall: false, usable: false })
  }
  for (const one of doc.missing) {
    add({ id: one.id, label: one.label, kind: '', state: 'not_installed', detail: one.install_hint ?? '', url: '', canInstall: false, usable: false })
  }
  return lines
}

/** The word and tone of a state, in this screen's words. The engine's state is
 *  the input; a keyed agent that is not set up is one that needs a key. */
function standingOf(line: AgentLine): { word: string; tone?: 'ok' | 'warn' } {
  if (line.state === 'ready') return { word: 'Ready', tone: 'ok' }
  if (line.state === 'needs_setup') return { word: line.kind === 'api' ? 'Needs a key' : 'Needs setup', tone: 'warn' }
  if (line.state === 'not_installed') return { word: 'Not installed' }
  return { word: '' }
}

function kindWords(kind: string): string {
  if (kind === 'local') return 'A model on this machine'
  if (kind === 'api') return 'A keyed API agent'
  if (kind === 'cli') return 'A command-line agent'
  return ''
}

const withCurrent = (list: string[], current: string) => (current && !list.includes(current) ? [current, ...list] : list)

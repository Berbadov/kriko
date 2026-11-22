import { memo, useEffect, useRef, useState } from 'react'
import { capLine, overCap, useCaps } from '../engine/caps'
import { useUsage } from '../engine/usage'
import {
  RESOURCE_WORDS,
  WINDOW_WORDS,
  agentLimits,
  ago,
  left,
  pillParts,
  resetsIn,
  standingOf,
  statusWord,
  usedResources,
  verdictLine,
  type AgentLimits,
  type Meters,
  type Resource,
  type ResourceId,
  type SourceSum,
  type WindowId,
  type WindowSum,
} from '../engine/usagemeters'
import { formatTokens, formatUsd } from '../chat/view'
import { AgentMark } from './AgentMark'
import { Icon, type IconName } from './Icon'
import { ProgressBar } from './controls'
import { showDrawer } from './drawerEvents'
import { showSettingsPage } from './panels/settingsPages'

const ICONS: Record<Exclude<ResourceId, 'cli_agent'>, IconName> = { llm_api: 'spark', web_search: 'globe', local_model: 'cpu' }

/** The four rolling windows, in the order a reader thinks of them. */
const WINDOWS: WindowId[] = ['5h', '24h', '7d', '30d']

/** Three bars that rise like a signal, lit by how much is left. */
function Gauge({ fill }: { fill: number }) {
  const lit = fill > 0.6 ? 3 : fill > 0.25 ? 2 : 1
  const tone = fill <= 0.05 ? 'out' : fill <= 0.2 ? 'warn' : 'ok'
  return (
    <span className="usage-gauge" data-lit={lit} data-tone={tone} aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  )
}

/** The usage pill in the top strip and the card it opens. The pill says the two
 *  things worth a glance: how much of the tightest coding-agent window is left,
 *  and what the last day cost. The card opens with one plain sentence built from
 *  the numbers, then keeps every resource apart, each window a labelled row. A
 *  number nobody reported is not drawn, and a resource never used is left out. */
export const UsagePill = memo(function UsagePill() {
  const { meters, demo, reload } = useUsage()
  const { caps } = useCaps()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const now = meters?.as_of ?? 0

  useEffect(() => {
    if (!open) return
    reload()
    const out = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false)
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', out)
    window.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('pointerdown', out)
      window.removeEventListener('keydown', key)
    }
  }, [open, reload])

  const used = usedResources(meters)
  if (!meters || used.length === 0) return null
  const { fill, text } = pillParts(meters)
  const passed = used.filter((id) => overCap(meters, id, caps[id]))
  const over = passed.length > 0
  const verdict = verdictLine(meters, passed)

  const setCaps = () => {
    setOpen(false)
    showDrawer('settings')
    showSettingsPage('usage')
  }

  return (
    <div className="topbar-usage" ref={box}>
      <button className="usage-pill" data-over={over || undefined} onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="dialog" data-tour="usage" title={over ? 'A daily cap is passed' : 'What you have used'}>
        {fill !== null && <Gauge fill={fill} />}
        <span className="mono">{fill !== null ? `${Math.round(fill * 100)}% left` : ''}</span>
        {text && <span className="mono usage-pill-text">{text}</span>}
        {fill === null && !text && <Icon name="clock" size={15} />}
      </button>
      {open && (
        <div className="usage-card" role="dialog" aria-label="What you have used">
          {demo && <p className="usage-demo">Example numbers. Nothing here was measured.</p>}
          {verdict && (
            <p className="usage-verdict" data-over={over || undefined}>
              {verdict}
            </p>
          )}
          {used.map((id) => (
            <ResourceBlock key={id} id={id} resource={meters.resources[id]} now={now} cap={caps[id]} meters={meters} />
          ))}
          <div className="usage-foot">
            <p className="usage-note">A cap only warns. It never stops a run.</p>
            <button type="button" className="usage-link" onClick={setCaps}>
              Set caps
            </button>
          </div>
          <p className="usage-note">Counts what Kriko itself sent. Use outside Kriko, and any balance at a provider, is not visible here.</p>
        </div>
      )}
    </div>
  )
})

function ResourceBlock({ id, resource, now, cap, meters }: { id: ResourceId; resource: Resource; now: number; cap: number | null; meters: Meters }) {
  const words = RESOURCE_WORDS[id]
  const agents = id === 'cli_agent' ? agentLimits(resource) : []
  const line = capLine(meters, id, cap)
  const over = overCap(meters, id, cap)
  return (
    <section className="usage-block" data-resource={id}>
      <header>
        <span className="usage-icon">{id === 'cli_agent' ? <AgentMark id={agents[0]?.agent ?? 'claude-code'} size={22} /> : <Icon name={ICONS[id]} size={17} />}</span>
        <div>
          <strong>{words.title}</strong>
          <small>{words.line}</small>
        </div>
      </header>

      {agents.map((agent) => (
        <LimitRows key={agent.agent} agent={agent} now={now} />
      ))}
      {id === 'cli_agent' && agents.length === 0 && <p className="usage-asof">This agent has not reported its limits yet. They appear after its next run.</p>}

      <ul className="usage-rows" aria-label={`${words.title}, by window`}>
        {WINDOWS.map((name) => {
          const sum = resource.windows[name]
          if (!sum) return null
          return <WindowRow key={name} id={id} name={name} sum={sum} cap={name === '24h' ? line : ''} over={name === '24h' && over} />
        })}
      </ul>

      <Sources id={id} rows={resource.by_source} />
    </section>
  )
}

/** The limits a coding agent reported for itself. Kriko does not work them out. */
function LimitRows({ agent, now }: { agent: AgentLimits; now: number }) {
  return (
    <div className="usage-limits">
      <p className="usage-group">Limits {agent.agent} reported</p>
      <ul className="usage-rows">
        {agent.windows.map((window) => {
          const remaining = left(window.used)
          const standing = standingOf(window)
          const reset = resetsIn(window.resets_at, now)
          const usedText = window.used !== null && Number.isFinite(window.used) ? `${Math.min(100, Math.round(window.used * 100))}% used` : statusWord(window.status) || 'No figure given'
          const notes = [reset ? `Resets in ${reset}` : '', window.overage ? 'Using extra usage' : ''].filter(Boolean).join(' · ')
          return (
            <li key={window.id} className="usage-row" data-standing={standing}>
              <span className="usage-row-name">{window.label}</span>
              <span className="usage-row-used mono">{usedText}</span>
              {remaining !== null && (
                <span className="usage-row-bar">
                  <ProgressBar value={remaining} size="sm" tone={standing === 'ok' ? undefined : standing} />
                </span>
              )}
              {notes && <span className="usage-row-note">{notes}</span>}
            </li>
          )
        })}
      </ul>
      {agent.newest !== null && (
        <small className="usage-asof">
          {agent.agent} said so {ago(agent.newest, now)}, in a run Kriko started.
        </small>
      )}
    </div>
  )
}

const number = (value: number | null) => (value === null ? null : value.toLocaleString('en-GB'))

/** What one window used, in the words the resource is counted in. */
function usedWords(id: ResourceId, sum: WindowSum): string {
  const calls = number(sum.calls)
  if (id === 'web_search') return `${calls} ${sum.calls === 1 ? 'search' : 'searches'}${sum.misses ? ` · ${sum.misses} empty` : ''}`
  const noun = id === 'cli_agent' ? (sum.calls === 1 ? 'run' : 'runs') : sum.calls === 1 ? 'call' : 'calls'
  const tokens = sum.tokens_in !== null && sum.tokens_out !== null ? `${formatTokens(sum.tokens_in)} in · ${formatTokens(sum.tokens_out)} out` : sum.tokens !== null ? `${formatTokens(sum.tokens)} tokens` : ''
  return [`${calls} ${noun}`, tokens].filter(Boolean).join(' · ')
}

/** One window as a labelled row: what it used, the cap when it has one, and the
 *  cost in dollars where a price was known, or "Not priced" where none was. */
function WindowRow({ id, name, sum, cap, over }: { id: ResourceId; name: WindowId; sum: WindowSum; cap: string; over: boolean }) {
  const cost = sum.usd !== null ? `${formatUsd(sum.usd)} spent` : 'Not priced'
  return (
    <li className="usage-row" data-priced={sum.usd !== null || undefined}>
      <span className="usage-row-name">{WINDOW_WORDS[name]}</span>
      <span className="usage-row-used mono">{usedWords(id, sum)}</span>
      <span className="usage-row-cost mono" data-none={sum.usd === null || undefined}>
        {cost}
      </span>
      {cap && (
        <span className="usage-row-cap" data-over={over || undefined}>
          {cap}
          {over && <span className="usage-cap-mark"> · Cap passed</span>}
        </span>
      )}
    </li>
  )
}

function Sources({ id, rows }: { id: ResourceId; rows: SourceSum[] }) {
  if (rows.length < 2 && !(rows.length === 1 && rows[0].model)) return null
  return (
    <ul className="usage-sources" aria-label="By source, last 7 days">
      {rows.slice(0, 5).map((row) => (
        <li key={`${row.source}-${row.model}`}>
          <span>{[row.source, row.model].filter(Boolean).join(' · ')}</span>
          <span className="mono">
            {row.calls} {id === 'web_search' ? 'searches' : 'calls'}
            {row.usd !== null ? ` · ${formatUsd(row.usd)}` : ''}
          </span>
        </li>
      ))}
    </ul>
  )
}

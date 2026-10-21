import { useEffect, useRef, useState } from 'react'
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
  type Resource,
  type ResourceId,
  type SourceSum,
  type WindowSum,
} from '../engine/usagemeters'
import { formatTokens, formatUsd } from '../chat/view'
import { AgentMark } from './AgentMark'
import { Icon, type IconName } from './Icon'
import { ProgressBar } from './controls'

const ICONS: Record<Exclude<ResourceId, 'cli_agent'>, IconName> = { llm_api: 'spark', web_search: 'globe', local_model: 'cpu' }

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

/** The usage pill in the top bar and the card it opens. The pill says the two
 *  things worth a glance: how much of the tightest coding-agent window is left,
 *  and what the last day cost. The card keeps every resource apart. A number
 *  nobody reported is not drawn, and a resource never used is left out. */
export function UsagePill() {
  const { meters, demo, reload } = useUsage()
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

  return (
    <div className="topbar-usage" ref={box}>
      <button className="usage-pill" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="dialog" data-tour="usage" title="What you have used">
        {fill !== null && <Gauge fill={fill} />}
        <span className="mono">{fill !== null ? `${Math.round(fill * 100)}% left` : ''}</span>
        {text && <span className="mono usage-pill-text">{text}</span>}
        {fill === null && !text && <Icon name="clock" size={15} />}
      </button>
      {open && (
        <div className="usage-card" role="dialog" aria-label="What you have used">
          {demo && <p className="usage-demo">Example numbers. Nothing here was measured.</p>}
          {used.map((id) => (
            <ResourceBlock key={id} id={id} resource={meters.resources[id]} now={now} />
          ))}
          <p className="usage-note">Counts what Kriko itself sent. Use outside Kriko, and any balance at a provider, is not visible here.</p>
        </div>
      )}
    </div>
  )
}

function ResourceBlock({ id, resource, now }: { id: ResourceId; resource: Resource; now: number }) {
  const words = RESOURCE_WORDS[id]
  const agents = id === 'cli_agent' ? agentLimits(resource) : []
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
        <div key={agent.agent} className="usage-limits">
          {agent.windows.map((window) => {
            const remaining = left(window.used)
            const standing = standingOf(window)
            const reset = resetsIn(window.resets_at, now)
            return (
              <div key={window.id} className="usage-limit" data-standing={standing}>
                <span className="usage-limit-name">{window.label}</span>
                {remaining !== null ? (
                  <ProgressBar value={remaining} size="sm" tone={standing === 'ok' ? undefined : standing} />
                ) : (
                  <span className="usage-limit-none" />
                )}
                <span className="usage-limit-left mono">{remaining !== null ? `${Math.round(remaining * 100)}% left` : statusWord(window.status)}</span>
                <span className="usage-limit-reset mono">
                  {[statusWord(window.status) && remaining !== null && standing !== 'ok' ? statusWord(window.status) : '', reset ? `resets in ${reset}` : ''].filter(Boolean).join(' · ')}
                </span>
                {window.overage && <span className="usage-flag">Using extra usage</span>}
              </div>
            )
          })}
          {agent.newest !== null && (
            <small className="usage-asof">
              {agent.agent} said so {ago(agent.newest, now)}, in a run Kriko started.
            </small>
          )}
        </div>
      ))}
      {id === 'cli_agent' && agents.length === 0 && <p className="usage-asof">This agent has not reported its limits yet. They appear after its next run.</p>}
      <Table id={id} resource={resource} />
      <Sources id={id} rows={resource.by_source} />
    </section>
  )
}

const number = (value: number | null) => (value === null ? null : value.toLocaleString('en-GB'))

function cells(id: ResourceId, sum: WindowSum) {
  const tokens = sum.tokens_in !== null && sum.tokens_out !== null ? `${formatTokens(sum.tokens_in)} in · ${formatTokens(sum.tokens_out)} out` : sum.tokens !== null ? `${formatTokens(sum.tokens)} tokens` : null
  return {
    calls: id === 'web_search' ? `${number(sum.calls)}${sum.misses ? ` · ${sum.misses} empty` : ''}` : number(sum.calls),
    tokens,
    usd: sum.usd !== null ? formatUsd(sum.usd) : null,
  }
}

/** The four rolling windows. A column no window has a number for is not drawn. */
function Table({ id, resource }: { id: ResourceId; resource: Resource }) {
  const names = Object.keys(resource.windows) as (keyof Resource['windows'])[]
  const rows = names.map((name) => ({ name, ...cells(id, resource.windows[name]) }))
  const showTokens = id !== 'web_search' && rows.some((row) => row.tokens)
  const showUsd = id === 'llm_api' && rows.some((row) => row.usd)
  return (
    <table className="usage-table">
      <thead>
        <tr>
          <th scope="col">Last</th>
          <th scope="col">{id === 'web_search' ? 'Searches' : 'Calls'}</th>
          {showTokens && <th scope="col">Tokens</th>}
          {showUsd && <th scope="col">Cost</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.name}>
            <th scope="row">{WINDOW_WORDS[row.name]}</th>
            <td className="mono">{row.calls}</td>
            {showTokens && <td className="mono">{row.tokens ?? '–'}</td>}
            {showUsd && <td className="mono">{row.usd ?? '–'}</td>}
          </tr>
        ))}
      </tbody>
    </table>
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

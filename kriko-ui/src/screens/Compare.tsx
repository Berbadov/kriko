import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from 'react'
import { useCompare, MAX_SLOTS, type Question } from '../compare'
import { selectCompareAgent } from '../compare/research'
import { groundingNote, findingsLabel, riskRows, specRows, type Check, type Level, type Risk, type RiskRow } from '../compare/checks'
import { deliveryText, expiryText, moneyText, pricedLine, procurementRead, warrantyText } from '../compare/figures'
import { AgentRecovery } from '../compare/Recovery'
import { useEngine, type Agent } from '../engine/Engine'
import { useHistory } from '../engine/history'
import { useSensitivity } from '../engine/sensitivity'
import { hiddenLine, shown } from '../engine/thinness'
import { findProduct, useProcurement, type ProcurementLine } from '../engine/procurement'
import { usePrefs } from '../prefs'
import { useQueue } from '../queue'
import { post, seg } from '../engine/api'
import { Composer } from '../ui/Composer'
import { ProductGlyph } from '../ui/ProductGlyph'
import { Decide } from '../ui/Decide'
import { ClaimSources } from '../ui/ClaimChip'
import { EvidenceMark } from '../ui/EvidenceMark'
import { AddToEstimate } from '../ui/AddToEstimate'
import { AgentSteps, Switch } from '../ui/controls'
import { CheckContext } from '../ui/CheckContext'
import { ExternalLink } from '../ui/ExternalLink'
import { Icon } from '../ui/Icon'
import { count } from '../ui/format'
import { Markdown } from '../ui/Markdown'
import { PixelGlyph } from '../ui/PixelGlyph'
import { RiskMark } from '../ui/RiskMark'

const LEVEL_WORD: Record<Level, string> = { critical: 'Serious', high: 'Serious', medium: 'Known issues', low: 'Minor', unrated: 'To check' }
const LEVEL_ORDER: Record<Level, number> = { critical: 0, high: 1, medium: 2, low: 3, unrated: 4 }
const NO_FINDINGS = 'The agents found no sourced problems. That is not proof there are none.'
const DEMO_CHOICES = [
  { id: 'demo:Gamma Unit 400', name: 'Gamma Unit 400', note: 'Demo' },
  { id: 'demo:Kingston A400 480 GB', name: 'Kingston A400 480 GB', note: 'Demo' },
]

/** Compare: the products the reader chose, side by side. Each product is a
 *  column of one table. Its rows are the findings the agents lined up, the
 *  severity word and its mark say how serious each one is, and a finding a
 *  product does not carry is said as such, never counted as none. In live
 *  mode the table closes on a Procurement block, read from the saved
 *  estimates: the same product's landed cost, risk, delivery and expiry, in
 *  the one currency its estimate states. */
export function CompareScreen() {
  const { items } = useQueue()
  const { mode } = useEngine()
  const { slots, checks, questions, add, remove, retry, ask, research, researchNew, stop, problem, saveAgain, pending, dismissPending } = useCompare()
  const procurement = useProcurement()
  const { sensitivity } = useSensitivity()
  const [only, setOnly] = useState(false)
  const [specsOpen, setSpecsOpen] = useState(false)
  const [reveal, setReveal] = useState<{ step: string; ids: string[] }>({ step: '', ids: [] })
  const searchRef = useRef<HTMLInputElement>(null)
  const live = mode === 'live'
  const revealed = reveal.step === sensitivity ? reveal.ids : []

  const working = items.filter((i) => i.state !== 'done')
  // The columns that have loaded, in the order they were added: their indexes line up with the rows.
  const { readyIds, ready } = useMemo(() => {
    const ids: string[] = []
    const found: Check[] = []
    for (const id of slots) {
      const loaded = checks[id]
      if (loaded?.status === 'ready') {
        ids.push(id)
        found.push(loaded.check)
      }
    }
    return { readyIds: ids, ready: found }
  }, [slots, checks])

  const risks = useMemo(() => riskRows(ready), [ready])
  const specs = useMemo(() => specRows(ready), [ready])
  // Most serious finding first; a row a product lacks sorts by the others.
  const rows = useMemo(() => {
    const kept = only ? risks.filter((r) => r.differs) : risks
    const worst = (row: RiskRow) => Math.min(...row.cells.map((c) => (c ? LEVEL_ORDER[c.level] : 9)))
    return [...kept].sort((a, b) => worst(a) - worst(b))
  }, [risks, only])
  const shownSpecs = only ? specs.filter((r) => r.differs) : specs
  const empty = slots.length === 0 && working.length === 0 && pending.length === 0
  // With no problems to read, the specifications are all there is: show them.
  const specsShown = specsOpen || (ready.length > 0 && risks.length === 0)

  const lines = useMemo(() => {
    const map = new Map<string, ProcurementLine[]>()
    for (const id of slots) {
      const loaded = checks[id]
      map.set(id, loaded?.status === 'ready' && loaded.check.subjectId ? findProduct(procurement.estimates, loaded.check.subjectId) : [])
    }
    return map
  }, [slots, checks, procurement.estimates])

  const toggleReveal = (id: string) => setReveal({ step: sensitivity, ids: revealed.includes(id) ? revealed.filter((one) => one !== id) : [...revealed, id] })

  const nameOf = (id: string) => {
    const loaded = checks[id]
    if (loaded?.status === 'ready') return loaded.check.name
    return loaded?.status === 'error' ? 'Not read' : 'Reading the check'
  }

  /** A column still being read, or one that failed, has no findings yet to show. */
  const unreadCell = (id: string): ReactNode => (checks[id]?.status === 'error' ? <span className="cmp-muted">Not read</span> : <span className="skeleton" aria-hidden="true" />)

  const cellOf = (id: string, row: RiskRow): ReactNode => {
    const loaded = checks[id]
    if (loaded?.status !== 'ready') return unreadCell(id)
    const risk = row.cells[readyIds.indexOf(id)]
    if (!risk) return <span className="cmp-muted">Not found here</span>
    if (!revealed.includes(id) && !shown(risk.evidence?.level, sensitivity)) return <span className="cmp-muted">Hidden at this sensitivity</span>
    return <Finding risk={risk} />
  }

  /** The one cell for a product when no finding is sourced at all: what the engine said, or the plain sentence. */
  const noneCell = (id: string): ReactNode => {
    const loaded = checks[id]
    if (loaded?.status !== 'ready') return unreadCell(id)
    return <span className="cmp-muted">{groundingNote(loaded.check) || NO_FINDINGS}</span>
  }

  const headOf = (id: string): ReactNode => {
    const loaded = checks[id]
    if (loaded?.status === 'ready') {
      const check = loaded.check
      const hidden = check.risks.filter((r) => !shown(r.evidence?.level, sensitivity))
      const open = revealed.includes(id)
      return (
        <ColumnHead check={check} onResearch={(agent, onJob) => research(id, agent, onJob)}>
          {hidden.length > 0 && (
            <p className="cmp-hidden" role="status">
              <span>{open ? 'Showing the hidden findings.' : `${hiddenLine(hidden.length, sensitivity)}.`}</span>
              <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => toggleReveal(id)} aria-pressed={open}>
                {open ? 'Hide them again' : 'Show them'}
              </button>
            </p>
          )}
        </ColumnHead>
      )
    }
    if (loaded?.status === 'error') {
      return (
        <div className="cmp-colhead">
          <strong>Not read</strong>
          <span className="muted">{loaded.message}</span>
          <div className="cmp-actions">
            <button type="button" className="k-btn" data-size="sm" onClick={() => retry(id)}>Try again</button>
            <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => remove(id)}>Remove</button>
          </div>
        </div>
      )
    }
    return (
      <div className="cmp-colhead">
        <span className="cmp-working"><PixelGlyph size={13} active />Reads the check</span>
      </div>
    )
  }

  // Procurement, per column: the estimate lines this product sits on, and the one that shows.
  const procure = (id: string) => {
    const found = lines.get(id) ?? []
    const loaded = checks[id]
    const check = loaded?.status === 'ready' ? loaded.check : null
    return { check, found, chosen: pricedLine(found) ?? found[0] ?? null }
  }
  const readable = live && ready.length > 0
    ? procurementRead(slots.flatMap((id) => {
      const { check, found } = procure(id)
      return check ? [{ name: check.name, lines: found }] : []
    }))
    : ''

  return (
    <section className="k-screen cmp" data-width="wide">
      <header className="k-head">
        <h1 className="k-title">Compare</h1>
        <div className="k-head-actions">
          <label className="inline-switch">
            <span>Differences only</span>
            <Switch on={only} onChange={setOnly} label="Differences only" />
          </label>
        </div>
      </header>

      {problem && (
        <div className="k-notice" data-tone="risk" role="alert">
          <span>{problem}</span>
          <button type="button" className="k-btn" data-size="sm" onClick={saveAgain}>{problem.startsWith('Could not load') ? 'Retry loading' : 'Retry saving'}</button>
        </div>
      )}

      <section className="k-group" aria-labelledby="cmp-products">
        <h2 className="k-caption" id="cmp-products">Products</h2>
        <div className="k-card cmp-products" data-pad>
          <div className="cmp-chips">
            {slots.map((id) => (
              <span key={id} className="k-chip cmp-chip">
                <span>{nameOf(id)}</span>
                <button type="button" className="cmp-chip-remove" aria-label={`Remove ${nameOf(id)}`} onClick={() => remove(id)}>Remove</button>
              </span>
            ))}
            {slots.length === 0 && <span className="cmp-muted">None yet. Search your saved checks, or name a product.</span>}
          </div>
          <ProductSearch slots={slots} add={add} researchNew={researchNew} inputRef={searchRef} />
        </div>
      </section>

      {(pending.length > 0 || working.length > 0) && (
        <section className="k-group">
          <h2 className="k-caption">Being read</h2>
          <ul className="k-card k-list cmp-pending" aria-label="Products being researched for this comparison">
            {pending.map((one) => (
              <li key={one.id} className="cmp-pending-row" data-state={one.state}>
                {one.state === 'running' ? <PixelGlyph size={16} active /> : <Icon name="alert" size={15} />}
                <span className="cmp-pending-main">
                  <strong>{one.name}</strong>
                  <span className="muted">{one.note}</span>
                </span>
                {one.state === 'failed' && (
                  <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => dismissPending(one.id)} aria-label={`Dismiss ${one.name}`}>Dismiss</button>
                )}
              </li>
            ))}
            {working.slice(0, 3).map((item) => (
              <li key={item.id} className="cmp-pending-row" data-state={item.state}>
                <PixelGlyph size={16} active={item.state === 'researching'} />
                <span className="cmp-pending-main">
                  <strong>{item.name}</strong>
                  <span className="muted">{item.line}</span>
                </span>
                <AgentSteps value={item.progress} state={item.state} labels={false} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {empty ? (
        <div className="k-empty">
          <PixelGlyph size={34} active />
          <strong>Add two checks to compare them.</strong>
          <button type="button" className="k-btn" data-kind="primary" onClick={() => searchRef.current?.focus()}>
            <Icon name="plus" size={14} /> Add a product
          </button>
        </div>
      ) : (
        slots.length > 0 && (
          <>
            <Decide lookupIds={ready.map((one) => one.lookupId)} />

            <section className="k-group">
              <h2 className="k-caption">Findings</h2>
              <div className="k-card cmp-scroll">
                <table className="k-table cmp-table" aria-label="Products side by side">
                  <thead>
                    <tr>
                      <th scope="col" className="cmp-first">Finding</th>
                      {slots.map((id) => <th scope="col" key={id} className="cmp-col">{headOf(id)}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.key ?? row.title}>
                        <th scope="row" className="cmp-first">
                          <span className="cmp-row-title">{row.title}</span>
                          <span className="muted cmp-row-note">
                            In {row.cells.filter(Boolean).length} of {ready.length} {ready.length === 1 ? 'product' : 'products'}
                          </span>
                        </th>
                        {slots.map((id) => <td key={id}>{cellOf(id, row)}</td>)}
                      </tr>
                    ))}
                    {risks.length === 0 && ready.length > 0 && (
                      <tr>
                        <th scope="row" className="cmp-first">None sourced</th>
                        {slots.map((id) => <td key={id}>{noneCell(id)}</td>)}
                      </tr>
                    )}
                    {risks.length > 0 && rows.length === 0 && (
                      <tr>
                        <td colSpan={slots.length + 1} className="cmp-muted">Nothing here differs from the others.</td>
                      </tr>
                    )}
                  </tbody>

                  {live && (
                    <tbody className="cmp-procure">
                      <tr>
                        <th scope="rowgroup" colSpan={slots.length + 1} className="cmp-group">Procurement</th>
                      </tr>
                      <tr>
                        <th scope="row" className="cmp-first">In an estimate</th>
                        {slots.map((id) => {
                          const { check, found } = procure(id)
                          const estimates = [...new Set(found.map((line) => line.estimateName || 'Untitled estimate'))]
                          return (
                            <td key={id}>
                              {!check ? <span className="cmp-muted">–</span> : estimates.length > 0 ? estimates.join(', ') : (
                                <span className="cmp-stack">
                                  <span>Not yet</span>
                                  {check.subjectId && check.packId
                                    ? <AddToEstimate subject={{ subject_id: check.subjectId, pack_id: check.packId, label: check.name }} compact />
                                    : <span className="cmp-muted">Not linked to a catalog product</span>}
                                </span>
                              )}
                            </td>
                          )
                        })}
                      </tr>
                      <tr>
                        <th scope="row" className="cmp-first">Best landed cost</th>
                        {slots.map((id) => {
                          const { check, found } = procure(id)
                          const priced = pricedLine(found)
                          return (
                            <td key={id} className="cmp-figure">
                              {!check ? <span className="cmp-muted">–</span> : priced ? `${moneyText(priced.bestLanded, priced.currency)} per unit` : <span className="cmp-muted">No comparable price yet</span>}
                            </td>
                          )
                        })}
                      </tr>
                      <tr>
                        <th scope="row" className="cmp-first">Quote risk</th>
                        {slots.map((id) => {
                          const { check, chosen } = procure(id)
                          return (
                            <td key={id}>
                              {!check ? <span className="cmp-muted">–</span> : chosen && chosen.quotes > 0 ? <RiskMark level={chosen.risk} /> : <span className="cmp-muted">No quote yet</span>}
                            </td>
                          )
                        })}
                      </tr>
                      <tr>
                        <th scope="row" className="cmp-first">Delivery</th>
                        {slots.map((id) => {
                          const { check, chosen } = procure(id)
                          return <td key={id}>{!check ? <span className="cmp-muted">–</span> : chosen?.best ? deliveryText(chosen.best.delivery_days) : <span className="cmp-muted">No comparable quote</span>}</td>
                        })}
                      </tr>
                      <tr>
                        <th scope="row" className="cmp-first">Warranty</th>
                        {slots.map((id) => {
                          const { check, chosen } = procure(id)
                          return <td key={id}>{!check ? <span className="cmp-muted">–</span> : chosen?.best ? warrantyText(chosen.best.warranty_months) : <span className="cmp-muted">No comparable quote</span>}</td>
                        })}
                      </tr>
                      <tr>
                        <th scope="row" className="cmp-first">Expires</th>
                        {slots.map((id) => {
                          const { check, chosen } = procure(id)
                          return <td key={id}>{!check ? <span className="cmp-muted">–</span> : chosen?.best ? expiryText(chosen.expiresInDays) : <span className="cmp-muted">No comparable quote</span>}</td>
                        })}
                      </tr>
                    </tbody>
                  )}
                </table>
              </div>
              {live && procurement.problem && <p className="k-notice" role="alert">{procurement.problem}</p>}
              {readable && <p className="cmp-read" role="status">{readable}</p>}
            </section>

            {ready.length > 0 && specs.length > 0 && (
              <section className="k-group">
                <div className="cmp-specs-head">
                  <h2 className="k-caption">Specifications <span className="mono">{shownSpecs.length}</span></h2>
                  {risks.length > 0 && (
                    <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => setSpecsOpen((v) => !v)} aria-expanded={specsShown}>
                      {specsShown ? 'Hide specifications' : 'Show specifications'}
                    </button>
                  )}
                </div>
                {specsShown && (
                  <div className="k-card cmp-scroll">
                    <table className="k-table cmp-table" aria-label="Specifications">
                      <thead>
                        <tr>
                          <th scope="col" className="cmp-first">Specification</th>
                          {ready.map((c) => <th scope="col" key={c.lookupId} className="cmp-col" title={c.name}>{c.name}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {shownSpecs.map((row) => (
                          <tr key={row.label} data-differs={row.differs}>
                            <th scope="row" className="cmp-first">{row.label}</th>
                            {row.cells.map((cell, i) => (
                              <td key={ready[i].lookupId}>
                                <span className="cmp-spec-value">{cell?.value ?? 'Unknown'}</span>
                                {cell?.source && <ExternalLink href={cell.source}> Source</ExternalLink>}
                                {cell?.quote && <details><summary>Quote</summary><q>{cell.quote}</q></details>}
                              </td>
                            ))}
                          </tr>
                        ))}
                        {shownSpecs.length === 0 && (
                          <tr>
                            <td colSpan={ready.length + 1} className="cmp-muted">The specifications do not differ.</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}
          </>
        )
      )}

      <Talk questions={questions} />

      <div className="cmp-dock">
        <Composer onSubmit={(text, agent) => ask(text, agent)} running={questions.some((q) => q.state === 'running')} onStop={stop} placeholder={slots.length ? 'Ask about these products' : 'Add a check to ask about it'} />
      </div>
    </section>
  )
}

/** A product's column head: its picture and name, what the agents kept, and the research it can have. */
function ColumnHead({ check, onResearch, children }: { check: Check; onResearch: (agent: Agent, onJob: (jobId: string) => void) => Promise<void>; children?: ReactNode }) {
  const { mode, agents, agentAvailable, preferred, chooseAgent } = useEngine()
  const [research, setResearch] = useState<{ busy: boolean; error: string }>({ busy: false, error: '' })
  const [jobId, setJobId] = useState('')
  const [canceling, setCanceling] = useState(false)
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])
  const selectedAgent = selectCompareAgent(agents, preferred, agentAvailable)
  const researchWith = async (agent: Agent) => {
    if (research.busy || mode !== 'live') return
    // A press here is also the reader's answer to "which agent should this
    // machine use". Storing it is what recovers the other columns and the
    // composer, which were dead-ended by the same stored pick; the engine
    // keeps it, so the next product starts on it too.
    chooseAgent(agent.id)
    setResearch({ busy: true, error: '' })
    setJobId('')
    setCanceling(false)
    try {
      await onResearch(agent, setJobId)
      if (mounted.current) setResearch({ busy: false, error: '' })
    } catch (error) {
      // Whatever the engine refused with, a missing key, a trial used up, an
      // agent not installed, is the whole message, so it is shown unwrapped.
      if (mounted.current) setResearch({ busy: false, error: error instanceof Error ? error.message : 'Could not research this product.' })
    }
  }
  const cancel = async () => {
    if (!jobId || canceling) return
    setCanceling(true)
    try {
      await post(`/api/jobs/${seg(jobId)}/cancel`, {})
    } catch (error) {
      if (mounted.current) {
        setCanceling(false)
        setResearch({ busy: true, error: error instanceof Error ? error.message : 'Could not stop this research.' })
      }
    }
  }
  return (
    <div className="cmp-colhead">
      <div className="cmp-title">
        <ProductGlyph name={check.name} size={22} />
        <strong title={check.name}>{check.name}</strong>
      </div>
      <span className="muted">{check.category || 'Quick look'}</span>
      <span className="cmp-count">{findingsLabel(check)}</span>
      {mode === 'live' && (selectedAgent ? (
        <div className="cmp-actions">
          <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => void researchWith(selectedAgent)} disabled={research.busy} title={`Research with ${selectedAgent.label}`}>
            {research.busy ? <><PixelGlyph size={13} active /> {canceling ? 'Stopping' : `Researching with ${selectedAgent.label}`}</> : `Research with ${selectedAgent.label}`}
          </button>
          {research.busy && jobId && <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={() => void cancel()} disabled={canceling}>{canceling ? 'Stopping…' : 'Stop'}</button>}
        </div>
      ) : <AgentRecovery agents={agents} preferred={preferred} available={agentAvailable} busy={research.busy} onResearch={(agent) => void researchWith(agent)} />)}
      {research.error && <p className="k-notice" data-tone="risk" role="alert">{research.error}</p>}
      <CheckContext check={check} />
      {children}
    </div>
  )
}

/** One finding in a product's cell: its severity word and mark, the body, and its sources behind a button. */
function Finding({ risk }: { risk: Risk }) {
  const [open, setOpen] = useState(false)
  const pages = risk.sources.length
  const detail = pages > 0 || Boolean(risk.applicability || risk.advice)
  return (
    <div className="cmp-finding" data-open={open} data-thin={risk.evidence?.level === 'thin' || undefined}>
      <div className="cmp-finding-top">
        <span className="level" data-level={risk.level}>{LEVEL_WORD[risk.level]}</span>
        <EvidenceMark evidence={risk.evidence} />
      </div>
      {risk.disputed && <span className="cmp-flag">Its sources disagree</span>}
      {risk.body && <p className="cmp-finding-body">{risk.body}</p>}
      {open && (
        <>
          {risk.applicability && <p className="cmp-finding-more">Applies: {risk.applicability}</p>}
          {risk.advice && <p className="cmp-finding-more">{risk.advice}</p>}
          {pages > 0 && <ClaimSources sources={risk.sources} />}
        </>
      )}
      {detail && (
        <button type="button" className="k-btn" data-kind="quiet" data-size="sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? 'Hide details' : pages > 0 ? `Show ${count(pages, 'source')}` : 'Show details'}
        </button>
      )}
    </div>
  )
}

/** The search that adds a product: saved checks, or a name to research. The list opens while the field has focus. */
function ProductSearch({ slots, add, researchNew, inputRef }: { slots: string[]; add: (id: string) => boolean; researchNew: (name: string, agent: Agent) => Promise<void>; inputRef: RefObject<HTMLInputElement | null> }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const close = () => setOpen(false)
  return (
    <div className="cmp-search">
      <label className="k-field">
        <span className="k-field-label">Add a product</span>
        <input
          ref={inputRef}
          type="search"
          className="k-input"
          placeholder="Search your checks, or name any product"
          value={query}
          onChange={(event) => { setQuery(event.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => { if (event.key === 'Escape') close() }}
        />
      </label>
      {open && <SearchResults query={query} slots={slots} add={add} researchNew={researchNew} onDone={close} onPicked={() => { setQuery(''); close() }} />}
    </div>
  )
}

/** The saved checks that match the query, and the research a new name can start. Mounted only while open. */
function SearchResults({ query, slots, add, researchNew, onDone, onPicked }: { query: string; slots: string[]; add: (id: string) => boolean; researchNew: (name: string, agent: Agent) => Promise<void>; onDone: () => void; onPicked: () => void }) {
  const engine = useEngine()
  const history = useHistory(query)
  const demo = engine.mode !== 'live' && engine.mode !== 'checking'
  const choices = (demo ? DEMO_CHOICES : (history.items ?? []).map((r) => ({ id: r.id, name: r.name, note: r.category }))).filter((r) => !slots.includes(r.id))
  const full = slots.length >= MAX_SLOTS
  const waiting = !demo && history.items === null
  return (
    <div className="cmp-results">
      <div className="cmp-results-head">
        <span className="k-caption">Saved checks</span>
        <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={onDone} aria-label="Close the list">Close</button>
      </div>
      {history.problem && <p className="k-notice" data-tone="risk" role="alert">{history.problem}</p>}
      {waiting && <p className="cmp-muted">Reads your checks…</p>}
      {!waiting && choices.length === 0 && !query.trim() && <p className="cmp-muted">No checks yet. Name a product to research it.</p>}
      <div className="k-list cmp-results-list">
        {query.trim().length >= 3 && (
          <button
            type="button"
            className="k-row"
            disabled={full || engine.mode !== 'live'}
            title="Kriko searches the web for it now and adds it as a column when the research is done"
            onClick={() => {
              const agent = engine.agents.find((a) => a.id === engine.preferred) ?? engine.agents[0]
              void researchNew(query.trim(), agent)
              onPicked()
            }}
          >
            <span className="k-row-main">
              <span className="k-row-title"><Icon name="search" size={13} /> Research “{query.trim()}” and add</span>
              <span className="k-row-note">Not checked yet. Kriko searches the web for it now.</span>
            </span>
          </button>
        )}
        {choices.map((r) => (
          <button key={r.id} type="button" className="k-row" onClick={() => { if (add(r.id)) onPicked() }} disabled={full} title={r.name}>
            <span className="k-row-main">
              <span className="k-row-title">{r.name}</span>
              <span className="k-row-note">{r.note}</span>
            </span>
          </button>
        ))}
      </div>
      {history.hasMore && <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={history.loadMore}>Load more</button>}
    </div>
  )
}

/** The questions and the answers, above the composer. */
function Talk({ questions }: { questions: Question[] }) {
  const { motion: m } = usePrefs()
  const end = useRef<HTMLDivElement>(null)
  const size = questions.reduce((n, q) => n + q.answer.length, questions.length)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: m.on ? 'smooth' : 'auto' })
  }, [size, m.on])
  if (!questions.length) return null
  return (
    <div className="talk cmp-talk">
      {questions.map((q) => (
        <div key={q.id} className="talk-q">
          <p className="you">{q.text}</p>
          {q.state === 'running' && !q.answer && (
            <span className="work-line">
              <PixelGlyph size={13} active />
              {q.agent ? `${q.agent} researches` : 'Researches'}
            </span>
          )}
          {q.answer && (
            <article className="answer">
              <Markdown text={q.answer} live={q.state === 'running'} />
            </article>
          )}
          {q.state === 'failed' && (
            <p className="error-note" role="alert">
              {q.note}
            </p>
          )}
        </div>
      ))}
      <div ref={end} />
    </div>
  )
}

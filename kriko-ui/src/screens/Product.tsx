import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { demoCheck, loadCheck, type Check, type Level } from '../compare/checks'
import { useCompare } from '../compare'
import { useEngine } from '../engine/Engine'
import { EngineError, get, post, seg, type ApiJob } from '../engine/api'
import { followJob } from '../engine/jobs'
import { findProduct, useProcurement, type ProcurementLine } from '../engine/procurement'
import { useSensitivity } from '../engine/sensitivity'
import { hiddenLine, shown } from '../engine/thinness'
import { usePrefs } from '../prefs'
import { AddToEstimate } from '../ui/AddToEstimate'
import { Composer } from '../ui/Composer'
import { EvidenceMark } from '../ui/EvidenceMark'
import { ExternalLink } from '../ui/ExternalLink'
import { Markdown } from '../ui/Markdown'
import { PixelGlyph } from '../ui/PixelGlyph'
import { ReportButton } from '../ui/ReportButton'
import { RiskMark } from '../ui/RiskMark'
import { CheckContext, RiskEvidence } from '../ui/CheckContext'
import { ProductInsights, type ProductTarget } from '../ui/ProductInsights'
import { DustField } from '../dust/DustField'
import { kindFor, product, reading } from '../dust/engine'

/** The findings' severity, said as a shape and a word. */
type Severity = 'serious' | 'known' | 'minor' | 'check'
const SEVERITY: Record<Level, Severity> = { critical: 'serious', high: 'serious', medium: 'known', low: 'minor', unrated: 'check' }
const GROUPS: { key: Severity; caption: string }[] = [
  { key: 'serious', caption: 'Serious' },
  { key: 'known', caption: 'Known issues' },
  { key: 'minor', caption: 'Minor' },
  { key: 'check', caption: 'To check' },
]
const SEVERITY_WORD: Record<Severity, string> = { serious: 'Serious', known: 'Known issues', minor: 'Minor', check: 'To check' }
const DEMO_ANSWER = 'The maker states a limit of **40 minutes** of full load.\n\n- Short jobs are fine.\n- For long jobs, add a fan or pick another unit.'
/** A quote that expires within this many days is said to expire soon. */
const SOON_DAYS = 14

interface Turn {
  id: string
  text: string
  answer: string
  state: 'running' | 'done' | 'failed'
  note: string
}

type Asked = ApiJob & { params?: { question?: string } }

const reasonOf = (error: unknown) => (error instanceof EngineError ? error.message : 'The engine does not answer.')
const answerOf = (job: ApiJob) => (job.result as { answer?: string } | null | undefined)?.answer ?? ''
/** How a lost research reads when the engine sends no words of its own. */
const STOPPED: Record<string, string> = {
  cancelled: 'The research was stopped.',
  interrupted: 'The research was interrupted. Ask again to continue.',
  failed: 'The research failed.',
}

const money = (amount: number, currency: string) => {
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount)
  } catch {
    return `${amount.toFixed(2)} ${currency}`
  }
}

/** The quote's validity in words, from the engine's own day count. Empty when the quote has no date. */
function validity(line: ProcurementLine): { text: string; tone: 'risk' | 'warn' | '' } {
  const until = line.best?.valid_until ?? ''
  const days = line.expiresInDays
  if (!until || days == null) return { text: '', tone: '' }
  if (days < 0) return { text: 'Expired', tone: 'risk' }
  if (days === 0) return { text: 'Expires today', tone: 'warn' }
  if (days <= SOON_DAYS) return { text: `Expires in ${days} ${days === 1 ? 'day' : 'days'}`, tone: 'warn' }
  return { text: `Valid until ${until}`, tone: '' }
}

const openEstimate = () => window.dispatchEvent(new CustomEvent('kriko:navigate', { detail: { screen: 'estimate' } }))

/** One estimate line that holds this product: the best quote, its risk and its terms. */
function ProcurementCard({ line }: { line: ProcurementLine }) {
  const best = line.best
  const vendor = best ? best.vendor || best.seller || 'Unnamed vendor' : ''
  const due = validity(line)
  return (
    <article className="k-card product-quote" data-pad>
      <div className="product-quote-head">
        <strong className="product-quote-estimate">{line.estimateName || 'Untitled estimate'}</strong>
        <span className="product-quote-note">
          {line.quotes} {line.quotes === 1 ? 'quote' : 'quotes'} · quantity {line.quantity}
        </span>
      </div>
      <div className="product-quote-price">
        <span className="product-landed">{line.bestLanded != null ? money(line.bestLanded, line.currency) : 'No comparable price yet'}</span>
        {best && <span className="product-quote-note">per unit, landed, from {vendor}</span>}
      </div>
      {line.saving != null && <p className="product-quote-note">Saves {money(line.saving, line.currency)} against the next quote.</p>}
      <div className="product-quote-facts">
        <RiskMark level={line.risk} />
        {best?.delivery_days != null && <span>Delivery {best.delivery_days} days</span>}
        {best?.warranty_months != null && <span>Warranty {best.warranty_months} months</span>}
        {due.text && <span className="k-pill" data-tone={due.tone || undefined}>{due.text}</span>}
      </div>
      {line.reasons.length > 0 && (
        <ul className="product-quote-reasons">
          {line.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      <div>
        <button className="k-btn" data-size="sm" onClick={openEstimate}>Open the estimate</button>
      </div>
    </article>
  )
}

/** The product's place in procurement: its estimates' best quotes, or the one way to put it in an estimate. */
function ProcurementSection({ name, target, lines, seriousCount, loading, problem }: {
  name: string
  target: ProductTarget | null | undefined
  lines: ProcurementLine[]
  seriousCount: number
  loading: boolean
  problem: string
}) {
  const estimateNames = [...new Set(lines.map((line) => line.estimateName || 'Untitled estimate'))]
  const where = estimateNames.length === 1 ? estimateNames[0] : `${estimateNames.length} estimates`
  const ready = target !== undefined && !loading
  return (
    <section className="k-group product-procure" aria-label="Procurement">
      <p className="k-caption">Procurement</p>
      {problem && <p className="k-notice" role="alert">{problem}</p>}
      {target === undefined && !problem && <p className="product-quiet" role="status">Reading the product…</p>}
      {loading && lines.length === 0 && <p className="product-quiet" role="status">Reading your estimates…</p>}
      {lines.map((line, index) => (
        <ProcurementCard key={`${line.estimateId}-${line.lineId ?? index}`} line={line} />
      ))}
      {ready && lines.length === 0 && (
        <div className="k-empty">
          <strong>Not in an estimate yet</strong>
          {target ? (
            <>
              <p>Add it to an estimate to see its best landed price, its quote risk and when the quote expires.</p>
              <AddToEstimate subject={{ subject_id: target.subject_id, pack_id: target.pack_id, label: name }} />
            </>
          ) : (
            <p>This product is not linked to a catalog entry, so it cannot be priced in an estimate yet.</p>
          )}
        </div>
      )}
      {lines.length > 0 && seriousCount > 0 && (
        <p className="k-notice" data-tone="warn" role="status">
          This product has {seriousCount} serious {seriousCount === 1 ? 'finding' : 'findings'} and is in {where}. Review them before you buy.
        </p>
      )}
    </section>
  )
}

/** One saved check, and the questions about it. The extension hands a product
 *  over to this page. The questions go to the engine, which answers them with a
 *  web search and names the pages it read. */
export function ProductScreen({ lookupId, onBack, onCompare }: { lookupId: string; onBack: () => void; onCompare: () => void }) {
  const { motion: m } = usePrefs()
  const { mode } = useEngine()
  const { add, slots } = useCompare()
  const [check, setCheck] = useState<Check | null>(null)
  const [problem, setProblem] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [turns, setTurns] = useState<Turn[]>([])
  /** The catalog subject this product is in: undefined while it is read, null when it has none. */
  const [target, setTarget] = useState<ProductTarget | null | undefined>(undefined)
  const { sensitivity } = useSensitivity()
  /** The reader pressed "show them", for this check at this step. A different check or step is a new question. */
  const [reveal, setReveal] = useState({ key: '', on: false })
  const revealKey = `${lookupId}|${sensitivity}`
  const revealed = reveal.on && reveal.key === revealKey
  const alive = useRef(true)
  const end = useRef<HTMLDivElement>(null)
  const stopRequested = useRef(false)
  const procurement = useProcurement()

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const patch = useCallback((id: string, change: Partial<Turn>) => {
    if (alive.current) setTurns((list) => list.map((t) => (t.id === id ? { ...t, ...change } : t)))
  }, [])

  const settle = useCallback(
    (id: string, job: ApiJob) => {
      if (job.state === 'succeeded') patch(id, { answer: answerOf(job) || 'No answer came back.', state: 'done' })
      else patch(id, { answer: answerOf(job), state: 'failed', note: job.message || STOPPED[job.state] || 'The research did not finish.' })
    },
    [patch],
  )

  // The check, and the questions asked before.
  useEffect(() => {
    let live = true
    setCheck(null)
    setProblem('')
    setTurns([])
    setTarget(undefined)
    if (lookupId.startsWith('demo:')) {
      setCheck(demoCheck(lookupId, lookupId.slice(5)))
      return
    }
    loadCheck(lookupId)
      .then((c) => live && setCheck(c))
      .catch((e) => live && setProblem(reasonOf(e)))
    get<{ items: Asked[] }>(`/api/lookup/${seg(lookupId)}/questions`)
      .then((reply) => {
        if (!live) return
        setTurns(
          reply.items.map((j) => ({
            id: j.job_id,
            text: j.params?.question ?? '',
            answer: answerOf(j),
            state: j.state === 'succeeded' ? 'done' : j.done ? 'failed' : 'running',
            note: j.done && j.state !== 'succeeded' ? j.message || '' : '',
          })),
        )
        for (const j of reply.items) {
          if (j.done) continue
          followJob(j.job_id, (reading) => patch(j.job_id, { answer: answerOf(reading), note: reading.message || 'Working' }), () => live)
            .then((ended) => ended && settle(j.job_id, ended))
            .catch((e) => patch(j.job_id, { state: 'failed', note: reasonOf(e) }))
        }
      })
      .catch((error: unknown) => live && setProblem(`Could not read saved questions. ${reasonOf(error)}`))
    return () => {
      live = false
    }
  }, [lookupId, settle, patch, loadAttempt])

  const lastSize = turns.length ? turns[turns.length - 1].answer.length : 0
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: m.on ? 'smooth' : 'auto' })
  }, [turns.length, lastSize, m.on])

  const ask = async (text: string) => {
    stopRequested.current = false
    const id = `local-${Date.now()}`
    let activeId = id
    setTurns((list) => [...list, { id, text, answer: '', state: 'running', note: '' }])
    if (mode !== 'live') {
      await new Promise((resolve) => window.setTimeout(resolve, 1200))
      patch(id, { answer: DEMO_ANSWER, state: 'done' })
      return
    }
    try {
      const sent = await post<{ job_id: string }>(`/api/lookup/${seg(lookupId)}/questions`, { question: text })
      activeId = sent.job_id
      if (stopRequested.current) await post(`/api/jobs/${seg(sent.job_id)}/cancel`, {})
      setTurns((list) => list.map((t) => (t.id === id ? { ...t, id: sent.job_id } : t)))
      const ended = await followJob(sent.job_id, (reading) => patch(sent.job_id, { answer: answerOf(reading), note: reading.message || 'Working' }), () => alive.current)
      if (ended) settle(sent.job_id, ended)
    } catch (error) {
      patch(activeId, { state: 'failed', note: reasonOf(error) })
    }
  }

  const hidden = check ? check.risks.filter((risk) => !shown(risk.evidence?.level, sensitivity)) : []
  const drawn = check ? check.risks.filter((risk) => revealed || shown(risk.evidence?.level, sensitivity)) : []
  const seriousCount = check ? check.risks.filter((risk) => SEVERITY[risk.level] === 'serious').length : 0

  // The product rebuilt in dust: the cloud reads while the check loads, then
  // gathers into the outline of whatever kind of thing the check is about.
  const portrait = useMemo(() => (check ? product(kindFor(check.name, check.category)) : reading), [check])

  const onBoard = slots.includes(lookupId)
  const asking = turns.some((t) => t.state === 'running')
  const live = mode === 'live' && !lookupId.startsWith('demo:')
  const lines = useMemo(() => (target ? findProduct(procurement.estimates, target.subject_id) : []), [procurement.estimates, target])
  const stop = () => {
    stopRequested.current = true
    for (const turn of turns.filter((t) => t.state === 'running')) {
      if (mode === 'live' && !turn.id.startsWith('local-')) void post(`/api/jobs/${seg(turn.id)}/cancel`, {}).then(() => patch(turn.id, { note: 'Stopping…' })).catch((error) => patch(turn.id, { note: reasonOf(error) }))
    }
  }

  const savedOn = check?.checkedAt ? new Date(check.checkedAt) : null
  const savedText = savedOn && !Number.isNaN(savedOn.getTime()) ? savedOn.toLocaleDateString() : ''

  return (
    <div className="k-screen product-page" data-width="wide">
      <header className="product-head rise" style={{ '--i': 0 } as CSSProperties}>
        <div className="product-head-main">
          <button className="k-btn" data-kind="quiet" data-size="sm" onClick={onBack} aria-label="Back to Chat">
            Back
          </button>
          <h1 className="product-title" title={check?.name}>{check?.name ?? 'Check'}</h1>
          {check && (
            <div className="product-facts">
              {check.category && <span className="k-pill">{check.category}</span>}
              {savedText && <span className="k-pill">Saved {savedText}</span>}
              {check.risks.length === 0 ? (
                <span className="k-pill" data-tone="ok">No reports</span>
              ) : seriousCount > 0 ? (
                <span className="k-pill" data-tone="risk">{seriousCount} serious</span>
              ) : (
                <span className="k-pill">{check.risks.length} {check.risks.length === 1 ? 'finding' : 'findings'}</span>
              )}
            </div>
          )}
        </div>
        <div className="k-head-actions">
          {check && (
            <button className="k-btn" disabled={turns.some((turn) => turn.state === 'running')} onClick={() => void ask('Research this exact product again for current evidence, prices and availability. Keep the recorded variant and market assumptions explicit and cite the sources.')}>
              Ask for fresh evidence
            </button>
          )}
          {onBoard ? (
            <button className="k-btn" onClick={onCompare}>
              Compare
            </button>
          ) : (
            <button className="k-btn" onClick={() => add(lookupId)} disabled={!check}>
              Add to compare
            </button>
          )}
          {check && target && <AddToEstimate subject={{ subject_id: target.subject_id, pack_id: target.pack_id, label: check.name }} />}
        </div>
      </header>

      <div className="product-columns">
        <div className="product-main">
          {!problem && (
            <div className="product-dust rise" style={{ '--i': 0 } as CSSProperties}>
              <DustField scene={portrait} reading={!check} per={12} cap={9000} />
            </div>
          )}
          {problem && (
            <p className="error-note" role="alert">
              {problem}
              <button className="k-btn" data-size="sm" onClick={() => setLoadAttempt((n) => n + 1)}>Read again</button>
              <ReportButton note={problem} />
            </p>
          )}
          {!check && !problem && (
            <span className="work-line">
              <PixelGlyph size={13} active />
              Reads the check
            </span>
          )}
          {check && <CheckContext check={check} />}

          {check && (
            <section className="product-findings" aria-label="Findings">
              {check.risks.length === 0 && (
                <div className="product-none">
                  <span className="product-sev" data-level="none">No reports</span>
                  <span className="product-quiet">Nothing on record for this product.</span>
                </div>
              )}
              {check.risks.length > 0 && drawn.length === 0 && <p className="product-quiet">Every finding on record is hidden at this sensitivity.</p>}
              {GROUPS.map((group) => {
                const rows = drawn.filter((risk) => SEVERITY[risk.level] === group.key)
                if (rows.length === 0) return null
                return (
                  <section className="product-group" key={group.key} aria-label={group.caption}>
                    <h2 className="product-caption">{group.caption}</h2>
                    <ul className="product-finding-list rise" style={{ '--i': 1 } as CSSProperties}>
                      {rows.map((risk) => (
                        <li key={risk.title} className="product-finding" data-thin={risk.evidence?.level === 'thin' || undefined}>
                          <div className="product-gutter">
                            <span className="product-sev" data-level={group.key}>{SEVERITY_WORD[group.key]}</span>
                            {risk.sources.length > 0 && (
                              <span className="product-count">
                                {risk.sources.length} {risk.sources.length === 1 ? 'source' : 'sources'}
                              </span>
                            )}
                          </div>
                          <div className="product-finding-body">
                            <div className="risk-title product-finding-title">
                              <strong>{risk.title}</strong>
                              <EvidenceMark evidence={risk.evidence} />
                            </div>
                            {risk.body && <p>{risk.body}</p>}
                            <RiskEvidence risk={risk} />
                          </div>
                        </li>
                      ))}
                    </ul>
                  </section>
                )
              })}
            </section>
          )}
          {check && hidden.length > 0 && (
            <p className="product-hidden" role="status">
              <span>{revealed ? 'Showing the hidden findings.' : `${hiddenLine(hidden.length, sensitivity)}.`}</span>
              <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => setReveal({ key: revealKey, on: !revealed })} aria-pressed={revealed}>
                {revealed ? 'Hide them again' : 'Show them'}
              </button>
            </p>
          )}
          {check && check.specs.length > 0 && (
            <details className="product-specs">
              <summary>Specifications</summary>
              <dl>
                {check.specs.map((spec) => (
                  <div key={spec.label}>
                    <dt>{spec.label}</dt>
                    <dd>
                      {spec.value} {spec.source && <ExternalLink href={spec.source}>Source</ExternalLink>}
                      {spec.quote && <blockquote>{spec.quote}</blockquote>}
                    </dd>
                  </div>
                ))}
              </dl>
            </details>
          )}

          <div className="product-talk">
            <AnimatePresence initial={false}>
              {turns.map((t) => (
                <motion.div key={t.id} className="talk-q" initial={{ opacity: 0, y: m.d(10) }} animate={{ opacity: 1, y: 0 }} transition={m.tx.spring}>
                  <p className="you">{t.text}</p>
                  {t.state === 'running' && (
                    <span className="work-line">
                      <PixelGlyph size={13} active />
                      {t.note || 'Starting research'}
                    </span>
                  )}
                  {t.answer && (
                    <article className="answer">
                      <Markdown text={t.answer} live={t.state === 'running'} />
                    </article>
                  )}
                  {t.state === 'failed' && (
                    <p className="error-note" role="alert">
                      {t.note}
                    </p>
                  )}
                </motion.div>
              ))}
            </AnimatePresence>
            <div ref={end} />
          </div>

          <div className="product-ask">
            <Composer onSubmit={(text) => void ask(text)} running={asking} onStop={stop} placeholder="Ask about this product" agents={false} autoFocus />
          </div>
        </div>

        <aside className="product-side">
          {live && check && <ProcurementSection name={check.name} target={target} lines={lines} seriousCount={seriousCount} loading={procurement.loading} problem={procurement.problem} />}
          {check && (
            <ProductInsights
              key={lookupId}
              lookupId={lookupId}
              live={live}
              onTarget={setTarget}
              onResearch={(question) => void ask(question)}
              onReload={() => setLoadAttempt((value) => value + 1)}
            />
          )}
        </aside>
      </div>
    </div>
  )
}

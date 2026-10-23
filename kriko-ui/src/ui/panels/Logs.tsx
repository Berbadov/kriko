import { Checkbox } from '../../arc/checkbox/checkbox'
import { useMemo, useState } from 'react'
import { useEngine } from '../../engine/Engine'
import {
  LEVELS,
  NO_FILTER,
  SOURCES,
  cost,
  count,
  exportLog,
  facts,
  loadStep,
  span,
  useLogJobs,
  useLogSteps,
  type Level,
  type LogFilter,
  type LogJob,
  type LogStep,
  type LogStepFull,
  type Source,
} from '../../engine/logs'
import { copyText } from '../clipboard'
import { Icon } from '../Icon'

const SOURCE_WORDS: Record<Source, string> = {
  job: 'Job',
  search: 'Search',
  page: 'Page',
  agent: 'Agent',
  verify: 'Verdict',
  retry: 'Retry',
  note: 'Note',
}

const KIND_WORDS: Record<string, string> = {
  research: 'Research',
  quick_look: 'Quick look',
  chat_ask: 'Chat',
  pack_author: 'Catalogue',
  verify: 'Re-check',
}

const kindWord = (kind: string) => KIND_WORDS[kind] ?? kind.replaceAll('_', ' ')

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((one) => one !== value) : [...list, value]
}

/** Every job's steps, in order, with their timing. Filter, open a row for the
 *  exact request and reply, and export a plain text copy. */
export function LogsPanel() {
  const { mode } = useEngine()
  const { jobs, problem: jobsProblem, reload } = useLogJobs()
  const [filter, setFilter] = useState<LogFilter>(NO_FILTER)
  const [bodies, setBodies] = useState(false)
  const [note, setNote] = useState('')

  const job = jobs?.find((one) => one.job_id === filter.job) ?? null
  const following = filter.job ? !!job && !job.done : !!jobs?.some((one) => !one.done)
  const { data, problem, reload: reloadSteps } = useLogSteps(filter, following)

  const set = (patch: Partial<LogFilter>) => setFilter((now) => ({ ...now, ...patch }))
  const filtered = filter.levels.length > 0 || filter.sources.length > 0 || filter.q.trim() !== ''

  const save = async () => {
    setNote('')
    try {
      const made = await exportLog(filter, bodies, mode === 'live')
      const url = URL.createObjectURL(new Blob([made.text], { type: 'text/plain;charset=utf-8' }))
      const link = document.createElement('a')
      link.href = url
      link.download = made.filename
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 30000)
      setNote(`Saved ${made.filename}.`)
    } catch (error) {
      setNote(error instanceof Error ? error.message : 'The log could not be exported.')
    }
  }

  if (!jobs && jobsProblem) {
    return (
      <p className="error-note" role="alert">
        The log could not be read. {jobsProblem} <button className="btn" onClick={() => void reload()}>Try again</button>
      </p>
    )
  }
  if (!jobs) return <p className="panel-note">Reading the log…</p>
  if (!jobs.length) return <p className="panel-note">Nothing has run yet. Every step of every job is kept here.</p>

  return (
    <div className="logs">
      <aside className="logs-jobs" aria-label="Jobs">
        <button className="logs-job" data-on={!filter.job} onClick={() => set({ job: '' })}>
          <strong>Every job</strong>
          <small>{jobs.length} job{jobs.length === 1 ? '' : 's'}, newest first</small>
        </button>
        {jobs.map((one) => (
          <JobRow key={one.job_id} job={one} on={filter.job === one.job_id} onPick={() => set({ job: one.job_id })} />
        ))}
      </aside>

      <section className="logs-main" aria-label="Steps">
        <Summary job={job} jobs={jobs} />

        <div className="logs-filters">
          <label className="search-field">
            <Icon name="search" size={15} />
            <input type="search" placeholder="Search the steps" aria-label="Search the steps" value={filter.q} onChange={(event) => set({ q: event.target.value })} />
          </label>
          <div className="logs-chips" role="group" aria-label="Level">
            {LEVELS.map((level) => (
              <button key={level} className="logs-chip" data-level={level} aria-pressed={filter.levels.includes(level)} onClick={() => set({ levels: toggle<Level>(filter.levels, level) })}>
                {level === 'info' ? 'Info' : level === 'warn' ? 'Warnings' : 'Errors'}
              </button>
            ))}
          </div>
          <div className="logs-chips" role="group" aria-label="Source">
            {SOURCES.map((source) => (
              <button key={source} className="logs-chip" aria-pressed={filter.sources.includes(source)} onClick={() => set({ sources: toggle<Source>(filter.sources, source) })}>
                {SOURCE_WORDS[source]}
              </button>
            ))}
          </div>
          <div className="logs-actions">
            {filtered && <button className="btn ghost" onClick={() => set({ levels: [], sources: [], q: '' })}>Clear filters</button>}
            <Checkbox checked={bodies} onCheckedChange={(next) => setBodies(next === true)} label="Include prompts and replies" />
            <button className="btn" onClick={() => void save()}>
              Export as text
            </button>
          </div>
        </div>
        {note && <p className="panel-note" role="status">{note}</p>}
        {problem && <p className="error-note">{problem} <button className="btn" onClick={() => void reloadSteps()}>Try again</button></p>}

        {!data && !problem && <p className="panel-note">Reading the steps…</p>}
        {data && data.items.length === 0 && <p className="panel-note">{filtered ? 'No step matches these filters.' : 'This job has no steps yet.'}</p>}
        {data && data.truncated && <p className="panel-note">Showing the latest {data.items.length} of {data.total} steps. Narrow the filters, or export, to reach the rest.</p>}
        {data && data.items.length > 0 && (
          <ol className="logs-steps" aria-label="Steps in order">
            {data.items.map((one, index) => (
              <StepRow key={one.step_id} step={one} showJob={!filter.job && (index === 0 || data.items[index - 1].job_id !== one.job_id)} job={jobs.find((j) => j.job_id === one.job_id)} live={mode === 'live'} />
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}

function JobRow({ job, on, onPick }: { job: LogJob; on: boolean; onPick: () => void }) {
  return (
    <button className="logs-job" data-on={on} data-state={job.state} onClick={onPick} aria-pressed={on}>
      <strong>{job.label || kindWord(job.kind)}</strong>
      <small>
        {kindWord(job.kind)} · {job.done ? job.state : 'running'}
        {job.duration_ms !== null && ` · ${span(job.duration_ms)}`}
      </small>
      <small className="mono">
        {job.steps} step{job.steps === 1 ? '' : 's'}
        {job.errors > 0 && <span className="logs-bad"> · {job.errors} error{job.errors === 1 ? '' : 's'}</span>}
        {job.calls > 0 && ` · ${job.calls} call${job.calls === 1 ? '' : 's'}`}
      </small>
    </button>
  )
}

/** The totals for what is on show: one job, or every job in the list. */
function Summary({ job, jobs }: { job: LogJob | null; jobs: LogJob[] }) {
  const of = job ? [job] : jobs
  const sum = (pick: (j: LogJob) => number) => of.reduce((all, one) => all + pick(one), 0)
  const counted = of.filter((one) => one.tokens !== null)
  const priced = of.filter((one) => one.usd !== null)
  const tokens = counted.length ? counted.reduce((all, one) => all + (one.tokens ?? 0), 0) : null
  const usd = priced.length ? priced.reduce((all, one) => all + (one.usd ?? 0), 0) : null
  const complete = of.every((one) => one.usd_complete) && priced.length === of.filter((one) => one.calls > 0).length
  return (
    <dl className="logs-summary" aria-label={job ? 'This job' : 'Every job'}>
      <div><dt>Steps</dt><dd>{sum((j) => j.steps)}</dd></div>
      <div><dt>Searches</dt><dd>{sum((j) => j.searches)}</dd></div>
      <div><dt>Pages</dt><dd>{sum((j) => j.pages)}</dd></div>
      <div><dt>Agent calls</dt><dd>{sum((j) => j.calls)}</dd></div>
      <div><dt>Retries</dt><dd>{sum((j) => j.retries)}</dd></div>
      <div data-bad={sum((j) => j.errors) > 0}><dt>Errors</dt><dd>{sum((j) => j.errors)}</dd></div>
      <div><dt>Tokens</dt><dd>{count(tokens)}</dd></div>
      <div><dt>Cost</dt><dd>{cost(usd, complete)}</dd></div>
      {job && <div><dt>Took</dt><dd>{job.done ? span(job.duration_ms) : 'running'}</dd></div>}
    </dl>
  )
}

function StepRow({ step, showJob, job, live }: { step: LogStep; showJob: boolean; job?: LogJob; live: boolean }) {
  const [open, setOpen] = useState(false)
  const [full, setFull] = useState<LogStepFull | null>(null)
  const [problem, setProblem] = useState('')
  const rows = useMemo(() => facts(step), [step])
  const expandable = rows.length > 0 || step.request_chars > 0 || step.response_chars > 0 || step.title.length > 80

  const toggleOpen = () => {
    const next = !open
    setOpen(next)
    if (next && !full && (step.request_chars > 0 || step.response_chars > 0)) {
      loadStep(step.step_id, live).then(setFull).catch((error: unknown) => setProblem(error instanceof Error ? error.message : 'Could not read this step.'))
    }
  }

  return (
    <>
      {showJob && job && (
        <li className="logs-jobhead" aria-hidden="true">
          {job.label || kindWord(job.kind)} · {kindWord(job.kind)} · {job.state}
        </li>
      )}
      <li className="logs-step" data-level={step.level} data-source={step.source} data-state={step.state} style={{ ['--depth' as string]: step.depth }}>
        <button className="logs-line" aria-expanded={expandable ? open : undefined} disabled={!expandable} onClick={toggleOpen}>
          <span className="logs-at mono" title={step.at}>{step.offset_ms === null ? '' : `+${(step.offset_ms / 1000).toFixed(2)} s`}</span>
          <span className="logs-dot" aria-label={step.level} />
          <span className="logs-source">{SOURCE_WORDS[step.source]}</span>
          <span className="logs-title">{step.state === 'running' ? 'Running: ' : ''}{step.title}</span>
          <span className="logs-meta mono">
            {step.ms !== null && <span>{span(step.ms)}</span>}
            {step.tokens !== null && <span>{count(step.tokens)} tok</span>}
            {step.usd !== null && <span>{cost(step.usd)}</span>}
          </span>
        </button>
        {open && (
          <div className="logs-open">
            <dl className="logs-facts">
              {rows.map(([name, value]) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
              {step.gap_ms !== null && <div><dt>Until the next step</dt><dd>{span(step.gap_ms)}</dd></div>}
            </dl>
            {problem && <p className="error-note">{problem}</p>}
            {(step.request_chars > 0 || step.response_chars > 0) && !full && !problem && <p className="panel-note">Reading it…</p>}
            {full && <Body label="Request" text={full.request} />}
            {full && <Body label="Response" text={full.response} />}
            <p className="panel-note logs-redacted">Keys and the words you saved about yourself are taken out before anything is kept.</p>
          </div>
        )}
      </li>
    </>
  )
}

function Body({ label, text }: { label: string; text: string }) {
  const [copied, setCopied] = useState(false)
  if (!text) return null
  return (
    <section className="logs-body">
      <header>
        <h4>{label} <span className="muted mono">{text.length.toLocaleString('en-GB')} characters</span></h4>
        <button className="btn ghost" onClick={() => void copyText(text).then((ok) => { setCopied(ok); window.setTimeout(() => setCopied(false), 1500) })}>
          <Icon name="copy" size={14} /> {copied ? 'Copied' : 'Copy'}
        </button>
      </header>
      <pre tabIndex={0}>{text}</pre>
    </section>
  )
}

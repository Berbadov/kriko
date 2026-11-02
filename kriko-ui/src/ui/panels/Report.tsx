import { useEffect, useRef, useState } from 'react'
import { useEngine } from '../../engine/Engine'
import { useLogJobs } from '../../engine/logs'
import { KINDS, canDraft, draftReport, jobLabel, reportable, takeRequestedReport, type ReportDraft, type ReportKind } from '../../engine/report'
import { copyText } from '../clipboard'
import { Segmented, Select } from '../controls'
import { openLink } from '../ExternalLink'

/** Tell us what broke, or what to add. Kriko writes the report and shows all of it;
 *  the reader copies it, saves it, or opens it as an issue and presses Submit there. */
export function ReportPanel() {
  const { mode } = useEngine()
  const { jobs } = useLogJobs()
  const [incoming] = useState(takeRequestedReport)
  const [kind, setKind] = useState<ReportKind>('error')
  const [picked, setPicked] = useState<string | null>(incoming?.jobId || null)
  const [note, setNote] = useState(incoming?.note ?? '')
  const [written, setWritten] = useState<{ asked: string; draft: ReportDraft } | null>(null)
  const [status, setStatus] = useState('')
  const [working, setWorking] = useState(false)

  const runs = reportable(jobs ?? [])
  const jobId = picked ?? runs[0]?.job_id ?? ''
  const asked = `${kind}|${jobId}|${note}`
  const draft = written?.asked === asked ? written.draft : null

  const show = async () => {
    setWorking(true)
    setStatus('')
    try {
      setWritten({ asked, draft: await draftReport(kind, jobId, note, mode === 'live') })
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'The report could not be written.')
    } finally {
      setWorking(false)
    }
  }

  // An error that sent the reader here has its report written as soon as its run is known.
  const wrote = useRef(false)
  useEffect(() => {
    if (!incoming || wrote.current || (!incoming.jobId && jobs === null)) return
    wrote.current = true
    void show()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, with what the error asked for
  }, [incoming, jobs])

  const copy = async () => setStatus((await copyText(draft?.text ?? '')) ? 'Copied.' : 'Copying was refused. Select the text and copy it by hand.')

  const save = () => {
    if (!draft) return
    const url = URL.createObjectURL(new Blob([draft.text], { type: 'text/plain;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = draft.filename
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 30000)
    setStatus(`Saved ${draft.filename}.`)
  }

  const open = async () => {
    if (!draft) return
    await copyText(draft.text)
    await openLink(draft.url)
    setStatus('The full report is copied. GitHub shows a draft issue; nothing is sent until you press Submit there.')
  }

  return (
    <div className="panel-body">
      <section className="panel-group">
        <h3>Tell us what broke, or what to add</h3>
        <p>
          Kriko writes the report here and sends nothing. You read all of it first, with keys and your saved profile
          removed, then copy it, save it, or open it as an issue on GitHub and press Submit yourself.
        </p>
        <Segmented label="What is this about" value={kind} options={KINDS} onChange={setKind} />
      </section>
      {kind === 'error' && (
        <section className="panel-group">
          <h3>Which run</h3>
          {runs.length ? (
            <Select label="Which run" value={jobId} onChange={setPicked} options={[{ value: '', label: 'None, I will describe it' }, ...runs.map((one) => ({ value: one.job_id, label: jobLabel(one) }))]} />
          ) : (
            <p className="panel-note">No failed run is on record. Describe what happened below.</p>
          )}
        </section>
      )}
      <section className="panel-group need-field">
        <h3>{kind === 'error' ? 'What happened' : 'Your suggestion'}</h3>
        <textarea
          aria-label={kind === 'error' ? 'What happened' : 'Your suggestion'}
          rows={5}
          maxLength={4000}
          value={note}
          placeholder={kind === 'error' ? 'For example: Mistral timed out on every chat turn.' : 'What would make Kriko better for you?'}
          onChange={(event) => setNote(event.target.value)}
        />
        <button className="btn primary" disabled={working || !canDraft(kind, jobId, note)} onClick={() => void show()}>
          Write the report
        </button>
      </section>
      {draft && (
        <section className="panel-group">
          <h3>Everything this report says</h3>
          <pre className="report-text" tabIndex={0}>{draft.text}</pre>
          <div className="report-actions">
            <button className="btn" onClick={() => void copy()}>Copy report</button>
            <button className="btn ghost" onClick={save}>Save as a file</button>
            {draft.url && <button className="btn primary" onClick={() => void open()}>Open on GitHub</button>}
          </div>
        </section>
      )}
      {status && <p role="status" className="panel-note">{status}</p>}
    </div>
  )
}

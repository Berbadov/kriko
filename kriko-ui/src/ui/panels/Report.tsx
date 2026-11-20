import { useEffect, useRef, useState } from 'react'
import { useEngine } from '../../engine/Engine'
import { useLogJobs } from '../../engine/logs'
import { KINDS, canDraft, draftReport, jobLabel, reportable, takeRequestedReport, type ReportDraft, type ReportKind } from '../../engine/report'
import { copyText } from '../clipboard'
import { openLink } from '../ExternalLink'
import { Choice, SelectField } from './settingsParts'

/** Tell us what broke, or what to add. Kriko writes the report here and shows all of it;
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
    <div className="settings-data-panel-body">
      <div className="settings-data-block">
        <Choice label="What is this about" value={kind} options={KINDS} onChange={setKind} />
      </div>

      {kind === 'error' && (
        <div className="settings-data-block">
          <h4>Which run</h4>
          {runs.length ? (
            <SelectField label="Which run" value={jobId} onChange={setPicked} options={[{ value: '', label: 'None, I will describe it' }, ...runs.map((one) => ({ value: one.job_id, label: jobLabel(one) }))]} />
          ) : (
            <p className="settings-data-words">No failed run is on record. Describe what happened below.</p>
          )}
        </div>
      )}

      <div className="settings-data-block">
        <label className="settings-data-field">
          <span className="settings-data-field-label">{kind === 'error' ? 'What happened' : 'Your suggestion'}</span>
          <textarea
            className="k-input"
            rows={5}
            maxLength={4000}
            value={note}
            placeholder={kind === 'error' ? 'For example: Mistral timed out on every chat turn.' : 'What would make Kriko better for you?'}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        <div>
          <button type="button" className="k-btn" data-kind="primary" disabled={working || !canDraft(kind, jobId, note)} onClick={() => void show()}>
            Write the report
          </button>
        </div>
      </div>

      {draft && (
        <div className="settings-data-block">
          <h4>Everything this report says</h4>
          <pre className="settings-data-report" tabIndex={0}>
            {draft.text}
          </pre>
          <div className="settings-data-controls">
            {draft.url && (
              <button type="button" className="k-btn" data-kind="primary" onClick={() => void open()}>
                Open on GitHub
              </button>
            )}
            <button type="button" className="k-btn" onClick={() => void copy()}>
              Copy report
            </button>
            <button type="button" className="k-btn" data-kind="quiet" onClick={save}>
              Save as a file
            </button>
          </div>
        </div>
      )}
      {status && (
        <p role="status" className="settings-data-status">
          {status}
        </p>
      )}
    </div>
  )
}

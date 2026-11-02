import { reportProblem } from '../engine/report'

/** Beside an error: opens the report with this run's log already written. */
export function ReportButton({ jobId, note }: { jobId?: string; note: string }) {
  return (
    <button className="btn ghost report-this" onClick={() => reportProblem({ jobId, note })}>
      Report this
    </button>
  )
}

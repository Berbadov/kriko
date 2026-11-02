import type { LogJob } from './logformat'

export type ReportKind = 'error' | 'suggestion'

export interface ReportRequest {
  jobId: string
  note: string
}

let pending: ReportRequest | null = null

/** An error asked to be reported. The report section, once open, picks it up. */
export const askToReport = (request: Partial<ReportRequest>) => {
  pending = { jobId: request.jobId ?? '', note: request.note ?? '' }
}

/** What was asked for last, once. */
export const takeRequestedReport = (): ReportRequest | null => {
  const asked = pending
  pending = null
  return asked
}

export const KINDS = [
  { value: 'error', label: 'Something went wrong' },
  { value: 'suggestion', label: 'A suggestion' },
] as const

/** Runs worth reporting: failed, interrupted, or finished with errors in their log. */
export const reportable = (jobs: readonly LogJob[]): LogJob[] =>
  jobs.filter((one) => one.state === 'failed' || one.state === 'interrupted' || one.errors > 0)

export const jobLabel = (job: LogJob): string =>
  [job.kind.replaceAll('_', ' '), job.label, job.state].filter(Boolean).join(' · ')

export const askBody = (kind: ReportKind, jobId: string, note: string) => ({
  kind,
  job_id: kind === 'error' ? jobId : '',
  note,
})

/** A suggestion needs words. A problem needs words or a run to read. */
export const canDraft = (kind: ReportKind, jobId: string, note: string): boolean =>
  note.trim() !== '' || (kind === 'error' && jobId !== '')

import type { LogJob } from './logformat'

export type ReportKind = 'error' | 'suggestion'

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

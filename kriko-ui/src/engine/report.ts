import { showDrawer } from '../ui/drawerEvents'
import { post } from './api'
import { askBody, askToReport, type ReportKind, type ReportRequest } from './reportformat'

export * from './reportformat'

/** Open the report section on this error, with its run's log. */
export function reportProblem(request: Partial<ReportRequest> = {}) {
  askToReport(request)
  showDrawer('report')
}

export interface ReportDraft {
  title: string
  text: string
  filename: string
  url: string
}

/** The report as it would be sent, composed by the engine. Nothing leaves this computer here. */
export async function draftReport(kind: ReportKind, jobId: string, note: string, live: boolean): Promise<ReportDraft> {
  if (!live) {
    const text = `## ${kind === 'error' ? 'What happened' : 'Suggestion'}\n${note || '(nothing written)'}\n\n## This machine\nKriko demo\n`
    return { title: `[${kind === 'error' ? 'problem' : 'suggestion'}] ${note.slice(0, 70)}`, text, filename: `kriko-${kind}-report.txt`, url: '' }
  }
  return post<ReportDraft>('/api/report/draft', askBody(kind, jobId, note), 30000)
}

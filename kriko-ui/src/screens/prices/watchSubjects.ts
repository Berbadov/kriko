/** The product the reader chose for a watch, so the next "Add as a quote"
 *  skips the search. A convenience kept in this window's own storage, never
 *  state of record: the estimate holds the truth, and every read and write here
 *  survives storage being blocked or holding something else. */

export const WATCH_SUBJECTS_KEY = 'kriko.watchSubjects'

export interface WatchSubject {
  subject_id: string
  pack_id: string
  label: string
}

const valid = (value: unknown): value is WatchSubject => {
  const one = value as Partial<WatchSubject> | null
  return !!one && typeof one === 'object' && typeof one.subject_id === 'string' && typeof one.pack_id === 'string' && typeof one.label === 'string' && one.subject_id !== ''
}

export function readWatchSubjects(): Record<string, WatchSubject> {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(WATCH_SUBJECTS_KEY) || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const out: Record<string, WatchSubject> = {}
    for (const [id, value] of Object.entries(parsed)) {
      if (valid(value)) out[id] = { subject_id: value.subject_id, pack_id: value.pack_id, label: value.label }
    }
    return out
  } catch {
    return {}
  }
}

export function watchSubjectOf(watchId: string): WatchSubject | null {
  return readWatchSubjects()[watchId] ?? null
}

export function rememberWatchSubject(watchId: string, subject: WatchSubject): void {
  try {
    const all = readWatchSubjects()
    all[watchId] = { subject_id: subject.subject_id, pack_id: subject.pack_id, label: subject.label }
    window.localStorage.setItem(WATCH_SUBJECTS_KEY, JSON.stringify(all))
  } catch {
    /* storage is blocked or full: the reader searches again next time */
  }
}

export function forgetWatchSubject(watchId: string): void {
  try {
    const all = readWatchSubjects()
    delete all[watchId]
    window.localStorage.setItem(WATCH_SUBJECTS_KEY, JSON.stringify(all))
  } catch {
    /* nothing kept, nothing to forget */
  }
}

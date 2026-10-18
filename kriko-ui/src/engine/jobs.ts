import { get, seg, type ApiJob } from './api'

const POLL_MS = 700
const ENDED = new Set(['succeeded', 'failed', 'cancelled'])

/** Read a job until it ends. `onReading` sees each reading, so a screen can
 *  show the partial result. `stillWanted` ends the wait when the screen is gone. */
export async function followJob(job: string, onReading: (reading: ApiJob) => void, stillWanted: () => boolean = () => true): Promise<ApiJob | null> {
  for (;;) {
    await new Promise((resolve) => window.setTimeout(resolve, POLL_MS))
    if (!stillWanted()) return null
    const reading = await get<ApiJob>(`/api/jobs/${seg(job)}`)
    onReading(reading)
    if (reading.done || ENDED.has(reading.state)) return reading
  }
}

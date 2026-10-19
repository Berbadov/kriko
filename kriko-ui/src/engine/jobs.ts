import { get, seg, type ApiJob } from './api'

const POLL_MS = 700
const ENDED = new Set(['succeeded', 'failed', 'cancelled'])

/**
 * How long one follow may last before it gives up.
 *
 * A research run can legitimately take many minutes, and the engine's own job
 * runner cancels anything that outlives its budget — so this is deliberately
 * long. What it exists to stop is a job that is stuck `running` in the
 * database: the loop had no deadline at all, so a single wedged row meant a
 * request every 700 ms for the life of the window, with no way out and nothing
 * on screen saying why.
 */
const FOLLOW_LIMIT_MS = 45 * 60 * 1000

/** Read a job until it ends. `onReading` sees each reading, so a screen can
 *  show the partial result. `stillWanted` ends the wait when the screen is gone.
 *
 *  Returns the last reading when the deadline passes rather than `null`: the
 *  caller then says "this is still running" instead of "nothing happened",
 *  which is the difference the engine's own `interrupted` state exists for. */
export async function followJob(
  job: string,
  onReading: (reading: ApiJob) => void,
  stillWanted: () => boolean = () => true,
  limitMs: number = FOLLOW_LIMIT_MS,
): Promise<ApiJob | null> {
  const deadline = Date.now() + limitMs
  let last: ApiJob | null = null
  for (;;) {
    await new Promise((resolve) => window.setTimeout(resolve, POLL_MS))
    if (!stillWanted()) return null
    const reading = await get<ApiJob>(`/api/jobs/${seg(job)}`)
    last = reading
    onReading(reading)
    if (reading.done || ENDED.has(reading.state)) return reading
    if (Date.now() >= deadline) return last
  }
}

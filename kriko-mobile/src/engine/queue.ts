/** Run a snapshot of queued work in order, isolating each task's failure. */
export async function drainQueue<T extends { id: string; status: string }>(
  jobs: readonly T[],
  execute: (job: T) => Promise<void>,
  isCancelled: (id: string) => boolean = () => false,
): Promise<void> {
  for (const job of jobs) {
    if (job.status !== 'queued' || isCancelled(job.id)) continue;
    try {
      await execute(job);
    } catch {
      // One broken scan must not strand later products in the queue.
    }
  }
}

/** Where an agent's run stands among its steps, from the progress the engine
 *  reports. The steps are equal quarters of that progress; the screen does not
 *  claim a stage the engine did not name. `at` is the current step (-1 before
 *  the run starts, `count` once it is done) and `within` is how much of the
 *  line after it is lit. */
export function stepOf(value: number, state: 'waiting' | 'researching' | 'paused' | 'done', count: number): { at: number; within: number } {
  if (state === 'done') return { at: count, within: 1 }
  if (state === 'waiting') return { at: -1, within: 0 }
  const fraction = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0))
  const at = Math.min(count - 1, Math.floor(fraction * count))
  return { at, within: Math.min(1, fraction * count - at) }
}

/** Small pieces of text the interface counts and formats. Kept out of the React
 *  modules so a test can read them without a browser. */

/** A count with its noun in the number the reader is looking at. */
export function count(n: number, singular: string, plural = `${singular}s`): string {
  return `${n} ${n === 1 ? singular : plural}`
}

/**
 * A duration the reader reads, to one decimal below ten seconds and never with
 * a leftover 60 seconds: 119.6 s is "2 min 0 s", not "1 min 60 s".
 *
 * Rounding happens before the unit is chosen, because the old order let 59.6 s
 * print "60 s" and 3599.9 s print "59 min 60 s".
 */
export function formatSeconds(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0
  if (safe < 9.95) return `${safe.toFixed(1)} s`
  const whole = Math.round(safe)
  if (whole < 60) return `${whole} s`
  const minutes = Math.floor(whole / 60)
  const rest = whole % 60
  if (minutes < 60) return `${minutes} min ${rest} s`
  const hours = Math.floor(minutes / 60)
  return `${hours} h ${minutes % 60} min`
}

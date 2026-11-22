/**
 * One animation frame loop for every piece of dust on screen. A dozen working
 * glyphs and a sky would otherwise be a dozen loops; here they share one, and
 * it stops when nothing is subscribed, the window is hidden or motion is off.
 *
 * Dust is ambience, so it is drawn at most 30 times a second (a ticker that
 * skips every other frame costs half the work and the eye does not miss it),
 * and the step it hands out is scaled to match, so speed does not change.
 */

type Tick = (dt: number, t: number) => void

const FRAME_MS = 1000 / 30

/** Fewer than five logical cores: the machine has little to spare for decoration. */
export const lowCores = (): boolean => typeof navigator !== 'undefined' && (navigator.hardwareConcurrency || 8) <= 4

const ticks = new Set<Tick>()
let frame = 0
let last = 0

const still = () => typeof document !== 'undefined' && document.documentElement.dataset.motion === 'off'

function loop(now: number) {
  frame = 0
  if (!ticks.size || document.hidden || still()) return
  // Wait for the next frame when this one came too soon after the last drawn one.
  if (last && now - last < FRAME_MS - 2) {
    frame = requestAnimationFrame(loop)
    return
  }
  const dt = last ? Math.min(3, ((now - last) / 1000) * 60) : 1
  last = now
  const t = now / 1000
  for (const tick of ticks) tick(dt, t)
  frame = requestAnimationFrame(loop)
}

function start() {
  if (!frame && ticks.size && !document.hidden && !still()) {
    last = 0
    frame = requestAnimationFrame(loop)
  }
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && frame) {
      cancelAnimationFrame(frame)
      frame = 0
    } else start()
  })
}

/** Run `tick` every frame until the returned function is called. */
export function onFrame(tick: Tick): () => void {
  ticks.add(tick)
  start()
  return () => {
    ticks.delete(tick)
    if (!ticks.size && frame) {
      cancelAnimationFrame(frame)
      frame = 0
    }
  }
}

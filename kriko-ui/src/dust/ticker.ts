/**
 * One animation frame loop for every piece of dust on screen. A dozen working
 * glyphs and a sky would otherwise be a dozen loops; here they share one, and
 * it stops when nothing is subscribed or the window is hidden.
 */

type Tick = (dt: number, t: number) => void

const ticks = new Set<Tick>()
let frame = 0
let last = 0

function loop(now: number) {
  frame = 0
  if (!ticks.size || document.hidden) return
  const dt = last ? Math.min(3, ((now - last) / 1000) * 60) : 1
  last = now
  const t = now / 1000
  for (const tick of ticks) tick(dt, t)
  frame = requestAnimationFrame(loop)
}

function start() {
  if (!frame && ticks.size && !document.hidden) {
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

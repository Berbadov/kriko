import { useEffect, useRef } from 'react'
import { usePrefs } from '../prefs'
import { Dust, grainsFor, type Motion, type Scene } from './engine'
import { useAfterIdle } from '../idle'
import { lowCores, onFrame } from './ticker'

/** The motion setting, as the dust reads it: off is still, calm is calm. */
export function useDustMotion(): Motion {
  const { motion, profile } = usePrefs()
  return !motion.on ? 'still' : profile === 'calm' ? 'calm' : 'full'
}

/** Whether a colour is light enough that grains should add light rather than ink. */
function glows(colour: string): boolean {
  const m = colour.match(/\d+(\.\d+)?/g)
  if (!m) return false
  const [r, g, b] = m.map(Number)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 140
}

const BINS = 10
/** A frame of dust that takes longer than this (milliseconds, smoothed) halves the rate. */
const FRAME_BUDGET_MS = 6

/**
 * A field of dust filling its parent. The grains take the element's own
 * `color`, so a stylesheet decides the ink; a light ink is drawn as light on a
 * dark ground, a dark one as ink on paper.
 *
 * `scene` changes are animated: the grains fly to the new picture. `reading`
 * passes a band of light down through the cloud while work runs. It does not
 * react to the cursor, which kept the whole field busy for nothing.
 */
export function DustField({
  scene,
  reading = false,
  per = 12,
  cap = 16000,
  className,
}: {
  scene: Scene
  reading?: boolean
  /** Square pixels of field per grain. */
  per?: number
  /** The most grains this field may carry, whatever its size. */
  cap?: number
  className?: string
}) {
  const ref = useRef<HTMLCanvasElement>(null)
  const dust = useRef<Dust | null>(null)
  const motion = useDustMotion()
  const { resolved } = usePrefs()
  // Decoration waits for the first idle moment, so it is never on the way to an interactive window.
  const ready = useAfterIdle()
  const state = useRef({ scene, reading, motion, visible: true, dirty: true })
  /** Set while the field is running: starts or stops its frame loop to match the state. */
  const sync = useRef<() => void>(() => undefined)
  useEffect(() => {
    state.current.reading = reading
    state.current.motion = motion
    state.current.dirty = true
    sync.current()
  }, [reading, motion])

  // A new scene: the grains fly to it, or land on it when nothing may move.
  useEffect(() => {
    state.current.scene = scene
    dust.current?.show(scene, { scatter: motion === 'full' ? 1 : 0.4, settle: motion === 'still' })
    state.current.dirty = true
    sync.current()
  }, [scene, motion])

  useEffect(() => {
    const canvas = ref.current
    const ctx = ready ? canvas?.getContext('2d') : null
    if (!canvas || !ctx) return
    let colour = getComputedStyle(canvas).color
    let light = glows(colour)
    let out: ReturnType<Dust['buffers']> | null = null
    let dpr = 1
    let frames = 0
    // A machine with few cores gets half the grains.
    const share = lowCores() ? 0.5 : 1
    const budget = Math.round(cap * share)
    const spacing = per / share

    const size = () => {
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      if (!w || !h) return
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      const count = grainsFor(w, h, spacing, budget)
      if (!dust.current || dust.current.count !== count) {
        dust.current = new Dust({ count, seed: 7 })
        dust.current.resize(w, h)
        dust.current.show(state.current.scene, { settle: true })
        out = dust.current.buffers(BINS)
      } else dust.current.resize(w, h)
      out ??= dust.current.buffers(BINS)
      state.current.dirty = true
    }

    const draw = (t: number) => {
      const d = dust.current
      if (!d || !out) return
      const s = state.current
      const band = s.reading ? { y: ((t % 2.6) / 2.6) * (d.h + 120) - 60, width: 24 } : undefined
      d.sort(out, { shimmer: s.motion === 'full', band })
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, d.w, d.h)
      ctx.globalCompositeOperation = light ? 'lighter' : 'source-over'
      ctx.fillStyle = colour
      for (let b = 0; b < BINS; b++) {
        const n = out.counts[b]
        if (!n) continue
        ctx.globalAlpha = ((b + 0.5) / BINS) * (light ? 0.6 : 0.5)
        const p = out.points[b]
        for (let i = 0; i < n; i++) ctx.fillRect(p[i * 2], p[i * 2 + 1], 1.2, 1.2)
      }
      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
    }

    // The frame loop runs only while the grains can move and can be seen. Motion off
    // draws once and holds; a field scrolled out of view subscribes to nothing.
    let stop: (() => void) | null = null
    // A frame that costs more than a budget makes the next one wait: a slow machine
    // draws the dust at half the rate rather than starve the page of its main thread.
    let cost = 0
    let owed = 0
    const tick = (dt: number, t: number) => {
      const s = state.current
      if (cost > FRAME_BUDGET_MS && owed++ % 2 === 0) return
      const began = performance.now()
      // The ink is read again about once a second, not every frame: a style read forces layout.
      if (++frames % 30 === 0) {
        const now = getComputedStyle(canvas).color
        if (now !== colour) {
          colour = now
          light = glows(colour)
        }
      }
      dust.current?.step(dt, t, s.motion)
      draw(t)
      cost = cost * 0.8 + (performance.now() - began) * 0.2
    }
    const update = () => {
      const s = state.current
      const moving = s.visible && s.motion !== 'still'
      if (moving && !stop) stop = onFrame(tick)
      else if (!moving && stop) {
        stop()
        stop = null
      }
      if (!moving && s.dirty) {
        draw(0)
        s.dirty = false
      }
    }

    size()
    const resize = new ResizeObserver(() => {
      size()
      update()
    })
    resize.observe(canvas)
    const seen = new IntersectionObserver(([entry]) => {
      state.current.visible = entry.isIntersecting
      update()
    })
    seen.observe(canvas)
    sync.current = update
    update()

    return () => {
      sync.current = () => undefined
      stop?.()
      resize.disconnect()
      seen.disconnect()
    }
  }, [per, cap, resolved, ready])

  return <canvas ref={ref} className={className} aria-hidden="true" />
}

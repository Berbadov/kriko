import { useEffect, useRef } from 'react'
import { usePrefs } from '../prefs'
import { Dust, grainsFor, type Motion, type Scene } from './engine'
import { onFrame } from './ticker'

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

/**
 * A field of dust filling its parent. The grains take the element's own
 * `color`, so a stylesheet decides the ink; a light ink is drawn as light on a
 * dark ground, a dark one as ink on paper.
 *
 * `scene` changes are animated: the grains fly to the new picture. `reading`
 * passes a band of light down through the cloud while work runs.
 * `follow` lets the cursor push the dust aside, read from the window so the
 * field never takes a click from what sits on top of it.
 */
export function DustField({
  scene,
  reading = false,
  follow = false,
  per = 12,
  cap = 16000,
  className,
}: {
  scene: Scene
  reading?: boolean
  follow?: boolean
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
  const state = useRef({ scene, reading, motion, visible: true, dirty: true })
  useEffect(() => {
    state.current.reading = reading
    state.current.motion = motion
    state.current.dirty = true
  }, [reading, motion])

  // A new scene: the grains fly to it, or land on it when nothing may move.
  useEffect(() => {
    state.current.scene = scene
    dust.current?.show(scene, { scatter: motion === 'full' ? 1 : 0.4, settle: motion === 'still' })
    state.current.dirty = true
  }, [scene, motion])

  useEffect(() => {
    const canvas = ref.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    let colour = getComputedStyle(canvas).color
    let light = glows(colour)
    let out: ReturnType<Dust['buffers']> | null = null
    let dpr = 1

    const size = () => {
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      if (!w || !h) return
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      const count = grainsFor(w, h, per, cap)
      if (!dust.current || dust.current.count !== count) {
        dust.current = new Dust({ count, seed: 7 })
        dust.current.resize(w, h)
        dust.current.show(state.current.scene, { settle: true })
        out = dust.current.buffers(BINS)
      } else dust.current.resize(w, h)
      out ??= dust.current.buffers(BINS)
      state.current.dirty = true
    }
    size()
    const resize = new ResizeObserver(size)
    resize.observe(canvas)
    const seen = new IntersectionObserver(([entry]) => {
      state.current.visible = entry.isIntersecting
    })
    seen.observe(canvas)

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

    const move = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect()
      dust.current?.point(event.clientX - rect.left, event.clientY - rect.top, 56)
    }
    const leave = () => dust.current?.point(-1e9, -1e9, 0)
    if (follow) {
      window.addEventListener('pointermove', move)
      document.addEventListener('pointerleave', leave)
    }

    const stop = onFrame((dt, t) => {
      const s = state.current
      if (!s.visible) return
      const now = getComputedStyle(canvas).color
      if (now !== colour) {
        colour = now
        light = glows(colour)
      }
      if (s.motion === 'still') {
        if (s.dirty) draw(0)
        s.dirty = false
        return
      }
      dust.current?.step(dt, t, s.motion)
      draw(t)
    })

    return () => {
      stop()
      resize.disconnect()
      seen.disconnect()
      if (follow) {
        window.removeEventListener('pointermove', move)
        document.removeEventListener('pointerleave', leave)
      }
    }
  }, [per, cap, follow, resolved])

  return <canvas ref={ref} className={className} aria-hidden="true" />
}

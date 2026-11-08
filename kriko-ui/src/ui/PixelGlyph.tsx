import { useEffect, useRef, type CSSProperties } from 'react'
import { onFrame } from '../dust/ticker'
import { useDustMotion } from '../dust/DustField'

/**
 * The working glyph: a small knot of dust that turns while work runs and holds
 * still when it does not. It is the same grain as the sky and the product
 * pictures, so every sign of activity in the app is one material.
 *
 * All glyphs share one frame loop, and a glyph that is not active draws once.
 */
export function PixelGlyph({
  size = 16,
  active = true,
  tone = 'accent',
}: {
  size?: number
  active?: boolean
  tone?: 'accent' | 'ink'
}) {
  const ref = useRef<HTMLCanvasElement>(null)
  const motion = useDustMotion()
  const live = active && motion !== 'still'

  useEffect(() => {
    const canvas = ref.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = Math.round(size * dpr)
    canvas.height = Math.round(size * dpr)
    // Grains on a loose ring: an angle, a radius and a brightness each, fixed.
    const n = Math.max(24, Math.round(size * size * 0.55))
    let seed = 9
    const random = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
    const angle = new Float32Array(n)
    const radius = new Float32Array(n)
    const bright = new Float32Array(n)
    const speed = new Float32Array(n)
    for (let i = 0; i < n; i++) {
      angle[i] = random() * Math.PI * 2
      radius[i] = size * (0.18 + 0.28 * Math.sqrt(random()))
      bright[i] = 0.35 + 0.65 * random()
      speed[i] = 0.6 + random() * 0.8
    }
    const grain = Math.max(1, size / 14)
    const draw = (t: number) => {
      const colour = getComputedStyle(canvas).color
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, size, size)
      ctx.fillStyle = colour
      const c = size / 2
      for (let i = 0; i < n; i++) {
        // Inner grains turn faster, so the knot shears as it spins.
        const a = angle[i] + t * speed[i] * (size * 0.55 / radius[i]) * (live ? 1 : 0)
        const flicker = live ? 0.45 + 0.55 * random() : 0.55
        ctx.globalAlpha = bright[i] * flicker * (live ? 1 : 0.5)
        ctx.fillRect(c + Math.cos(a) * radius[i] - grain / 2, c + Math.sin(a) * radius[i] - grain / 2, grain, grain)
      }
      ctx.globalAlpha = 1
    }
    draw(0)
    if (!live) return
    return onFrame((_dt, t) => draw(t))
  }, [size, live])

  const style = { '--size': `${size}px` } as CSSProperties
  return <canvas ref={ref} className={`pixel-glyph tone-${tone}${active ? ' is-active' : ''}`} style={style} aria-hidden="true" />
}

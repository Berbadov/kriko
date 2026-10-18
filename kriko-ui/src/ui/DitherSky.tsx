import { useEffect, useRef } from 'react'
import { usePrefs } from '../prefs'

/** The hero sky. A cloud field is made once, then drawn through an 8x8 ordered
 *  dither into a small palette, so it keeps the look of a pixel print. The
 *  field drifts slowly. It draws one still frame when motion is off. */

const W = 384
const H = 216
const FW = W * 2 // the field is wider than the picture, so it can drift
const FPS = 12

const BAYER = (() => {
  const m = [[0]]
  let size = 1
  while (size < 8) {
    const next: number[][] = Array.from({ length: size * 2 }, () => Array(size * 2).fill(0))
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const v = m[y][x] * 4
        next[y][x] = v
        next[y][x + size] = v + 2
        next[y + size][x] = v + 3
        next[y + size][x + size] = v + 1
      }
    }
    m.length = 0
    m.push(...next)
    size *= 2
  }
  return m.map((row) => row.map((v) => (v + 0.5) / 64))
})()

type Rgb = [number, number, number]
const hex = (h: string): Rgb => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]

const PALETTES = {
  light: {
    sky: ['#3f6be9', '#6a8cf0', '#9db2f6'].map(hex),
    cloud: ['#8f82e6', '#c28fe8', '#f58fb2', '#ffbf9f', '#fff0d4'].map(hex),
  },
  dark: {
    sky: ['#0a0f36', '#16215f', '#2c3c9a'].map(hex),
    cloud: ['#1d2260', '#43347f', '#8a4a97', '#d97aa0', '#f5b9a8'].map(hex),
  },
}

function hash(x: number, y: number, seed: number): number {
  let h = (x * 374761393 + y * 668265263 + seed * 2147483647) | 0
  h = (h ^ (h >>> 13)) * 1274126177
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295
}

/** Value noise that repeats every `period` cells along x. */
function noise(x: number, y: number, period: number, seed: number): number {
  const x0 = Math.floor(x)
  const y0 = Math.floor(y)
  const fx = x - x0
  const fy = y - y0
  const sx = fx * fx * (3 - 2 * fx)
  const sy = fy * fy * (3 - 2 * fy)
  const a = hash(((x0 % period) + period) % period, y0, seed)
  const b = hash((((x0 + 1) % period) + period) % period, y0, seed)
  const c = hash(((x0 % period) + period) % period, y0 + 1, seed)
  const d = hash((((x0 + 1) % period) + period) % period, y0 + 1, seed)
  return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy
}

function makeField(): Float32Array {
  const field = new Float32Array(FW * H)
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < FW; x++) {
      let value = 0
      let amp = 0.55
      let total = 0
      for (let octave = 0; octave < 5; octave++) {
        const cells = 6 * 2 ** octave
        const period = cells
        value += amp * noise((x / FW) * cells, (y / H) * cells * 0.62, period, octave + 3)
        total += amp
        amp *= 0.5
      }
      field[y * FW + x] = value / total
    }
  }
  return field
}

export function DitherSky({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const { resolved, motion } = usePrefs()
  const fieldRef = useRef<Float32Array | null>(null)
  const offset = useRef(-1)

  useEffect(() => {
    const canvas = ref.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    fieldRef.current ??= makeField()
    // Each start looks at a different part of the sky.
    if (offset.current < 0) offset.current = Math.random() * FW
    const field = fieldRef.current
    const image = ctx.createImageData(W, H)
    const { sky, cloud } = PALETTES[resolved]

    const draw = () => {
      const ox = Math.floor(offset.current)
      const data = image.data
      for (let y = 0; y < H; y++) {
        const fy = y / H
        for (let x = 0; x < W; x++) {
          const fx = x / W
          const edge = Math.abs(fx - 0.5) * 2 // 0 in the middle, 1 at the sides
          // Clouds gather at the sides and the top, and thin out toward the horizon and the middle.
          const mask = 0.18 + 1.05 * edge ** 1.4
          const fade = Math.max(0, 1 - fy * 1.12)
          const density = field[y * FW + ((x + ox) % FW)] * mask * (0.35 + fade)
          const bayer = BAYER[y & 7][x & 7]
          let rgb: Rgb
          if (density < 0.36) {
            const level = Math.min(2, Math.floor(fy * 2.2 + bayer * 1.15))
            rgb = sky[level]
          } else {
            const t = (density - 0.36) / 0.34
            const level = Math.max(0, Math.min(cloud.length - 1, Math.floor(t * (cloud.length - 1) + bayer)))
            rgb = cloud[level]
          }
          const i = (y * W + x) * 4
          data[i] = rgb[0]
          data[i + 1] = rgb[1]
          data[i + 2] = rgb[2]
          data[i + 3] = 255
        }
      }
      ctx.putImageData(image, 0, 0)
    }

    draw()
    if (!motion.on) return
    let last = performance.now()
    const timer = window.setInterval(() => {
      const now = performance.now()
      offset.current = (offset.current + ((now - last) / 1000) * 2.2) % FW
      last = now
      draw()
    }, 1000 / FPS)
    return () => window.clearInterval(timer)
  }, [resolved, motion.on])

  return <canvas ref={ref} className={className} width={W} height={H} aria-hidden="true" />
}

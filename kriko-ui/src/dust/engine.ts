/**
 * Dust: a cloud of grains that drifts, shimmers and gathers into pictures.
 *
 * This file is the whole mechanism and knows nothing about a screen. A scene is
 * a density over the field, a function from a point to how much dust belongs
 * there. The engine samples a target for every grain from that density, and
 * each frame pulls the grains towards their targets through a slow flow field,
 * so a change of scene is the cloud rearranging itself rather than a cut. The
 * renderer asks for the grains sorted into a few brightness bins, which keeps
 * a platform's draw calls to one colour change per bin.
 *
 * The same file ships in the desktop app and the phone app. Neither imports
 * anything here but plain arithmetic, so it runs on a JS thread, in a test,
 * or in a worklet without change.
 */

export type Motion = 'full' | 'calm' | 'still'

/** How much dust belongs at a point, 0 to 1, in pixels of a W x H field. */
export type Density = (x: number, y: number, w: number, h: number) => number

export type Scene = { name: string; density: Density }

/* ------------------------------------------------------------- random -- */

/** A small seeded generator, so a scene samples the same way every time. */
export function rng(seed: number): () => number {
  let s = seed >>> 0 || 1
  return () => {
    s ^= s << 13
    s >>>= 0
    s ^= s >>> 17
    s ^= s << 5
    s >>>= 0
    return s / 4294967296
  }
}

/* --------------------------------------------------------- primitives -- */

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v)
/** 1 inside, 0 outside, with a soft edge `soft` pixels wide. */
const edge = (distance: number, soft: number) => clamp01(0.5 - distance / Math.max(soft, 0.0001))

export function disc(x: number, y: number, cx: number, cy: number, r: number, soft = 2): number {
  return edge(Math.hypot(x - cx, y - cy) - r, soft)
}

export function ring(x: number, y: number, cx: number, cy: number, r: number, width: number, soft = 2): number {
  return edge(Math.abs(Math.hypot(x - cx, y - cy) - r) - width / 2, soft)
}

/** A stroke from a to b, `width` wide, with flat-ish caps. */
export function stroke(x: number, y: number, ax: number, ay: number, bx: number, by: number, width: number, soft = 2): number {
  const dx = bx - ax
  const dy = by - ay
  const len2 = dx * dx + dy * dy || 1
  const t = clamp01(((x - ax) * dx + (y - ay) * dy) / len2)
  return edge(Math.hypot(x - (ax + t * dx), y - (ay + t * dy)) - width / 2, soft)
}

/** A filled rounded rectangle centred on (cx, cy). */
export function box(x: number, y: number, cx: number, cy: number, hw: number, hh: number, r = 0, soft = 2): number {
  const qx = Math.abs(x - cx) - hw + r
  const qy = Math.abs(y - cy) - hh + r
  const outside = Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r
  return edge(outside, soft)
}

/** The outline of a rounded rectangle, `width` wide. */
export function frame(x: number, y: number, cx: number, cy: number, hw: number, hh: number, r: number, width: number, soft = 2): number {
  const qx = Math.abs(x - cx) - hw + r
  const qy = Math.abs(y - cy) - hh + r
  const d = Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r
  return edge(Math.abs(d) - width / 2, soft)
}

/** A soft glow: 1 at the centre, falling to 0 at `r`. */
export function glow(x: number, y: number, cx: number, cy: number, r: number): number {
  const d = Math.hypot(x - cx, y - cy) / r
  return d >= 1 ? 0 : (1 - d) * (1 - d)
}

const max = (...values: number[]) => Math.max(0, ...values)

/* ------------------------------------------------------------- scenes -- */

/** The resting cloud: soft banks of dust, thicker at the edges, open in the middle. */
export function cloud(open = { x: 0.5, y: 0.5, r: 0.22 }): Scene {
  return {
    name: 'cloud',
    density: (x, y, w, h) => {
      const m = Math.min(w, h)
      const banks = max(
        glow(x, y, w * 0.08, h * 0.22, m * 0.62),
        glow(x, y, w * 0.95, h * 0.08, m * 0.5) * 0.9,
        glow(x, y, w * 0.9, h * 0.9, m * 0.55) * 0.8,
        glow(x, y, w * 0.05, h * 0.95, m * 0.4) * 0.6,
        glow(x, y, w * 0.6, h * 0.02, m * 0.3) * 0.5,
      )
      const hole = glow(x, y, w * open.x, h * open.y, m * open.r * 2)
      return 0.025 + banks * (1 - hole * 0.92)
    },
  }
}

/** While a page is read the dust spreads evenly, so the band of light has something to cross. */
export const reading: Scene = { name: 'reading', density: () => 0.4 }

/** Where a picture sits in the field: centred, a little above the middle. */
function stage(w: number, h: number, top = 0.48) {
  const s = Math.min(w * 0.82, h * 0.96)
  return { cx: w / 2, cy: h * top, s }
}

/** Kriko's own mark: the jack on its side, perch, raised arms and the screw between. */
export const jack: Scene = {
  name: 'jack',
  density: (x, y, w, h) => {
    const { cx, cy, s } = stage(w, h, 0.5)
    const u = s / 134 // the mark is 134 units wide
    const px = (v: number) => cx + (v - 50) * u
    const py = (v: number) => cy + (v - 46) * u
    const t = 12 * u
    return max(
      stroke(x, y, px(50), py(50), px(-6), py(14), t),
      stroke(x, y, px(50), py(50), px(106), py(14), t),
      box(x, y, px(50), py(52), 33 * u, 8 * u),
      box(x, y, px(50), py(21), 7 * u, 7 * u),
      box(x, y, px(50), py(50), 3 * u, 24 * u),
      box(x, y, px(50), py(75), 15 * u, 3 * u),
    )
  },
}

export type Kind =
  | 'keyboard' | 'bike' | 'phone' | 'laptop' | 'headphones' | 'washer'
  | 'car' | 'screen' | 'watch' | 'box'

/** A product drawn in dust, from what kind of thing it is. */
export function product(kind: Kind): Scene {
  return { name: `product:${kind}`, density: (x, y, w, h) => {
    const { cx, cy, s } = stage(w, h)
    const k = s / 100 // the drawings are on a 100-unit square
    const X = (v: number) => cx + (v - 50) * k
    const Y = (v: number) => cy + (v - 50) * k
    const L = (v: number) => v * k
    const halo = glow(x, y, cx, cy, s * 0.62) * 0.16
    let d = 0
    switch (kind) {
      case 'keyboard': {
        d = box(x, y, X(50), Y(50), L(46), L(16), L(5)) * 0.42
        for (let row = 0; row < 4; row++) {
          for (let col = 0; col < 11; col++) {
            const kx = 12 + col * 7.6 + (row % 2) * 2
            if (kx > 90) continue
            d = Math.max(d, disc(x, y, X(kx), Y(39 + row * 7.5), L(2.6)))
          }
        }
        d = Math.max(d, box(x, y, X(50), Y(62.5), L(16), L(2.4), L(2.4)))
        break
      }
      case 'bike':
        d = max(
          ring(x, y, X(24), Y(62), L(18), L(4)), ring(x, y, X(76), Y(62), L(18), L(4)),
          stroke(x, y, X(24), Y(62), X(46), Y(62), L(4)), stroke(x, y, X(46), Y(62), X(66), Y(34), L(4)),
          stroke(x, y, X(24), Y(62), X(40), Y(34), L(4)), stroke(x, y, X(40), Y(34), X(66), Y(34), L(4)),
          stroke(x, y, X(40), Y(34), X(46), Y(62), L(4)), stroke(x, y, X(66), Y(34), X(76), Y(62), L(4)),
          stroke(x, y, X(34), Y(28), X(46), Y(28), L(4)), stroke(x, y, X(66), Y(34), X(70), Y(24), L(4)),
        )
        break
      case 'phone':
        d = max(frame(x, y, X(50), Y(50), L(19), L(38), L(6), L(4)),
          box(x, y, X(50), Y(50), L(15), L(33), L(3)) * 0.22, box(x, y, X(50), Y(16), L(5), L(1.6), L(1.6)))
        break
      case 'laptop':
        d = max(frame(x, y, X(50), Y(40), L(32), L(21), L(2.5), L(4)),
          box(x, y, X(50), Y(40), L(28), L(17)) * 0.2,
          stroke(x, y, X(12), Y(68), X(88), Y(68), L(5)), stroke(x, y, X(18), Y(63), X(82), Y(63), L(3)))
        break
      case 'headphones':
        d = max(ring(x, y, X(50), Y(52), L(30), L(5)) * (y < Y(56) ? 1 : 0),
          box(x, y, X(20), Y(62), L(7), L(13), L(4)), box(x, y, X(80), Y(62), L(7), L(13), L(4)))
        break
      case 'washer':
        d = max(frame(x, y, X(50), Y(50), L(30), L(36), L(4), L(4)),
          ring(x, y, X(50), Y(56), L(17), L(5)), disc(x, y, X(50), Y(56), L(10)) * 0.25,
          stroke(x, y, X(24), Y(24), X(76), Y(24), L(3)), disc(x, y, X(66), Y(19), L(2.5)))
        break
      case 'car':
        d = max(box(x, y, X(50), Y(56), L(42), L(10), L(6)),
          stroke(x, y, X(28), Y(46), X(38), Y(32), L(4)), stroke(x, y, X(38), Y(32), X(64), Y(32), L(4)),
          stroke(x, y, X(64), Y(32), X(74), Y(46), L(4)),
          disc(x, y, X(28), Y(67), L(8)), disc(x, y, X(72), Y(67), L(8)))
        break
      case 'screen':
        d = max(frame(x, y, X(50), Y(42), L(40), L(25), L(2), L(4)), box(x, y, X(50), Y(42), L(36), L(21)) * 0.18,
          stroke(x, y, X(50), Y(67), X(50), Y(76), L(5)), stroke(x, y, X(36), Y(78), X(64), Y(78), L(4)))
        break
      case 'watch':
        d = max(frame(x, y, X(50), Y(50), L(17), L(19), L(6), L(5)),
          box(x, y, X(50), Y(22), L(11), L(10)) * 0.8, box(x, y, X(50), Y(78), L(11), L(10)) * 0.8,
          stroke(x, y, X(50), Y(50), X(50), Y(42), L(2.5)), stroke(x, y, X(50), Y(50), X(57), Y(50), L(2.5)))
        break
      default:
        d = max(stroke(x, y, X(50), Y(26), X(76), Y(38), L(4)), stroke(x, y, X(76), Y(38), X(50), Y(50), L(4)),
          stroke(x, y, X(50), Y(50), X(24), Y(38), L(4)), stroke(x, y, X(24), Y(38), X(50), Y(26), L(4)),
          stroke(x, y, X(24), Y(38), X(24), Y(64), L(4)), stroke(x, y, X(76), Y(38), X(76), Y(64), L(4)),
          stroke(x, y, X(50), Y(50), X(50), Y(78), L(4)), stroke(x, y, X(24), Y(64), X(50), Y(78), L(4)),
          stroke(x, y, X(76), Y(64), X(50), Y(78), L(4)))
    }
    return 0.03 + Math.max(d, halo)
  } }
}

/**
 * A closed vocabulary of generic product words, in English and Turkish. No
 * makes and no models: a word that names one product is catalogue data, and
 * this is only which outline to draw. An unknown product gets a plain box, so
 * a picture never claims a kind the text did not say.
 */
const KINDS: [Kind, RegExp][] = [
  ['keyboard', /keyboard|keycap|klavye/i],
  ['headphones', /headphone|headset|earbud|earphone|kulaklık/i],
  ['laptop', /laptop|notebook|dizüstü/i],
  ['screen', /monitor|display|\btv\b|television|televizyon/i],
  ['phone', /phone|telefon|tablet/i],
  ['watch', /watch|saat/i],
  ['washer', /washer|washing[- ]machine|dryer|dishwasher|çamaşır|bulaşık/i],
  ['bike', /\bbikes?\b|bicycle|scooter|bisiklet/i],
  ['car', /\bcars?\b|vehicle|sedan|hatchback|araba|otomobil/i],
]

export function kindFor(...parts: (string | undefined | null)[]): Kind {
  const text = parts.filter(Boolean).join(' ')
  return KINDS.find(([, words]) => words.test(text))?.[0] ?? 'box'
}

/* ------------------------------------------------------------- engine -- */

const GRID = 96 // sample columns; rows follow the field's aspect

export type DustOptions = { count: number; seed?: number }

export class Dust {
  readonly count: number
  w = 1
  h = 1
  x: Float32Array
  y: Float32Array
  vx: Float32Array
  vy: Float32Array
  tx: Float32Array
  ty: Float32Array
  bright: Float32Array
  phase: Float32Array
  private random: () => number
  private scene: Scene | null = null

  constructor({ count, seed = 7 }: DustOptions) {
    this.count = count
    this.random = rng(seed)
    this.x = new Float32Array(count)
    this.y = new Float32Array(count)
    this.vx = new Float32Array(count)
    this.vy = new Float32Array(count)
    this.tx = new Float32Array(count)
    this.ty = new Float32Array(count)
    this.bright = new Float32Array(count)
    this.phase = new Float32Array(count)
    for (let i = 0; i < count; i++) {
      this.bright[i] = 0.35 + 0.65 * this.random()
      this.phase[i] = this.random() * 1000
    }
  }

  /** A new size keeps the cloud where it is, scaled, and resamples the scene for it. */
  resize(w: number, h: number) {
    const sx = w / this.w
    const sy = h / this.h
    for (let i = 0; i < this.count; i++) {
      this.x[i] *= sx
      this.y[i] *= sy
    }
    this.w = Math.max(1, w)
    this.h = Math.max(1, h)
    if (this.scene) this.target(this.scene)
  }

  /** Draw the scene's density into targets. Squaring the density keeps edges crisp. */
  private target(scene: Scene) {
    const cols = GRID
    const rows = Math.max(1, Math.round((GRID * this.h) / this.w))
    const cw = this.w / cols
    const ch = this.h / rows
    const cdf = new Float32Array(cols * rows)
    let sum = 0
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const v = clamp01(scene.density((c + 0.5) * cw, (r + 0.5) * ch, this.w, this.h))
        sum += v * v
        cdf[r * cols + c] = sum
      }
    }
    for (let i = 0; i < this.count; i++) {
      const want = this.random() * sum
      let lo = 0
      let hi = cdf.length - 1
      while (lo < hi) {
        const mid = (lo + hi) >> 1
        if (cdf[mid] < want) lo = mid + 1
        else hi = mid
      }
      this.tx[i] = ((lo % cols) + this.random()) * cw
      this.ty[i] = (Math.floor(lo / cols) + this.random()) * ch
    }
  }

  /**
   * Move to a scene. `scatter` throws the grains outward first, so they fly in
   * rather than slide; `settle` places them on their targets at once (for a
   * first frame, or when motion is off).
   */
  show(scene: Scene, { scatter = 1, settle = false }: { scatter?: number; settle?: boolean } = {}) {
    this.scene = scene
    this.target(scene)
    for (let i = 0; i < this.count; i++) {
      if (settle) {
        this.x[i] = this.tx[i]
        this.y[i] = this.ty[i]
        this.vx[i] = 0
        this.vy[i] = 0
      } else if (scatter > 0) {
        const a = this.random() * Math.PI * 2
        const v = (2 + this.random() * 6) * scatter
        this.vx[i] += Math.cos(a) * v
        this.vy[i] += Math.sin(a) * v
      }
    }
  }

  /** Throw the grains near a point outward, as when a button is pressed. */
  burst(x: number, y: number, r = 120, force = 9) {
    for (let i = 0; i < this.count; i++) {
      const dx = this.x[i] - x
      const dy = this.y[i] - y
      const d = Math.hypot(dx, dy) || 1
      if (d < r) {
        const f = ((r - d) / r) * force
        this.vx[i] += (dx / d) * f
        this.vy[i] += (dy / d) * f
      }
    }
  }

  /**
   * One frame. `dt` is in sixtieths of a second, so a slow device takes bigger
   * steps rather than slower ones. Calm moves at a third of the drift and never
   * shimmers; still does not move at all.
   */
  step(dt: number, t: number, motion: Motion = 'full') {
    if (motion === 'still') return
    const calm = motion === 'calm'
    const k = Math.min(dt, 3)
    const pull = (calm ? 0.012 : 0.02) * k
    const drift = (calm ? 0.02 : 0.06) * k
    const tempo = calm ? 0.4 : 1
    const damp = Math.pow(0.86, k)
    for (let i = 0; i < this.count; i++) {
      const s = this.phase[i]
      let vx = this.vx[i] + (this.tx[i] - this.x[i]) * pull + Math.sin(this.y[i] * 0.021 + t * 0.35 * tempo + s) * drift
      let vy = this.vy[i] + (this.ty[i] - this.y[i]) * pull + Math.cos(this.x[i] * 0.018 - t * 0.3 * tempo + s * 1.3) * drift
      vx *= damp
      vy *= damp
      this.vx[i] = vx
      this.vy[i] = vy
      this.x[i] += vx * k
      this.y[i] += vy * k
    }
  }

  /**
   * The grains sorted into `bins` brightness steps, ready to draw: for each bin
   * the number of grains and their coordinates packed x, y, x, y. `shimmer`
   * re-rolls every grain's brightness a little each frame, which is what makes
   * still dust read as alive; `band` lights a horizontal stripe at `band.y`.
   */
  sort(
    out: { counts: Int32Array; points: Float32Array[] },
    { shimmer = true, band }: { shimmer?: boolean; band?: { y: number; width: number } } = {},
  ) {
    const bins = out.counts.length
    out.counts.fill(0)
    for (let i = 0; i < this.count; i++) {
      let a = this.bright[i] * (shimmer ? 0.45 + 0.55 * this.random() : 1)
      if (band) {
        const d = (this.y[i] - band.y) / band.width
        a *= 0.18 + 1.7 * Math.exp(-d * d) + (this.y[i] < band.y ? 0.25 : 0)
      }
      const b = Math.min(bins - 1, Math.floor(a * bins))
      const n = out.counts[b]
      const bucket = out.points[b]
      bucket[n * 2] = this.x[i]
      bucket[n * 2 + 1] = this.y[i]
      out.counts[b] = n + 1
    }
  }

  /** Buffers for `sort`, sized so any bin can hold every grain. */
  buffers(bins = 10) {
    return {
      counts: new Int32Array(bins),
      points: Array.from({ length: bins }, () => new Float32Array(this.count * 2)),
    }
  }
}

/** How many grains a field of this size carries: one per `per` square pixels, capped. */
export function grainsFor(w: number, h: number, per = 12, cap = 26000): number {
  return Math.max(400, Math.min(cap, Math.round((w * h) / per)))
}

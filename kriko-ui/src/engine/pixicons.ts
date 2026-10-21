/** The agent marks, drawn on a 16 by 16 grid of small square cells.
 *
 *  The logo is a heavy monoline with mitred corners and 45 degree diagonals, a
 *  thin scan line, and one small square where the line ends. The icons keep all
 *  of that: strokes are two cells thick, which at this resolution is a fine line, corners are chamfered one step at a
 *  time, and each icon carries one signature cell (`o`) where the scan line of
 *  the logo ends. A lit cell is `#`, an empty one is a space.
 *
 *  They are drawn by rule, not typed out, so a stroke cannot come out one cell
 *  thick by accident and a new icon is a few lines. */

export const SIZE = 16

type Grid = string[][]

const blank = (): Grid => Array.from({ length: SIZE }, () => Array.from({ length: SIZE }, () => ' '))

function put(g: Grid, x: number, y: number, ch: string) {
  if (x >= 0 && y >= 0 && x < SIZE && y < SIZE) g[y][x] = ch
}

function rect(g: Grid, x: number, y: number, w: number, h: number, ch = '#') {
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) put(g, x + i, y + j, ch)
}

/** Whether a cell is inside a rectangle whose four corners are cut by `c` steps. */
function inside(px: number, py: number, x: number, y: number, w: number, h: number, c: number): boolean {
  const dx = px - x
  const dy = py - y
  if (dx < 0 || dy < 0 || dx >= w || dy >= h) return false
  const ex = Math.min(dx, w - 1 - dx)
  const ey = Math.min(dy, h - 1 - dy)
  return ex + ey >= c
}

/** A chamfered outline, two cells thick unless said otherwise. */
function ring(g: Grid, x: number, y: number, w: number, h: number, c = 1, t = 2) {
  for (let py = y; py < y + h; py++) {
    for (let px = x; px < x + w; px++) {
      if (inside(px, py, x, y, w, h, c) && !inside(px, py, x + t, y + t, w - 2 * t, h - 2 * t, Math.max(0, c - 1))) put(g, px, py, '#')
    }
  }
}

/** A 45 degree stroke two cells thick, starting at (x, y), `len` cells long. */
function diag(g: Grid, x: number, y: number, dx: 1 | -1, dy: 1 | -1, len: number) {
  for (let i = 0; i < len; i++) {
    put(g, x + dx * i, y + dy * i, '#')
    put(g, x + dx * i + 1, y + dy * i, '#')
  }
}

const SIGNATURE = 'o'

type Maker = (g: Grid) => void

const MAKERS: Record<string, Maker> = {
  /** Claude Code: eight spokes round a core. */
  burst: (g) => {
    rect(g, 7, 0, 2, 16)
    rect(g, 0, 7, 16, 2)
    diag(g, 1, 1, 1, 1, 5)
    diag(g, 13, 1, -1, 1, 5)
    diag(g, 1, 14, 1, -1, 5)
    diag(g, 13, 14, -1, -1, 5)
    rect(g, 7, 7, 2, 2, SIGNATURE)
  },
  /** Codex: a prompt chevron and its cursor. */
  prompt: (g) => {
    diag(g, 1, 2, 1, 1, 6)
    diag(g, 1, 13, 1, -1, 6)
    rect(g, 9, 12, 4, 2)
    rect(g, 13, 12, 2, 2, SIGNATURE)
  },
  /** Antigravity: a peak, hollow, with its summit lit. */
  peak: (g) => {
    for (let y = 0; y < 16; y++) {
      const half = Math.floor(y / 2) + 1
      for (let x = 0; x < 16; x++) {
        const d = Math.abs(x - 7.5)
        const outer = d <= half
        const inner = y < 14 && d <= half - 2.5
        if (outer && !inner) put(g, x, y, '#')
      }
    }
    rect(g, 7, 0, 2, 2, SIGNATURE)
  },
  /** Mistral: an M with its centre lit. */
  blocks: (g) => {
    rect(g, 0, 1, 2, 14)
    rect(g, 14, 1, 2, 14)
    diag(g, 2, 2, 1, 1, 5)
    diag(g, 13, 2, -1, 1, 5)
    rect(g, 7, 7, 2, 2, SIGNATURE)
  },
  /** Cursor: an arrow up and to the left, its tip lit. */
  pointer: (g) => {
    rect(g, 0, 0, 10, 2)
    rect(g, 0, 0, 2, 10)
    diag(g, 2, 2, 1, 1, 13)
    rect(g, 0, 0, 2, 2, SIGNATURE)
  },
  /** A local model: a chip with pins and a lit core. */
  chip: (g) => {
    ring(g, 2, 2, 12, 12, 1)
    for (const at of [5, 10]) {
      rect(g, 0, at, 2, 1)
      rect(g, 14, at, 2, 1)
      rect(g, at, 0, 1, 2)
      rect(g, at, 14, 1, 2)
    }
    ring(g, 5, 5, 6, 6, 0, 1)
    rect(g, 7, 7, 2, 2, SIGNATURE)
  },
  /** The fallback agent: a four-point star. */
  spark: (g) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const dx = Math.abs(x - 7.5)
        const dy = Math.abs(y - 7.5)
        if (Math.min(dx, dy) <= 1 || dx + dy <= 4) put(g, x, y, '#')
      }
    }
    rect(g, 7, 7, 2, 2, SIGNATURE)
  },
}

export type PixIconName = keyof typeof MAKERS | string

export const PIX_NAMES = Object.keys(MAKERS)

const cache = new Map<string, string[]>()

/** The icon as sixteen strings of sixteen characters: `#` lit, `o` signature, space empty. */
export function draw(name: string): string[] {
  const kept = cache.get(name)
  if (kept) return kept
  const g = blank()
  ;(MAKERS[name] ?? MAKERS.spark)(g)
  const rows = g.map((row) => row.join(''))
  cache.set(name, rows)
  return rows
}

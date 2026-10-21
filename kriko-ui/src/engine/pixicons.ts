/** The icon set, drawn on a 12 by 12 grid of square cells.
 *
 *  The logo is a heavy monoline with mitred corners and 45 degree diagonals, a
 *  thin scan line, and one small square where the line ends. The icons keep all
 *  of that: strokes are two cells thick, corners are chamfered one step at a
 *  time, and each icon carries one signature cell (`o`) where the scan line of
 *  the logo ends. A lit cell is `#`, an empty one is a space.
 *
 *  They are drawn by rule, not typed out, so a stroke cannot come out one cell
 *  thick by accident and a new icon is a few lines. */

export const SIZE = 12

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
  /** A speech bubble with a scan line ending in the signature cell. */
  chat: (g) => {
    ring(g, 0, 0, 12, 9, 2)
    rect(g, 2, 9, 3, 1)
    rect(g, 2, 10, 2, 1)
    rect(g, 2, 11, 1, 1)
    rect(g, 3, 4, 5, 1)
    put(g, 8, 4, SIGNATURE)
  },
  /** Two panels with the scan line crossing between them. */
  compare: (g) => {
    ring(g, 0, 0, 5, 12, 1)
    ring(g, 7, 0, 5, 12, 1)
    rect(g, 5, 6, 2, 1, SIGNATURE)
  },
  /** Three bars getting shorter, the last one ending in the signature cell. */
  queue: (g) => {
    rect(g, 0, 1, 12, 2)
    rect(g, 0, 5, 8, 2)
    rect(g, 0, 9, 4, 2)
    rect(g, 5, 9, 1, 2, SIGNATURE)
  },
  /** A clock: an octagon ring and a hand that ends in the signature cell. */
  history: (g) => {
    ring(g, 0, 0, 12, 12, 4)
    rect(g, 5, 2, 2, 5)
    rect(g, 7, 6, 2, 1)
    put(g, 9, 6, SIGNATURE)
  },
  plus: (g) => {
    rect(g, 5, 0, 2, 12)
    rect(g, 0, 5, 12, 2)
    rect(g, 5, 5, 2, 2, SIGNATURE)
  },
  more: (g) => {
    rect(g, 0, 5, 2, 2)
    rect(g, 5, 5, 2, 2, SIGNATURE)
    rect(g, 10, 5, 2, 2)
  },
  /** Claude Code: eight spokes round a core. */
  burst: (g) => {
    rect(g, 5, 0, 2, 12)
    rect(g, 0, 5, 12, 2)
    diag(g, 1, 1, 1, 1, 4)
    diag(g, 9, 1, -1, 1, 4)
    diag(g, 1, 10, 1, -1, 4)
    diag(g, 9, 10, -1, -1, 4)
    rect(g, 5, 5, 2, 2, SIGNATURE)
  },
  /** Codex: a prompt chevron and the cursor. */
  prompt: (g) => {
    diag(g, 0, 1, 1, 1, 5)
    diag(g, 0, 9, 1, -1, 5)
    rect(g, 7, 9, 3, 2)
    rect(g, 10, 9, 2, 2, SIGNATURE)
  },
  /** Antigravity: a peak, hollow, with its summit lit. */
  peak: (g) => {
    for (let y = 0; y < 12; y++) {
      const half = Math.floor(y / 2) + 1
      for (let x = 0; x < 12; x++) {
        const d = Math.abs(x - 5.5)
        const outer = d <= half
        const inner = y < 10 && d <= half - 2.5
        if (outer && !inner) put(g, x, y, '#')
      }
    }
    rect(g, 5, 0, 2, 2, SIGNATURE)
  },
  /** Mistral: an M of square blocks. */
  blocks: (g) => {
    rect(g, 0, 1, 2, 10)
    rect(g, 10, 1, 2, 10)
    rect(g, 2, 2, 2, 2)
    rect(g, 8, 2, 2, 2)
    rect(g, 4, 4, 2, 2)
    rect(g, 6, 4, 2, 2)
    rect(g, 5, 6, 2, 2, SIGNATURE)
  },
  /** Cursor: an arrow up and to the left, its tip lit. */
  pointer: (g) => {
    rect(g, 0, 0, 7, 2)
    rect(g, 0, 0, 2, 7)
    diag(g, 2, 2, 1, 1, 9)
    rect(g, 0, 0, 2, 2, SIGNATURE)
  },
  /** A local model: a chip with pins and a lit core. */
  chip: (g) => {
    ring(g, 2, 2, 8, 8, 1)
    for (const at of [4, 7]) {
      rect(g, 0, at, 2, 1)
      rect(g, 10, at, 2, 1)
      rect(g, at, 0, 1, 2)
      rect(g, at, 10, 1, 2)
    }
    rect(g, 5, 5, 2, 2, SIGNATURE)
  },
  /** The fallback agent: a four-point star. */
  spark: (g) => {
    rect(g, 5, 0, 2, 3)
    rect(g, 5, 9, 2, 3)
    rect(g, 4, 3, 4, 2)
    rect(g, 4, 7, 4, 2)
    rect(g, 0, 5, 12, 2)
    rect(g, 5, 5, 2, 2, SIGNATURE)
  },
}

export type PixIconName = keyof typeof MAKERS | string

export const PIX_NAMES = Object.keys(MAKERS)

const cache = new Map<string, string[]>()

/** The icon as twelve strings of twelve characters: `#` lit, `o` signature, space empty. */
export function draw(name: string): string[] {
  const kept = cache.get(name)
  if (kept) return kept
  const g = blank()
  ;(MAKERS[name] ?? MAKERS.spark)(g)
  const rows = g.map((row) => row.join(''))
  cache.set(name, rows)
  return rows
}

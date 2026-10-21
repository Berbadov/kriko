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
}

/** The agent marks: nine rows of nine cells, `#` lit and `o` the signature square.
 *  Set by hand, the first design for them, and kept as a dot display: the empty
 *  cells stay as faint dots (`ui/PixIcon.tsx`). */
const AGENTS: Record<string, string[]> = {
  burst: ['....#....', '.#..#..#.', '..#.#.#..', '...#o#...', '#########', '...###...', '..#.#.#..', '.#..#..#.', '....#....'],
  prompt: ['.........', '.#.......', '..#......', '...#.....', '....#....', '...#.....', '..#......', '.#...###o', '.........'],
  peak: ['....o....', '...#.#...', '...#.#...', '..#...#..', '..#.#.#..', '.#.....#.', '.#.....#.', '#########', '.........'],
  blocks: ['#.......#', '##.....##', '#.#...#.#', '#..#.#..#', '#...o...#', '#.......#', '#.......#', '#.......#', '.........'],
  pointer: ['o........', '##.......', '#.#......', '#..#.....', '#...#....', '#....#...', '#..####..', '.#..#....', '..##.....'],
  chip: ['..#.#.#..', '.#######.', '.#.....#.', '##.###.##', '.#.#o#.#.', '##.###.##', '.#.....#.', '.#######.', '..#.#.#..'],
  spark: ['....#....', '....#....', '...###...', '..#####..', '#####o###', '..#####..', '...###...', '....#....', '....#....'],
}

const dots = (rows: string[]) => rows.map((row) => row.replaceAll('.', ' '))

export type PixIconName = keyof typeof MAKERS | string

export const NAV_NAMES = Object.keys(MAKERS)
export const AGENT_NAMES = Object.keys(AGENTS)
export const PIX_NAMES = [...NAV_NAMES, ...AGENT_NAMES]

/** Agent marks are dot displays; navigation icons are solid. An unknown name is a mark too. */
export const kindOf = (name: string): 'agent' | 'nav' => (name in MAKERS ? 'nav' : 'agent')

const cache = new Map<string, string[]>()

/** An icon as rows of cells: `#` lit, `o` signature, space empty. Navigation icons are
 *  twelve by twelve, agent marks nine by nine. An unknown name draws the fallback mark. */
export function draw(name: string): string[] {
  const kept = cache.get(name)
  if (kept) return kept
  if (name in AGENTS || !(name in MAKERS)) {
    const rows = dots(AGENTS[name] ?? AGENTS.spark)
    cache.set(name, rows)
    return rows
  }
  const g = blank()
  MAKERS[name](g)
  const rows = g.map((row) => row.join(''))
  cache.set(name, rows)
  return rows
}

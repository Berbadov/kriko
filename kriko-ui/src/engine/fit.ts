/** Whether a model fits this computer, and how fast an answer is. Pure: no
 *  fetch, no state, so a screen can show a verdict without asking the engine.
 *
 *  A verdict needs two facts: how big the model is and how much memory the
 *  computer reported. A fact that is missing makes the verdict "Fit unknown",
 *  never a guess. The size of a library model is estimated from the size in its
 *  name (the engine's list carries sizes as `7b`, not as bytes); an installed
 *  model has its real size, which is better, and is used when there is one. */

/** Memory the computer reported, in megabytes. `null` is "not reported". */
export interface Facts {
  vramMb: number | null
  ramMb: number | null
}

export type Fit = 'well' | 'slow' | 'big' | 'unknown'

/** What each verdict is called on the screen. */
export const FIT_WORDS: Record<Fit, string> = {
  well: 'Runs well',
  slow: 'Will be slow',
  big: 'Too big',
  unknown: 'Fit unknown',
}

/** One sentence under a verdict, so the word is never the whole explanation. */
export const FIT_NOTES: Record<Fit, string> = {
  well: 'Fits in memory with room to spare.',
  slow: 'Fits, but not on the graphics card, so answers come slowly.',
  big: 'Needs more memory than this computer has.',
  unknown: 'The size of the model or of this computer is not reported.',
}

/** Bytes a billion parameters take at 4 bits, the way Ollama stores a model by default. */
export const BYTES_PER_BILLION = 0.6e9
/** A model on the graphics card needs room beyond its file for the answer being written. */
export const VRAM_HEADROOM = 1.2
/** The same room, in system memory, when the model runs on the processor. */
export const RAM_HEADROOM = 1.2
/** With no graphics card reported the processor does all of it, so a model has to sit well inside memory to be bearable. */
export const RAM_HEADROOM_NO_GPU = 2

const MB = 1024 * 1024

/** The memory facts of a `/api/machine` answer. A card the engine reports without memory is no card. */
export function factsOf(machine: { gpu?: { vram_total_mb?: number | null } | null; ram_total_mb?: number | null } | null | undefined): Facts {
  const vram = machine?.gpu?.vram_total_mb
  const ram = machine?.ram_total_mb
  return {
    vramMb: typeof vram === 'number' && vram > 0 ? vram : null,
    ramMb: typeof ram === 'number' && ram > 0 ? ram : null,
  }
}

/** Billions of parameters from the size in a model's name: `7b`, `3.8b`,
 *  `8x7b` (every expert is held in memory, so it counts in full), `270m`. The
 *  largest figure in the name wins. `null` when the name carries none, and for
 *  an "effective size" tag such as `e2b`: the file holds more than the tag says
 *  (a model sold as e2b can be several gigabytes), so a guess from it would say
 *  a model fits when it does not. Fit is unknown there, and the list says so. */
export function parametersB(name: string): number | null {
  const found: number[] = []
  const pattern = /(?:^|[-_:/])(e?)(\d+(?:\.\d+)?)(?:x(\d+(?:\.\d+)?))?([bm])(?=$|[-_:])/gi
  for (const match of name.matchAll(pattern)) {
    if (match[1]) return null
    const first = Number(match[2])
    const count = match[3] ? first * Number(match[3]) : first
    found.push(match[4].toLowerCase() === 'm' ? count / 1000 : count)
  }
  return found.length ? Math.max(...found) : null
}

/** About how many bytes a model takes, from its name. `null` when the name has no size. */
export function estimateBytes(name: string): number | null {
  const billions = parametersB(name)
  return billions && billions > 0 ? billions * BYTES_PER_BILLION : null
}

/** The verdict for a model of `bytes` on a computer with `facts`. */
export function fitOf(bytes: number | null | undefined, facts: Facts): Fit {
  if (!bytes || bytes <= 0) return 'unknown'
  const { vramMb, ramMb } = facts
  if (vramMb !== null) {
    if (bytes * VRAM_HEADROOM <= vramMb * MB) return 'well'
    if (ramMb === null) return 'unknown'
    return bytes * RAM_HEADROOM <= ramMb * MB ? 'slow' : 'big'
  }
  if (ramMb === null) return 'unknown'
  if (bytes * RAM_HEADROOM_NO_GPU <= ramMb * MB) return 'well'
  return bytes * RAM_HEADROOM <= ramMb * MB ? 'slow' : 'big'
}

/** Roughly the largest model, in billions of parameters, that runs well here.
 *  `null` when the computer reported no memory at all. */
export function largestThatRunsWell(facts: Facts): number | null {
  const room = facts.vramMb !== null ? (facts.vramMb * MB) / VRAM_HEADROOM : facts.ramMb !== null ? (facts.ramMb * MB) / RAM_HEADROOM_NO_GPU : null
  return room === null ? null : Math.floor(room / BYTES_PER_BILLION)
}

/** A row of the engine's library list: a family and the sizes it comes in. */
export interface LibraryFamily {
  name: string
  sizes: string[]
  about: string
}

export interface FitRow {
  /** What is pulled: `family:size`, or the family alone when it lists no size. */
  name: string
  family: string
  size: string
  about: string
  bytes: number | null
  fit: Fit
}

const ORDER: Record<Fit, number> = { well: 0, slow: 1, unknown: 2, big: 3 }

/** Every size of every family as its own row with its verdict, what fits first.
 *  Within a verdict the engine's order stands (it is the library's own), and the
 *  sizes of one family go largest first. `recommended` is lifted to the top when
 *  it is not too big. A stable sort keeps the rest as read. */
export function fitRows(library: readonly LibraryFamily[], facts: Facts, recommended = ''): FitRow[] {
  const rows: FitRow[] = []
  for (const family of library) {
    const sizes = family.sizes.length ? family.sizes : ['']
    const own = sizes
      .map((size): FitRow => {
        const name = size ? `${family.name}:${size}` : family.name
        const bytes = size ? estimateBytes(name) : null
        return { name, family: family.name, size, about: family.about, bytes, fit: fitOf(bytes, facts) }
      })
      .sort((a, b) => (b.bytes ?? 0) - (a.bytes ?? 0))
    rows.push(...own)
  }
  const rank = (row: FitRow) => (recommended && isRecommended(row.name, recommended) && row.fit !== 'big' ? -1 : ORDER[row.fit])
  return rows.map((row, at) => ({ row, at })).sort((a, b) => rank(a.row) - rank(b.row) || a.at - b.at).map((one) => one.row)
}

/** The recommended model, or a quantisation of it (`name-it-q4_K_M`): the engine's own rule. */
export function isRecommended(name: string, recommended: string): boolean {
  if (!recommended) return false
  const folded = name.toLowerCase()
  const want = recommended.toLowerCase()
  return folded === want || folded.startsWith(`${want}-`)
}

/** Speed thresholds, in tokens per second. One place, so the words and any test agree. */
export const SPEED = { fast: 10, usable: 3 } as const

export interface SpeedWords {
  tone: 'ok' | 'warn' | 'risk'
  text: string
}

/** What a measured speed means for research. `null` speed (the server counted no tokens) says so. */
export function speedWords(tokensPerSecond: number | null | undefined): SpeedWords | null {
  if (tokensPerSecond === null || tokensPerSecond === undefined || !Number.isFinite(tokensPerSecond) || tokensPerSecond <= 0) return null
  const rate = tokensPerSecond >= 10 ? Math.round(tokensPerSecond) : Math.round(tokensPerSecond * 10) / 10
  const per = `${rate} ${rate === 1 ? 'token' : 'tokens'} per second`
  if (tokensPerSecond >= SPEED.fast) return { tone: 'ok', text: `${per}: fast enough for research` }
  if (tokensPerSecond >= SPEED.usable) return { tone: 'warn', text: `${per}: usable, research runs will take a while` }
  return { tone: 'risk', text: `${per}: slow, expect long research runs` }
}

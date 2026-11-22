import { ORDER, routeFor, showDrawer, type Screen } from './drawerEvents'
import { SETTINGS_PAGES, showSettingsPage, type SettingsPage } from './panels/settingsPages'
import type { IconName } from './Icon'

/** The command palette's items: what can be reached, how it is found, and what
 *  running it does. Pure data and pure matching, so the palette and its tests
 *  share one list. Navigation goes only through the public seams listed here. */

export type PaletteGroup = 'Go to' | 'Actions' | 'Settings' | 'Recent checks' | 'Estimates'

/** The order groups take with an empty query, and the tie-break when a query
 *  leaves several matches equally good. */
export const GROUP_ORDER: readonly PaletteGroup[] = ['Go to', 'Actions', 'Settings', 'Recent checks', 'Estimates']

/** Actions the palette cannot do itself. The shell listens for `kriko:palette-action`. */
export type PaletteAction = 'new-chat' | 'take-tour' | 'check-a-list' | 'new-estimate'

export interface PaletteSeams {
  navigate(screen: Screen): void
  showDrawer(panel: string | null): void
  showSettingsPage(page: SettingsPage): void
  action(id: PaletteAction): void
  openProduct(lookupId: string): void
  openEstimate(estimateId: string): void
}

export interface PaletteItem {
  id: string
  group: PaletteGroup
  title: string
  /** The keyboard shortcut that does the same, when there is one. */
  hint?: string
  keywords: string[]
  icon: IconName
  run: (seams: PaletteSeams) => void
}

/** The data the items are built from. The palette reads it from the hooks. */
export interface PaletteData {
  recent: { id: string; name: string; category?: string }[]
  estimates: { estimate_id: string; name: string }[]
}

const RECENT_LIMIT = 8

/** The event that opens the palette. Ctrl+Shift+P sends it too; a button calls `openCommandPalette`. */
export const OPEN_EVENT = 'kriko:palette-open'

/** Asks the palette to open. The palette mounts once and listens for this. */
export function openCommandPalette(): void {
  window.dispatchEvent(new Event(OPEN_EVENT))
}

const emit = (name: string, detail: unknown) => window.dispatchEvent(new CustomEvent(name, { detail }))

/** The seams the live palette runs through. */
export const liveSeams: PaletteSeams = {
  navigate: (screen) => emit('kriko:navigate', { screen }),
  showDrawer,
  showSettingsPage,
  action: (id) => emit('kriko:palette-action', { id }),
  openProduct: (lookupId) => emit('kriko:open-product', { lookupId }),
  openEstimate: (estimateId) => emit('kriko:open-estimate', { estimateId }),
}

const PLACES: { id: string; title: string; screen: Screen; panel?: string; icon: IconName; keywords: string[] }[] = [
  { id: 'chat', title: 'Ask', screen: 'chat', icon: 'chat', keywords: ['chat', 'question', 'agent', 'assistant'] },
  { id: 'compare', title: 'Compare', screen: 'compare', icon: 'compare', keywords: ['side by side', 'products'] },
  { id: 'queue', title: 'Queue', screen: 'queue', icon: 'queue', keywords: ['jobs', 'running', 'waiting'] },
  { id: 'history', title: 'History', screen: 'history', panel: 'history', icon: 'clock', keywords: ['checks', 'past', 'saved'] },
  { id: 'estimate', title: 'Procurement', screen: 'estimate', icon: 'gauge', keywords: ['estimate', 'quotes', 'vat', 'landed cost', 'buy'] },
  { id: 'prices', title: 'Prices', screen: 'prices', icon: 'coins', keywords: ['price', 'quote', 'watch'] },
  { id: 'catalogs', title: 'Catalogs', screen: 'catalogs', panel: 'browse', icon: 'book', keywords: ['catalog', 'packs', 'install', 'browse'] },
  { id: 'sites', title: 'Sites', screen: 'sites', panel: 'sites', icon: 'globe', keywords: ['listing sites', 'extension'] },
  { id: 'foryou', title: 'For you', screen: 'foryou', panel: 'foryou', icon: 'star', keywords: ['recommended', 'suggestions'] },
  { id: 'settings', title: 'Settings', screen: 'settings', panel: 'settings', icon: 'gear', keywords: ['preferences', 'options'] },
]

const ACTIONS: { id: PaletteAction; title: string; icon: IconName; keywords: string[] }[] = [
  { id: 'new-chat', title: 'New chat', icon: 'plus', keywords: ['ask', 'conversation', 'start'] },
  { id: 'take-tour', title: 'Take the tour', icon: 'compass', keywords: ['help', 'walkthrough', 'guide', 'learn'] },
  { id: 'check-a-list', title: 'Check a list of products', icon: 'search', keywords: ['spreadsheet', 'csv', 'excel', 'batch', 'many'] },
  { id: 'new-estimate', title: 'New estimate', icon: 'docplus', keywords: ['procurement', 'quote', 'buy'] },
]

/** Words a reader might type for each Settings section. Typed out in full, so a
 *  new section is a compile error here until it has words. */
const SECTION_WORDS: Record<SettingsPage, string[]> = {
  general: ['looks', 'theme', 'paper', 'dark', 'appearance', 'findings'],
  research: ['agent', 'sources', 'thoroughness', 'checks'],
  keys: ['api key', 'model', 'provider'],
  local: ['local ai', 'local models', 'ollama', 'gpu', 'vram', 'offline', 'private', 'try the model'],
  connections: ['extension', 'browser', 'mcp', 'access code', 'chat clients'],
  usage: ['spend', 'cost', 'limits', 'budget'],
  data: ['backup', 'updates', 'logs', 'report', 'export', 'folder'],
}

/** The keyboard hint for a screen: Ctrl+1 to Ctrl+4 are the places in `ORDER`. */
function hintFor(screen: Screen): string | undefined {
  const at = ORDER.indexOf(screen)
  if (at >= 0) return `Ctrl+${at + 1}`
  if (screen === 'settings') return 'Ctrl+,'
  return undefined
}

/** Every item the palette can run, in group order. Recent checks and estimates
 *  come from the reader's data and are capped here. */
export function buildItems(data: PaletteData): PaletteItem[] {
  const items: PaletteItem[] = []

  for (const place of PLACES) {
    items.push({
      id: `go:${place.id}`,
      group: 'Go to',
      title: place.title,
      hint: hintFor(place.screen),
      keywords: place.keywords,
      icon: place.icon,
      // A place the shell names by panel goes through `showDrawer`; the rest are screens.
      run: (seams) => (place.panel && routeFor(place.panel)?.screen === place.screen ? seams.showDrawer(place.panel) : seams.navigate(place.screen)),
    })
  }

  for (const action of ACTIONS) {
    items.push({
      id: `action:${action.id}`,
      group: 'Actions',
      title: action.title,
      keywords: action.keywords,
      icon: action.icon,
      run: (seams) => seams.action(action.id),
    })
  }

  for (const page of SETTINGS_PAGES) {
    items.push({
      id: `settings:${page.value}`,
      group: 'Settings',
      title: `Settings: ${page.label}`,
      keywords: SECTION_WORDS[page.value],
      icon: 'gear',
      // The page is set first, so a Settings screen that mounts on this navigation takes it.
      run: (seams) => {
        seams.showSettingsPage(page.value)
        seams.navigate('settings')
      },
    })
  }

  for (const row of data.recent.slice(0, RECENT_LIMIT)) {
    items.push({
      id: `check:${row.id}`,
      group: 'Recent checks',
      title: row.name || 'Untitled check',
      keywords: row.category ? [row.category] : [],
      icon: 'cube',
      run: (seams) => seams.openProduct(row.id),
    })
  }

  for (const estimate of data.estimates) {
    items.push({
      id: `estimate:${estimate.estimate_id}`,
      group: 'Estimates',
      title: estimate.name || 'Untitled estimate',
      keywords: ['estimate', 'procurement'],
      icon: 'folder',
      run: (seams) => {
        seams.navigate('estimate')
        seams.openEstimate(estimate.estimate_id)
      },
    })
  }

  return items
}

/* ---- Matching ----------------------------------------------------------- */

/** Lower case with diacritics removed, and for each folded character the index
 *  of the character it came from, so a match can be shown in the original text. */
interface Folded {
  text: string
  map: number[]
}

function fold(input: string): Folded {
  let text = ''
  const map: number[] = []
  let at = 0
  for (const ch of input) {
    const plain = ch.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
    for (let k = 0; k < plain.length; k++) map.push(at)
    text += plain
    at += ch.length
  }
  return { text, map }
}

interface Word {
  text: string
  start: number
}

function wordsOf(text: string): Word[] {
  return [...text.matchAll(/[\p{L}\p{N}]+/gu)].map((m) => ({ text: m[0], start: m.index ?? 0 }))
}

/** The indexes of `word`'s letters taken in order from `text`, or null when they do not occur in order. */
function subsequence(word: string, text: string): number[] | null {
  const at: number[] = []
  let j = 0
  for (let i = 0; i < text.length && j < word.length; i++) {
    if (text[i] === word[j]) {
      at.push(i)
      j++
    }
  }
  return j === word.length ? at : null
}

/** How well one query word matches: 3 a word of the title starts with it, 2 a
 *  keyword does, 1 its letters occur in order inside one word of the title or a
 *  keyword. A subsequence never spans two words, or "pri" would find "help" and
 *  "guide". Marks are folded indexes in the title. */
function matchWord(word: string, titleWords: Word[], keywordWords: Word[]): { tier: number; marks: number[] } | null {
  const prefix = titleWords.find((w) => w.text.startsWith(word))
  if (prefix) return { tier: 3, marks: Array.from({ length: word.length }, (_, k) => prefix.start + k) }
  if (keywordWords.some((w) => w.text.startsWith(word))) return { tier: 2, marks: [] }
  for (const w of titleWords) {
    const at = subsequence(word, w.text)
    if (at) return { tier: 1, marks: at.map((i) => w.start + i) }
  }
  if (keywordWords.some((w) => subsequence(word, w.text))) return { tier: 1, marks: [] }
  return null
}

export interface PaletteMatch {
  item: PaletteItem
  /** Indexes into `item.title` to show as matched. */
  marks: number[]
}

/** Every item the query finds, best first. All query words must match. The
 *  item's score is its weakest word, so a prefix match ranks above a
 *  keyword match, which ranks above a scattered one. Equal scores keep the
 *  group order, then the order given. An empty query keeps every item. */
export function filterItems(items: readonly PaletteItem[], query: string): PaletteMatch[] {
  const words = wordsOf(fold(query).text).map((w) => w.text)
  const found: { match: PaletteMatch; tier: number; rank: number; index: number }[] = []

  items.forEach((item, index) => {
    if (!words.length) {
      found.push({ match: { item, marks: [] }, tier: 3, rank: GROUP_ORDER.indexOf(item.group), index })
      return
    }
    const title = fold(item.title)
    const titleWords = wordsOf(title.text)
    const keywordWords = wordsOf(fold(item.keywords.join(' ')).text)
    let tier = 3
    const marks = new Set<number>()
    for (const word of words) {
      const hit = matchWord(word, titleWords, keywordWords)
      if (!hit) return
      tier = Math.min(tier, hit.tier)
      for (const at of hit.marks) marks.add(title.map[at])
    }
    found.push({ match: { item, marks: [...marks].sort((a, b) => a - b) }, tier, rank: GROUP_ORDER.indexOf(item.group), index })
  })

  found.sort((a, b) => b.tier - a.tier || a.rank - b.rank || a.index - b.index)
  return found.map((row) => row.match)
}

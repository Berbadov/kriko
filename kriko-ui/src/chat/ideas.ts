import type { ChatMode } from '../activity/run'

/** One prompt the home offers under the box: what to ask, and the icon beside it. */
export interface Idea {
  text: string
  icon: 'search' | 'swap' | 'book' | 'compare' | 'coins' | 'alert'
}

/** A product's name as a reader would type it: the part before a listing's " : " or " | ", kept short. */
export function shortName(label: string): string {
  const head = label.split(/\s[:|–-]\s/)[0].trim()
  if (head.length <= 44) return head
  const cut = head.slice(0, 44)
  return cut.slice(0, cut.lastIndexOf(' ') > 20 ? cut.lastIndexOf(' ') : 44).trim()
}

/** Fresh prompts for the chosen mode, built from what the reader checked before,
 *  so the list is about their products rather than a fixed demo. With nothing
 *  checked yet it falls back to prompts that show what each mode does. */
export function ideasFor(mode: ChatMode, recentNames: string[]): Idea[] {
  // A product name carries a model, size or year (a word with a digit); a shop's
  // page title ("find the cheapest!") does not, and makes a poor prompt.
  const names = [...new Set(recentNames.map(shortName).filter((name) => /\p{L}*\d/u.test(name)))]
  const [a, b] = names
  const out: Idea[] = []
  if (mode === 'alternatives') {
    if (a) out.push({ text: `Alternatives to ${a}`, icon: 'swap' })
    if (b) out.push({ text: `Something like ${b}, but cheaper`, icon: 'coins' })
    out.push({ text: 'A quieter alternative to my robot vacuum', icon: 'swap' })
  } else if (mode === 'research') {
    if (a) out.push({ text: `What goes wrong with ${a}?`, icon: 'alert' })
    if (b) out.push({ text: `Is ${b} worth it? Reviews and specs`, icon: 'book' })
    out.push({ text: 'What should I check before buying a used car?', icon: 'book' })
  } else {
    if (a && b) out.push({ text: `Compare ${a} with ${b}`, icon: 'compare' })
    if (a) out.push({ text: `Find the best price for ${a}`, icon: 'coins' })
    out.push({ text: 'A phone for my father, easy to use, under 20,000 TL', icon: 'search' })
    out.push({ text: 'A 27" 2K monitor for gaming and work', icon: 'search' })
  }
  return out.slice(0, 3)
}

/** A compare suggestion for after an answer: the first two products it showed. */
export function compareIdea(labels: string[]): string | null {
  const names = [...new Set(labels.map(shortName).filter(Boolean))]
  return names.length >= 2 ? `Compare ${names[0]} with ${names[1]}` : null
}

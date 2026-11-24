import type { Risk } from '../compare/checks'

/** Before you buy used: a calm card on a secondhand listing, drawn only from the
 *  check the reader is already looking at. No new fetch, no model knowledge.
 *
 *  Three lists, and each item says where it came from: an inspection cue is
 *  mapped from a finding, a question names the identity field or variant the
 *  engine recorded, and a money line is a quote the finding already carries.
 *  When a finding maps to no cue, its own words are shown rather than advice
 *  invented for it. */

export interface Market {
  name: string
  /** Hosts this rule owns; a subdomain (`berlin.craigslist.org`) matches too. */
  hosts: string[]
  /** A path prefix that must also match, for a marketplace inside a general site. */
  path?: string
}

/** Data-driven on purpose: a new marketplace is one row, not a new branch. */
export const SECONDHAND_MARKETS: Market[] = [
  { name: 'Sahibinden', hosts: ['sahibinden.com'] },
  { name: 'Dolap', hosts: ['dolap.com'] },
  { name: 'Letgo', hosts: ['letgo.com'] },
  { name: 'Facebook Marketplace', hosts: ['facebook.com'], path: '/marketplace' },
  {
    name: 'eBay',
    hosts: ['ebay.com', 'ebay.co.uk', 'ebay.de', 'ebay.fr', 'ebay.it', 'ebay.es', 'ebay.nl',
      'ebay.be', 'ebay.at', 'ebay.ch', 'ebay.com.au', 'ebay.ca'],
  },
  { name: 'Craigslist', hosts: ['craigslist.org'] },
  { name: 'Kleinanzeigen', hosts: ['kleinanzeigen.de'] },
  { name: 'Subito', hosts: ['subito.it'] },
  { name: 'leboncoin', hosts: ['leboncoin.fr'] },
  { name: 'Marktplaats', hosts: ['marktplaats.nl'] },
]

function parsed(raw: string): URL | null {
  try {
    return new URL(/^[a-z]+:\/\//i.test(raw) ? raw : `https://${raw}`)
  } catch {
    return null
  }
}

/** The marketplace a listing address belongs to, or null for a new-product page. */
export function secondhandMarket(url: string): Market | null {
  const parts = parsed(url.trim())
  if (!parts) return null
  const host = parts.hostname.toLowerCase().replace(/^www\./, '')
  const path = parts.pathname.toLowerCase()
  for (const market of SECONDHAND_MARKETS) {
    const hostMatches = market.hosts.some((one) => host === one || host.endsWith(`.${one}`))
    const pathMatches = !market.path || path === market.path || path.startsWith(`${market.path}/`)
    if (hostMatches && pathMatches) return market
  }
  return null
}

/** A physical check a finding asks for, in the reader's hands. */
interface Cue {
  words: string[]
  text: string
}

const INSPECTION: Cue[] = [
  { words: ['hinge'], text: 'Open and close the hinge through its full range; listen for a crack or a stiff spot.' },
  { words: ['battery'], text: 'Check the battery health screen, or charge it and watch how fast it drains.' },
  { words: ['seal', 'gasket'], text: 'Look for a dried, split or seated-wrong seal, and ask whether it has ever leaked.' },
  { words: ['leak', 'leaked', 'leaking'], text: 'Dry it, fill or run it, and look for a fresh leak at the joints.' },
  { words: ['screen', 'display', 'pixel'], text: 'Show a white and a black screen; look for dead pixels, scratches and burn-in.' },
  { words: ['keyboard', 'keycap'], text: 'Press every key, including the corners, and check that each one springs back.' },
  { words: ['port', 'connector', 'usb'], text: 'Test every port with a cable known to work, and check that each one charges or connects.' },
  { words: ['fan', 'rattle', 'noise'], text: 'Run it for ten minutes and listen for a rattle, a whine, or a fan that never settles.' },
  { words: ['overheat', 'overheating', 'overheats', 'heat'], text: 'Run it under load for ten minutes and feel where the heat gathers.' },
  { words: ['motor', 'engine', 'compressor', 'pump'], text: 'Ask for a cold start and listen for a knock or a whine before it warms up.' },
  { words: ['brake', 'tyre', 'tire', 'tread'], text: 'Measure the tread and ask when the brakes were last serviced.' },
]

export interface UsedItem {
  /** The sentence the card shows. */
  text: string
  /** The finding, identity field or variant it came from. */
  from: string
}

export interface UsedCard {
  market: Market
  inspect: UsedItem[]
  ask: UsedItem[]
  leverage: UsedItem[]
}

export interface UsedCardInput {
  url: string
  name: string
  risks: Risk[]
  /** The identity fields the adapter read off the listing. */
  identity?: Record<string, unknown>
  /** The variant the check assumed, when it recorded one. */
  assumed?: string
  /** Labels of the subjects the listing resolved to. */
  subjects?: string[]
}

const LEVEL_RANK: Record<Risk['level'], number> = { critical: 4, high: 3, medium: 2, low: 1, unrated: 0 }
const MAX_EACH = 4

const fold = (text: string) => text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
const word = (text: string, needle: string) =>
  new RegExp(`(^|\\s)${needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(\\s|$)`).test(text)

function findingsInOrder(risks: Risk[]): Risk[] {
  return [...risks].sort((a, b) => LEVEL_RANK[b.level] - LEVEL_RANK[a.level])
}

function inspectList(risks: Risk[]): UsedItem[] {
  const out: UsedItem[] = []
  const seen = new Set<string>()
  for (const risk of findingsInOrder(risks)) {
    if (out.length >= MAX_EACH) break
    const words = fold(`${risk.title} ${risk.body} ${risk.advice ?? ''}`)
    const cue = INSPECTION.find((one) => one.words.some((word_) => word(words, word_)))
    const own = (risk.advice ?? '').trim() || risk.title.trim()
    const text = (cue?.text ?? own).trim()
    if (!text || seen.has(text)) continue
    seen.add(text)
    out.push({ text, from: risk.title.trim() })
  }
  return out
}

function identityFields(identity: Record<string, unknown> | undefined): [string, string][] {
  const out: [string, string][] = []
  for (const [key, value] of Object.entries(identity ?? {})) {
    if (typeof value !== 'string' && typeof value !== 'number') continue
    const text = String(value).trim()
    if (text) out.push([key, text])
  }
  return out
}

function askList(check: UsedCardInput, identity: [string, string][]): UsedItem[] {
  const out: UsedItem[] = []
  const seen = new Set<string>()
  const add = (text: string, from: string) => {
    const line = text.trim()
    if (!line || seen.has(line) || out.length >= MAX_EACH) return
    seen.add(line)
    out.push({ text: line, from })
  }
  let namedModel = false
  for (const [key, value] of identity) {
    const words = fold(key)
    const label = key.replaceAll('_', ' ').trim()
    if (/(serial|batch|vin|imei|chassis)/.test(words)) {
      add(`Ask for the ${label} and a photo of the label that carries it.`, label)
    } else if (/\bmodel\b/.test(words)) {
      namedModel = true
      add(`Ask the seller to read the model number off the ${check.name} itself, not from the listing.`, label)
    } else if (/\b(year|date)\b/.test(words)) {
      add('Ask when it was first used, and for the date on the receipt.', label)
    } else {
      add(`Ask the seller to confirm the ${label} is "${value}", shown in a photo.`, label)
    }
  }
  const assumed = (check.assumed ?? '').trim()
  if (assumed) add(`Ask which exact version this is: ${assumed}.`, 'variant assumption')
  const subjects = (check.subjects ?? []).map((one) => one.trim()).filter(Boolean)
  if (!namedModel && !identity.some(([key]) => /(serial|batch|vin|imei|chassis)/.test(fold(key)))) {
    const of = subjects.length ? `${check.name} (${subjects.join(', ')})` : check.name
    add(`Ask for the serial or model number of the ${of} and a photo of the label.`, subjects.length ? 'recognition' : 'the listing')
  }
  return out
}

const MONEY = /(?:[$€£]\s*\d[\d,]*(?:\.\d{1,2})?|\d[\d,]*(?:\.\d{1,2})?\s*(?:USD|EUR|GBP|TRY|CAD|AUD))/i
const REPAIR = /\b(?:part|repair|replac\w*|labou?r|service|kit|assembly)\b/i

/** A sentence that prices a repair, quoted from the finding's own source.
 *  The same rule as `app/productinsights.py`, so two screens cannot disagree. */
function leverageList(risks: Risk[]): UsedItem[] {
  const out: UsedItem[] = []
  const seen = new Set<string>()
  for (const risk of risks) {
    for (const source of risk.sources) {
      for (const sentence of source.quote.split(/(?<=[.!?])\s+|\n/)) {
        const line = sentence.trim()
        if (!line || seen.has(line) || !MONEY.test(line) || !REPAIR.test(line)) continue
        seen.add(line)
        out.push({ text: line, from: `${risk.title.trim()}${source.host ? ` · ${source.host}` : ''}` })
        if (out.length >= MAX_EACH) return out
      }
    }
  }
  return out
}

/** The card for one check, or null when the page is not secondhand or has no
 *  finding and no identity to say anything from. */
export function beforeYouBuyUsed(check: UsedCardInput): UsedCard | null {
  const market = secondhandMarket(check.url)
  const identity = identityFields(check.identity)
  const hasEvidence = check.risks.length > 0 || identity.length > 0
    || Boolean((check.assumed ?? '').trim()) || (check.subjects ?? []).length > 0
  if (!market || !hasEvidence) return null
  return {
    market,
    inspect: inspectList(check.risks),
    ask: askList(check, identity),
    leverage: leverageList(check.risks),
  }
}

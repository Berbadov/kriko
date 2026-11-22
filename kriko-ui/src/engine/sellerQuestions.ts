import type { EstimateQuote } from './estimates'
import { daysUntil, EXPIRING_DAYS } from './quotes'

/** The questions a reader asks the seller before buying one product, built
 *  only from what the catalogs know about this product and from the quote.
 *
 *  Nothing here names a product, make, model or category. The product's own
 *  label and its known problems (`claims`, read by the Estimate screen) are the
 *  only product words that appear. A figure in a question is one the quote or
 *  the date gave; a question is asked where a figure is missing, never filled
 *  with a guess.
 */

export type SellerQuestionSource = 'claim' | 'quote' | 'risk'

export interface SellerQuestion {
  text: string
  source: SellerQuestionSource
}

export interface SellerClaim {
  severity: string
  domain: string
  title: string
}

export interface SellerQuestionsInput {
  line: { label: string }
  quote: EstimateQuote | null
  claims: SellerClaim[] | undefined
  today: Date
}

export interface SellerQuestionsModel {
  subject: string
  body: string
  items: SellerQuestion[]
}

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'unrated', 'unknown']

/** Most serious first; an unknown severity sorts last. */
export function severityRank(severity: string): number {
  const at = SEVERITY_ORDER.indexOf((severity || '').trim().toLowerCase())
  return at === -1 ? SEVERITY_ORDER.length : at
}

/** A sentence's end, once: "Foo bar." whatever the catalog wrote after the words. */
const sentence = (text: string) => `${text.trim().replace(/[\s.!?]+$/, '')}.`

/** Risk reasons the quote questions already ask about are not repeated as risk questions. */
const ASKED_ELSEWHERE = /warrant|deliver|valid|expir/i

export const OPENING_TAIL = 'We would like answers to these questions first.'
export const CLOSING = 'Please answer in writing, so we can compare your offer with others. Thank you.'

function claimQuestions(claims: SellerClaim[] | undefined): SellerQuestion[] {
  return [...(claims ?? [])]
    .filter((claim) => (claim.title || '').trim() !== '')
    .sort((a, b) => severityRank(a.severity) - severityRank(b.severity))
    .map((claim) => ({
      text: `Owners report ${sentence(claim.title)} Has this unit's batch or firmware changed since? What does the warranty cover for it?`,
      source: 'claim' as const,
    }))
}

function quoteQuestions(quote: EstimateQuote | null, today: Date): SellerQuestion[] {
  if (!quote) return [{ text: 'What is your price for one unit, and does it include VAT?', source: 'quote' }]
  const out: SellerQuestion[] = []
  const add = (text: string) => out.push({ text, source: 'quote' })

  if (quote.warranty_months == null || !Number.isFinite(Number(quote.warranty_months))) {
    add('What warranty comes with this price, and for how many months?')
  }
  if (quote.delivery_days == null || !Number.isFinite(Number(quote.delivery_days))) {
    add('How many days will delivery take from the order?')
  }

  const days = daysUntil(quote.valid_until, today)
  if (days == null) {
    add('Until when is this price valid?')
  } else if (days < 0) {
    add(`The quote expired on ${quote.valid_until.trim().slice(0, 10)}. Is the price still valid, and until when?`)
  } else if (days <= EXPIRING_DAYS) {
    const when = days === 0 ? 'today' : `in ${days} ${days === 1 ? 'day' : 'days'}`
    add(`The quote expires ${when}. Is the price still valid, and until when?`)
  }

  if (quote.vat_rate == null || !Number.isFinite(Number(quote.vat_rate))) {
    add('Does the price include VAT, and at what rate?')
  }
  return out
}

function riskQuestions(quote: EstimateQuote | null): SellerQuestion[] {
  const reasons = quote?.risk?.reasons ?? []
  return reasons
    .filter((reason) => reason.trim() !== '' && !ASKED_ELSEWHERE.test(reason))
    .map((reason) => ({
      text: `Our check found: ${sentence(reason)} What can you show to settle this before we buy?`,
      source: 'risk' as const,
    }))
}

/** The name to greet: the seller, else the vendor, else nobody. */
function greetingOf(quote: EstimateQuote | null): string {
  const name = (quote?.seller || '').trim() || (quote?.vendor || '').trim()
  return name ? `Hello ${name},` : 'Hello,'
}

export function buildSellerQuestions({ line, quote, claims, today }: SellerQuestionsInput): SellerQuestionsModel {
  const label = (line.label || '').trim() || 'this product'
  const items: SellerQuestion[] = [
    ...claimQuestions(claims),
    ...quoteQuestions(quote, today),
    ...riskQuestions(quote),
  ]
  const numbered = items.map((item, index) => `${index + 1}. ${item.text}`)
  const body = [
    `${greetingOf(quote)}`,
    '',
    `We are about to buy ${label}. ${OPENING_TAIL}`,
    '',
    ...(numbered.length > 0 ? numbered : ['We have no further questions yet. Please confirm the terms in your offer in writing.']),
    '',
    CLOSING,
  ].join('\n')
  return { subject: `Questions before buying ${label}`, body, items }
}

/** The email link's body limit, in characters, and the note that says the list was cut. */
export const MAILTO_BODY_LIMIT = 1800
export const CUT_NOTE = '\n\n[The list was cut here to fit an email link. The full list is in Kriko.]'

/** A `mailto:` link for the text as it stands. A body over the limit is cut at a line
 *  break where possible, and the note says so; the link never exceeds the limit. */
export function mailtoHref(subject: string, body: string): { href: string; cut: boolean } {
  let text = body
  let cut = false
  if (body.length > MAILTO_BODY_LIMIT) {
    cut = true
    const budget = MAILTO_BODY_LIMIT - CUT_NOTE.length
    let kept = body.slice(0, budget)
    const lineBreak = kept.lastIndexOf('\n')
    if (lineBreak > budget / 2) kept = kept.slice(0, lineBreak)
    text = `${kept.replace(/\s+$/, '')}${CUT_NOTE}`
  }
  return {
    href: `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(text)}`,
    cut,
  }
}

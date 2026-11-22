import { moneyText } from '../../compare/figures'

/** What a watch's checks read, and how to say and draw it. Pure: nothing here
 *  reads the engine, converts a currency or adds a point that was not read. */

export interface HistoryPoint {
  price: number
  currency: string
  seen_at: string
}

export interface PriceHistory {
  items: HistoryPoint[]
  low: number | null
  high: number | null
  first: number | null
  last: number | null
}

export const SPARK_WIDTH = 120
export const SPARK_HEIGHT = 28
const SPARK_PAD = 3

export interface Spark {
  /** The line through every point, oldest first. Empty below two points. */
  path: string
  /** The newest point, where the dot goes. Null below two points. */
  last: { x: number; y: number } | null
  points: { x: number; y: number }[]
}

const round = (n: number) => Math.round(n * 10) / 10

/** Draw a series as one line in a width x height box: points are spaced evenly
 *  by read, the lowest price sits at the bottom edge and the highest at the top.
 *  A flat series is a level line through the middle. Fewer than two points
 *  draw nothing, because one read has no direction. */
export function sparkline(values: number[], width = SPARK_WIDTH, height = SPARK_HEIGHT, pad = SPARK_PAD): Spark {
  const prices = values.filter((value) => Number.isFinite(value))
  if (prices.length < 2) return { path: '', last: null, points: [] }
  const low = Math.min(...prices)
  const high = Math.max(...prices)
  const span = high - low
  const inner = width - pad * 2
  const tall = height - pad * 2
  const points = prices.map((price, index) => ({
    x: round(pad + (inner * index) / (prices.length - 1)),
    y: round(span === 0 ? height / 2 : pad + tall * (1 - (price - low) / span)),
  }))
  const path = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x} ${point.y}`).join(' ')
  return { path, last: points[points.length - 1], points }
}

const plain = (amount: number) => amount.toLocaleString(undefined, { maximumFractionDigits: 2 })

/** True when the newest read is the lowest the checks have seen and some earlier read was higher. */
export function isLowestSoFar(history: PriceHistory | null | undefined): boolean {
  if (!history || history.items.length < 2 || history.low == null || history.high == null || history.last == null) return false
  return history.last <= history.low && history.high > history.low
}

/** The sparkline's spoken label: how many reads, where it began and ended, and the lowest. */
export function sparkLabel(history: PriceHistory): string {
  const { items, first, last, low } = history
  if (items.length < 2 || first == null || last == null || low == null) return ''
  return `Price over ${items.length} reads: from ${plain(first)} to ${plain(last)}, lowest ${plain(low)}`
}

/** Last read against the first one, in words: "Down 100 USD (8.3%)", "Up ...", or "No change". */
export function sinceFirstText(history: PriceHistory, currency: string): string {
  const { first, last } = history
  if (first == null || last == null) return ''
  const diff = last - first
  if (Math.abs(diff) < 0.005) return 'No change'
  const share = first > 0 ? ` (${(Math.abs(diff / first) * 100).toFixed(1)}%)` : ''
  return `${diff < 0 ? 'Down' : 'Up'} ${moneyText(Math.abs(diff), currency)}${share}`
}

/** The three figures a row says in words, or none when fewer than two reads exist. */
export function figuresOf(history: PriceHistory | null | undefined, currency: string): { label: string; value: string }[] {
  if (!history || history.items.length < 2) return []
  const unit = currency || history.items[history.items.length - 1].currency
  return [
    { label: 'Lowest', value: moneyText(history.low, unit) },
    { label: 'Highest', value: moneyText(history.high, unit) },
    { label: 'Since first read', value: sinceFirstText(history, unit) },
  ]
}

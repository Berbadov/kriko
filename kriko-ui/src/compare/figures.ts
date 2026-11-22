import type { ProcurementLine } from '../engine/procurement'
import { count } from '../ui/format'

/** Display figures for Compare's procurement rows and Prices' watches. Pure
 *  text and comparisons: no figure is converted, estimated or invented here.
 *  A price is always stated in the currency it was read in. */

/** An amount with its currency after it, or a dash when there is no amount. */
export function moneyText(amount: number | null | undefined, currency: string): string {
  if (amount == null || !Number.isFinite(amount)) return '–'
  const digits = amount.toLocaleString(undefined, { maximumFractionDigits: 2 })
  return currency ? `${digits} ${currency}` : digits
}

/** Days until a quote lapses, said in words. Negative is already past. */
export function expiryText(days: number | null): string {
  if (days == null) return 'No date'
  if (days < 0) return `Expired ${count(-days, 'day')} ago`
  if (days === 0) return 'Expires today'
  return `${count(days, 'day')} left`
}

export function deliveryText(days: number | null): string {
  return days == null ? 'Not given' : count(days, 'day')
}

export function warrantyText(months: number | null): string {
  return months == null ? 'Not given' : count(months, 'month')
}

/** The line whose landed cost a column shows: the first with a comparable price, which the
 *  estimates list already orders most recent first. Null when none can be compared. */
export function pricedLine(lines: ProcurementLine[]): ProcurementLine | null {
  return lines.find((line) => line.bestLanded != null) ?? null
}

export interface ColumnLines {
  name: string
  lines: ProcurementLine[]
}

/** One sentence on what the procurement rows say about the compared products. It compares
 *  only figures in one currency; when the priced quotes disagree on currency it says so. */
export function procurementRead(columns: ColumnLines[]): string {
  const withLines = columns.filter((column) => column.lines.length > 0)
  if (withLines.length === 0) return 'None of these products is in an estimate yet, so there is no landed cost to compare.'
  const priced = columns.flatMap((column) => {
    const line = pricedLine(column.lines)
    return line && line.bestLanded != null ? [{ name: column.name, amount: line.bestLanded, currency: line.currency }] : []
  })
  if (priced.length === 0) return 'None of these has a comparable landed cost yet, so none can be compared.'
  const currencies = [...new Set(priced.map((row) => row.currency))]
  if (currencies.length > 1) {
    return `These prices are in ${currencies.join(' and ')}, so their landed costs cannot be compared without an exchange rate.`
  }
  const currency = currencies[0]
  if (priced.length === 1) return `Only ${priced[0].name} has a comparable landed cost yet, at ${moneyText(priced[0].amount, currency)} per unit.`
  const sorted = [...priced].sort((a, b) => a.amount - b.amount)
  const low = sorted[0]
  const tied = sorted.filter((row) => row.amount === low.amount)
  const next = sorted.find((row) => row.amount > low.amount)
  if (tied.length > 1) {
    const names = tied.map((row) => row.name)
    const list = names.length === 2 ? `${names[0]} and ${names[1]}` : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
    return `${list} have the same landed cost, ${moneyText(low.amount, currency)} per unit.`
  }
  if (!next) return `${low.name} has the lowest landed cost, ${moneyText(low.amount, currency)} per unit.`
  const gap = next.amount - low.amount
  return `${low.name} has the lower landed cost, ${moneyText(low.amount, currency)} per unit, which is ${moneyText(gap, currency)} less than ${next.name}.`
}

/** A price watch's move since it started, as a share, or null when either end is unknown. */
export function moveOf(watch: { started_price: number | null; last_price: number | null }): number | null {
  const { started_price: from, last_price: now } = watch
  if (from == null || now == null || from <= 0) return null
  return (now - from) / from
}

/** A watch has reached its target when the page's last price is at or below it. */
export function targetReached(watch: { target: number | null; last_price: number | null }): boolean {
  return watch.target != null && watch.last_price != null && watch.last_price <= watch.target
}

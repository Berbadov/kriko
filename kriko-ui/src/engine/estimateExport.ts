import type { Cell, Sheet } from './sheet'
import type { EstimateLine } from './estimates'
import type { Forecast, ForecastRow } from './forecast'
import { convert, quoteMoney, type Rates } from './money'
import { chosenQuote, lineUnitGross } from './quotes'

/** The workbook and CSV the Estimate screen exports, built from the same
 *  numbers the screen shows. Pure, so a test can read every cell.
 *
 *  Money keeps its currency: an amount in a quote's own currency is converted
 *  at the stated rate for the accounting sheet, and a cell with no rate is left
 *  blank, never written as if it were already in the estimate currency.
 */

/** The columns the accounting sheet always carries, in this order. A
 *  bookkeeper maps them once; adding a column happens at the end, never in the
 *  middle. */
export const ACCOUNTING_COLUMNS = [
  'Item', 'Catalog', 'Asset category', 'Acquisition year', 'Useful life (years)',
  'Depreciation method', 'Cost (net)', 'VAT', 'Cost (gross)', 'Salvage',
  'Currency', 'Vendor', 'Seller', 'Quote date', 'Document',
]

export interface KnownProblem { severity: string; domain: string; title: string; via?: string }

export interface ExportInput {
  name: string
  currency: string
  vatRate: number
  years: number
  maintenancePct: number
  discountPct: number
  fx: Rates & { source?: unknown; date?: unknown }
  lines: EstimateLine[]
  model: Forecast
  usage: { spent_usd?: number | null; runs?: number; claims?: number } | null
  /** Known problems per subject, when they have been read. */
  problems: Record<string, KnownProblem[] | undefined>
  costs: { estimates: Record<string, { usd: number | null }> } | null
}

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'unrated', 'unknown']
const severityRank = (severity: string) => {
  const at = SEVERITY_ORDER.indexOf((severity || '').toLowerCase())
  return at === -1 ? SEVERITY_ORDER.length : at
}

const usd = (amount: number) => `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })} USD`

/** The estimate, one row per line, with the quote and the totals. */
export function estimateSheet(input: ExportInput): Sheet {
  const { currency, fx, lines, model } = input
  const rows: Cell[][] = [
    [input.name.trim() || 'Untitled estimate', '', `Currency: ${currency}`],
    [`VAT default: ${input.vatRate}%`, '', `Rates: ${fx.source === 'TCMB' ? `TCMB ${String(fx.date ?? '')}` : 'manual'}`],
    [],
    ['Equipment', 'Catalog', 'Qty', 'Selected vendor', 'Seller', 'Quote URL', 'Quote currency',
      'Unit price (as typed)', 'Price basis', 'VAT %', 'Net unit', 'Gross unit',
      `Gross unit (${currency})`, `Line gross (${currency})`, 'Delivery days', 'Warranty months', 'Risk', 'Note'],
  ]
  for (const line of lines) {
    const quote = chosenQuote(line)
    const read = quote ? quoteMoney(quote, currency, fx) : null
    const unit = lineUnitGross(line, currency, fx)
    rows.push([
      line.label,
      line.pack_id,
      line.quantity,
      quote?.vendor || (line.unit_price != null ? 'Migrated price' : ''),
      quote?.seller ?? '',
      quote?.url ?? '',
      quote?.currency || currency,
      quote?.unit_price ?? line.unit_price ?? '',
      quote ? (quote.vat_included ? 'gross' : 'net') : 'not stated',
      quote?.vat_rate ?? '',
      read?.net ?? '',
      read?.gross ?? '',
      unit ?? (quote ? '' : line.unit_price ?? ''),
      unit == null ? '' : line.quantity * unit,
      quote?.delivery_days ?? '',
      quote?.warranty_months ?? '',
      quote?.risk?.level ?? '',
      line.note,
    ])
  }
  rows.push(
    [],
    ['Totals: net, VAT, gross', '', '', '', '', '', '', '', '', '', model.vat.net, model.vat.vat, model.vat.gross, model.capital, model.unpriced ? `${model.unpriced} line(s) unpriced` : '', '', '', ''],
    ['Research spend so far', '', '', '', '', '', '', '', '', '', '', '', '', input.usage?.spent_usd ?? '', input.usage ? `${input.usage.runs ?? 0} run(s), ${input.usage.claims ?? 0} claims kept` : '', '', ''],
  )
  if (input.costs) {
    rows.push(['Next research run, estimated', ...Object.entries(input.costs.estimates).map(([plane, est]) => `${plane}: ${est.usd == null ? 'not enough history yet' : usd(est.usd)}`)])
  }
  return { name: 'Estimate', rows }
}

/** The forecast by year, the totals, and one depreciation schedule per priced line. */
export function forecastSheet(input: ExportInput): Sheet {
  const { model, lines, currency, fx } = input
  const rows: Cell[][] = [
    ['Forecast', `Currency: ${currency}`, `Years: ${input.years}`, `Upkeep %/yr: ${input.maintenancePct}`, `Discount %: ${input.discountPct}`],
    [],
    ['Year', 'Capital', 'Maintenance', 'Depreciation', 'Cash', 'Discounted', 'Cumulative'],
    ...model.rows.map((row: ForecastRow) => [row.year, row.capital, row.maintenance, row.depreciation, row.cash, row.discounted, row.cumulative]),
    [],
    ['Total', model.capital, model.maintenance, model.depreciation, model.cash, '', ''],
    ['NPV (discounted cash)', model.npv, '', '', '', '', ''],
    [],
    ['Assets', 'Method', 'Life (years)', 'Cost (gross)', 'Salvage', 'Depreciation total'],
  ]
  // `assets` holds priced lines only, in line order; an unpriced line must not shift every schedule after it.
  let at = 0
  for (const line of lines) {
    const priced = lineUnitGross(line, currency, fx) != null
    const asset = priced ? model.assets[at++] : undefined
    rows.push([line.label, asset?.method ?? '', asset?.life_years ?? '', asset?.amount ?? '', asset?.salvage ?? '', asset?.total ?? ''])
  }
  return { name: 'Forecast', rows }
}

/** The accounting columns, in ACCOUNTING_COLUMNS order. Amounts are in the estimate currency. */
export function accountingSheet(input: ExportInput): Sheet {
  const { currency, fx } = input
  const rows: Cell[][] = [[...ACCOUNTING_COLUMNS]]
  for (const line of input.lines) {
    const quote = chosenQuote(line)
    let net: number | null
    let vat: number | null
    let gross: number | null
    if (quote) {
      const read = quoteMoney(quote, currency, fx)
      net = convert(read.net, read.currency, currency, fx)
      vat = convert(read.vat, read.currency, currency, fx)
      gross = convert(read.gross, read.currency, currency, fx)
    } else {
      net = line.unit_price ?? null
      vat = null
      gross = line.unit_price ?? null
    }
    const times = (amount: number | null) => (amount == null ? '' : amount * line.quantity)
    rows.push([
      line.label,
      line.pack_id,
      '',
      '',
      line.life_years ?? '',
      line.depreciation,
      times(net),
      times(vat),
      times(gross),
      line.salvage ?? '',
      currency,
      quote?.vendor ?? '',
      quote?.seller ?? '',
      quote?.quote_date ?? '',
      quote?.url ?? '',
    ])
  }
  return { name: 'Accounting', rows }
}

/** Known problems per line, most serious first. */
export function researchSheet(input: ExportInput): Sheet {
  const rows: Cell[][] = [['Equipment', 'Catalog', 'Severity', 'Domain', 'Known issue']]
  for (const line of input.lines) {
    const found = input.problems[line.subject_id]
    if (!found) continue
    const sorted = [...found].sort((a, b) => severityRank(a.severity) - severityRank(b.severity))
    for (const claim of sorted) {
      rows.push([line.label, line.pack_id, claim.severity, claim.domain, claim.via ? `${claim.title} (via ${claim.via})` : claim.title])
    }
    if (sorted.length === 0) rows.push([line.label, line.pack_id, '', '', 'No known issues in the catalog yet. Research it.'])
  }
  return { name: 'Research', rows }
}

export function costsSheet(input: ExportInput): Sheet {
  const rows: Cell[][] = [
    ['Research costs', '', ''],
    ['Spent so far (USD)', input.usage?.spent_usd ?? 'not metered', ''],
    ['Runs', input.usage?.runs ?? 0, `${input.usage?.claims ?? 0} claims kept`],
  ]
  if (input.costs) {
    rows.push([], ['Next research run, estimated by plane', '', ''])
    for (const [plane, est] of Object.entries(input.costs.estimates)) {
      rows.push([plane, est.usd == null ? 'not enough history yet' : `$${est.usd.toFixed(4)}`, ''])
    }
  }
  return { name: 'Costs', rows }
}

/** The workbook: estimate, forecast, accounting, research and costs, in that order. */
export function workbookSheets(input: ExportInput): Sheet[] {
  return [estimateSheet(input), forecastSheet(input), accountingSheet(input), researchSheet(input), costsSheet(input)]
}

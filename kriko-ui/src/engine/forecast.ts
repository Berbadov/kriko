/** The forecast math behind the Estimate screen, pure so a test can pin it.
 *
 *  Model, stated so an accountant can argue with it: year 0 is the purchase
 *  year and carries the whole capital cost. Every later year carries upkeep
 *  (`maintenance_pct` of capital per year, paid at year end) and the
 *  depreciation the reader's method asks for. `cash` is capital in year 0 plus
 *  upkeep in later years - depreciation is shown because a capital manager
 *  reads the P&L, not because it is a cash outflow. `npv` discounts the cash
 *  flows at `discount_pct`. A line without a price contributes nothing to the
 *  sums and is counted separately, never silently read as zero.
 *
 *  Money and tax, kept apart:
 *
 *  - `unit_price` is what the reader typed. `vat_included` says whether that
 *    number already carries VAT; `vat_rate` is the line's own rate. The
 *    forecast's `capital` is the gross amount actually paid, and the screen
 *    shows net and gross side by side. A line that states no VAT is read as
 *    VAT-free here - the screen, not this module, decides the default rate.
 *  - Depreciation never guesses a life or a rate. Straight-line takes the
 *    line's `life_years` (or the forecast horizon), declining balance uses
 *    twice the straight-line rate unless a `vuk_rate` is given, and the VUK
 *    method uses the rate the reader read off GİB's list. Salvage is a floor:
 *    the book value never goes below it.
 */

export interface CostLine {
  quantity: number
  unit_price: number | null
  vat_rate?: number | null
  vat_included?: boolean | null
  depreciation?: 'straight_line' | 'declining_balance' | 'vuk' | string | null
  life_years?: number | null
  salvage?: number | null
  vuk_rate?: number | null
}

export interface ForecastParams {
  years: number
  maintenance_pct: number
  discount_pct: number
}

export interface ForecastRow {
  year: number
  capital: number
  maintenance: number
  depreciation: number
  cash: number
  discounted: number
  cumulative: number
}

export interface VatSplit {
  net: number
  vat: number
  gross: number
}

export interface LineDepreciation {
  amount: number
  salvage: number
  method: string
  life_years: number
  yearly: number[]
  total: number
}

export interface Forecast {
  rows: ForecastRow[]
  capital: number
  maintenance: number
  depreciation: number
  cash: number
  npv: number
  unpriced: number
  /** Net, VAT and gross over the priced lines. */
  vat: VatSplit
  /** One schedule per priced line, in line order. */
  assets: LineDepreciation[]
}

export function lineTotal(line: CostLine): number | null {
  if (line.unit_price == null) return null
  return line.quantity * line.unit_price
}

export function lineVat(line: CostLine): VatSplit | null {
  const total = lineTotal(line)
  if (total == null) return null
  const rate = Math.max(0, Number(line.vat_rate ?? 0)) / 100
  if (line.vat_included) {
    const net = total / (1 + rate)
    return { net, vat: total - net, gross: total }
  }
  return { net: total, vat: total * rate, gross: total * (1 + rate) }
}

/** The priced subtotal and how many lines have no price yet. */
export function subtotal(lines: CostLine[]): { priced: number; unpriced: number } {
  let priced = 0
  let unpriced = 0
  for (const line of lines) {
    const total = lineTotal(line)
    if (total == null) unpriced += 1
    else priced += total
  }
  return { priced, unpriced }
}

/** Net, VAT and gross over the lines that have a price. */
export function vatTotals(lines: CostLine[]): VatSplit {
  const out: VatSplit = { net: 0, vat: 0, gross: 0 }
  for (const line of lines) {
    const split = lineVat(line)
    if (split == null) continue
    out.net += split.net
    out.vat += split.vat
    out.gross += split.gross
  }
  return out
}

const clampYears = (years: number) => Math.max(1, Math.min(30, Math.floor(years) || 1))

const num = (value: number | null | undefined) => {
  const number = Number(value ?? 0)
  return Number.isFinite(number) ? number : 0
}

/** One line's depreciation, year by year, for the horizon asked for.
 *
 *  `amount` is the gross capital of the line. The last year of a straight-line
 *  schedule absorbs rounding, so the column sums to `amount - salvage` to the
 *  cent; a declining schedule stops at salvage and a horizon shorter than the
 *  life simply shows the years it has.
 */
export function depreciationOf(line: CostLine, horizon: number): LineDepreciation {
  const amount = Math.max(0, num(lineTotal(line)))
  const method = String(line.depreciation || 'straight_line')
  const salvage = Math.min(amount, Math.max(0, num(line.salvage)))
  const life = Math.max(1, Math.min(50, Math.floor(Number(line.life_years) || horizon)))
  const yearly: number[] = []
  const depreciable = Math.max(0, amount - salvage)

  if (method === 'declining_balance' || method === 'vuk') {
    const rate = method === 'vuk'
      ? Math.min(1, Math.max(0, num(line.vuk_rate)) / 100)
      : Math.min(1, 2 / life)
    let book = amount
    for (let year = 0; year < horizon; year += 1) {
      const charge = year < life ? Math.min(Math.max(0, book - salvage), book * rate) : 0
      yearly.push(charge)
      book -= charge
      if (book <= salvage + 1e-9) break
    }
  } else {
    const straight = depreciable / life
    for (let year = 0; year < horizon; year += 1) {
      yearly.push(year < life ? straight : 0)
    }
    if (yearly.length >= life) yearly[life - 1] = depreciable - straight * (life - 1)
  }

  while (yearly.length < horizon) yearly.push(0)
  const total = yearly.reduce((sum, value) => sum + value, 0)
  return { amount, salvage, method, life_years: life, yearly, total }
}

export function forecast(lines: CostLine[], params: ForecastParams): Forecast {
  const years = clampYears(params.years)
  const maintenanceRate = Math.max(0, params.maintenance_pct) / 100
  const discountRate = Math.max(0, params.discount_pct) / 100
  const pricedLines = lines.filter((line) => lineTotal(line) != null)
  const { unpriced } = subtotal(lines)
  const vat = vatTotals(lines)
  const capital = vat.gross

  const assets = pricedLines.map((line) => depreciationOf(line, years))
  const perYear = Array.from({ length: years + 1 }, () => 0)
  for (const asset of assets) {
    for (let year = 1; year <= years; year += 1) perYear[year] += asset.yearly[year - 1] ?? 0
  }

  const rows: ForecastRow[] = []
  let maintenance = 0
  let cash = capital
  let npv = capital
  let cumulative = capital
  rows.push({
    year: 0, capital, maintenance: 0, depreciation: 0,
    cash: capital, discounted: capital, cumulative,
  })
  for (let year = 1; year <= years; year += 1) {
    const upkeep = capital * maintenanceRate
    const yearCash = upkeep
    const discounted = yearCash / Math.pow(1 + discountRate, year)
    maintenance += upkeep
    cash += yearCash
    npv += discounted
    cumulative += yearCash
    rows.push({
      year,
      capital: 0,
      maintenance: upkeep,
      depreciation: perYear[year],
      cash: yearCash,
      discounted,
      cumulative,
    })
  }
  return {
    rows,
    capital,
    maintenance,
    depreciation: assets.reduce((sum, asset) => sum + asset.total, 0),
    cash,
    npv,
    unpriced,
    vat,
    assets,
  }
}

/** The forecast math behind the Estimate screen, pure so a test can pin it.
 *
 *  Model, stated so an accountant can argue with it: year 0 is the purchase
 *  year and carries the whole capital cost. Every later year carries upkeep
 *  (`maintenance_pct` of capital per year, paid at year end) and straight-line
 *  depreciation (capital / years). `cash` is capital in year 0 plus upkeep in
 *  later years — depreciation is shown because a capital manager reads the
 *  P&L, not because it is a cash outflow. `npv` discounts the cash flows at
 *  `discount_pct`. A line without a price contributes nothing to the sums and
 *  is counted separately, never silently read as zero.
 */

export interface CostLine {
  quantity: number
  unit_price: number | null
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

export interface Forecast {
  rows: ForecastRow[]
  capital: number
  maintenance: number
  depreciation: number
  cash: number
  npv: number
  unpriced: number
}

export function lineTotal(line: CostLine): number | null {
  if (line.unit_price == null) return null
  return line.quantity * line.unit_price
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

const clampYears = (years: number) => Math.max(1, Math.min(30, Math.floor(years) || 1))

export function forecast(lines: CostLine[], params: ForecastParams): Forecast {
  const years = clampYears(params.years)
  const maintenanceRate = Math.max(0, params.maintenance_pct) / 100
  const discountRate = Math.max(0, params.discount_pct) / 100
  const { priced: capital, unpriced } = subtotal(lines)

  const rows: ForecastRow[] = []
  let maintenance = 0
  let cash = capital
  let npv = capital
  let cumulative = capital
  rows.push({
    year: 0, capital, maintenance: 0, depreciation: 0,
    cash: capital, discounted: capital, cumulative,
  })
  const depreciation = capital / years
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
      depreciation,
      cash: yearCash,
      discounted,
      cumulative,
    })
  }
  return {
    rows,
    capital,
    maintenance,
    depreciation: depreciation * years,
    cash,
    npv,
    unpriced,
  }
}

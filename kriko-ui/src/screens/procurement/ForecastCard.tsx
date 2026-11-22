import type { Forecast } from '../../engine/forecast'
import { EMPTY, money } from './format'

/** The multi-year forecast as its own card: the year rows, the totals, the
 *  net, VAT and gross the priced lines carry, and the two exports as words. */

export function ForecastCard({ model, currency, onCsv, onExcel, canExport, research }: {
  model: Forecast
  currency: string
  onCsv: () => void
  onExcel: () => void
  canExport: boolean
  research: string
}) {
  return (
    <section className="k-group procurement-forecast" aria-labelledby="procurement-forecast-caption">
      <div className="procurement-group-head">
        <span className="k-caption" id="procurement-forecast-caption">Forecast</span>
        <span className="procurement-export">
          <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={onExcel} disabled={!canExport}>Download Excel</button>
          <button type="button" className="k-btn" data-kind="quiet" data-size="sm" onClick={onCsv} disabled={!canExport}>Download CSV</button>
        </span>
      </div>
      <div className="k-card procurement-forecast-body">
        <div className="k-kpis procurement-totals" aria-label="Totals">
          <div className="k-kpi">
            <span className="k-kpi-value procurement-money">{money(model.vat.net, currency)}</span>
            <span className="k-kpi-label">Net</span>
          </div>
          <div className="k-kpi">
            <span className="k-kpi-value procurement-money">{money(model.vat.vat, currency)}</span>
            <span className="k-kpi-label">VAT</span>
          </div>
          <div className="k-kpi">
            <span className="k-kpi-value procurement-money">{money(model.vat.gross, currency)}</span>
            <span className="k-kpi-label">Gross, paid in year 0</span>
          </div>
          <div className="k-kpi">
            <span className="k-kpi-value procurement-money">{money(model.npv, currency)}</span>
            <span className="k-kpi-label">Present value of cash</span>
          </div>
        </div>
        <div className="procurement-table-scroll">
          <table className="k-table procurement-forecast-table">
            <thead>
              <tr>
                <th scope="col" data-num>Year</th>
                <th scope="col" data-num>Capital</th>
                <th scope="col" data-num>Upkeep</th>
                <th scope="col" data-num>Depreciation</th>
                <th scope="col" data-num>Cash</th>
                <th scope="col" data-num>Discounted</th>
                <th scope="col" data-num>Cumulative</th>
              </tr>
            </thead>
            <tbody>
              {model.rows.map((row) => (
                <tr key={row.year}>
                  <td data-num>{row.year}</td>
                  <td data-num>{row.capital ? money(row.capital, currency) : EMPTY}</td>
                  <td data-num>{row.maintenance ? money(row.maintenance, currency) : EMPTY}</td>
                  <td data-num>{row.depreciation ? money(row.depreciation, currency) : EMPTY}</td>
                  <td data-num>{money(row.cash, currency)}</td>
                  <td data-num>{money(row.discounted, currency)}</td>
                  <td data-num>{money(row.cumulative, currency)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td data-num>Total</td>
                <td data-num>{money(model.capital, currency)}</td>
                <td data-num>{money(model.maintenance, currency)}</td>
                <td data-num>{money(model.depreciation, currency)}</td>
                <td data-num>{money(model.cash, currency)}</td>
                <td data-num colSpan={2}>Present value {money(model.npv, currency)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
        <p className="procurement-quote-sub">
          {model.unpriced > 0
            ? <><strong>{model.unpriced} {model.unpriced === 1 ? 'line' : 'lines'}</strong> without a price, not counted.</>
            : 'Every line is priced.'}
          {' '}{research}
        </p>
      </div>
    </section>
  )
}

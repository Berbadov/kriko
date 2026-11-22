import type { Mapping, ColumnRole } from '../../engine/checklist'
import type { Table } from '../../engine/spreadsheet'

/** Step two: which column is which, and the first rows as they were read. */

const PREVIEW_ROWS = 5

const ROLES: { role: ColumnRole; label: string; required?: boolean; note: string }[] = [
  { role: 'name', label: 'Product name', required: true, note: 'What each row is called. This is what gets checked.' },
  { role: 'quantity', label: 'Quantity', note: 'Used when you add the rows to an estimate. Without it each line is 1.' },
  { role: 'price', label: 'Price', note: 'Becomes a quote on the line. A row with no price gets a line and no quote.' },
  { role: 'currency', label: 'Currency', note: 'A symbol or code in the price wins. Without either, the estimate’s currency is used.' },
  { role: 'vendor', label: 'Vendor', note: 'Names the quote. Without it the quote says "From a list".' },
]

const letter = (index: number): string => {
  let n = index
  let out = ''
  do {
    out = String.fromCharCode(65 + (n % 26)) + out
    n = Math.floor(n / 26) - 1
  } while (n >= 0)
  return out
}

const clip = (text: string): string => (text.length > 60 ? `${text.slice(0, 59)}…` : text)

export function MatchColumns({ tables, sheetAt, table, mapping, onSheet, onMapping }: {
  tables: Table[]
  sheetAt: number
  table: Table
  mapping: Mapping
  onSheet: (index: number) => void
  onMapping: (role: ColumnRole, column: number | undefined) => void
}) {
  const options = table.header.map((head, index) => ({ index, text: `${letter(index)}: ${clip(head.trim()) || '(no heading)'}` }))
  const shown = table.rows.slice(0, PREVIEW_ROWS)

  return (
    <section className="k-group" aria-labelledby="checklist-step-columns">
      <h2 className="k-caption" id="checklist-step-columns">2. Match the columns</h2>
      <div className="k-card" data-pad>
        <div className="checklist-fields">
          {tables.length > 1 && (
            <div className="k-field">
              <label htmlFor="checklist-sheet">Sheet</label>
              <select id="checklist-sheet" className="k-input" value={sheetAt} onChange={(event) => onSheet(Number(event.target.value))}>
                {tables.map((one, index) => (
                  <option key={index} value={index}>{one.name || `Sheet ${index + 1}`} ({one.rows.length} rows)</option>
                ))}
              </select>
            </div>
          )}
          {ROLES.map(({ role, label, required, note }) => (
            <div className="k-field" key={role}>
              <label htmlFor={`checklist-col-${role}`}>{label}{required ? ' (required)' : ''}</label>
              <select
                id={`checklist-col-${role}`}
                className="k-input"
                aria-describedby={`checklist-col-${role}-note`}
                value={mapping[role] ?? ''}
                onChange={(event) => onMapping(role, event.target.value === '' ? undefined : Number(event.target.value))}
              >
                <option value="">{required ? 'Choose a column' : 'None'}</option>
                {options.map((option) => <option key={option.index} value={option.index}>{option.text}</option>)}
              </select>
              <span className="checklist-hint" id={`checklist-col-${role}-note`}>{note}</span>
            </div>
          ))}
        </div>
      </div>

      <h3 className="k-caption checklist-sub">First {Math.min(PREVIEW_ROWS, table.rows.length)} of {table.rows.length + (table.truncated ?? 0)} rows</h3>
      <div className="k-card checklist-scroll">
        <table className="k-table checklist-preview">
          <caption className="checklist-sr">The first rows of the chosen sheet</caption>
          <thead>
            <tr>
              {options.map((option) => (
                <th key={option.index} scope="col" data-mapped={Object.values(mapping).includes(option.index) || undefined}>
                  {clip(table.header[option.index].trim()) || letter(option.index)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((cells, row) => (
              <tr key={row}>
                {options.map((option) => <td key={option.index}>{clip(cells[option.index] ?? '')}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

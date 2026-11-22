import { tableToText, type Spreadsheet } from './spreadsheet'

/** A spreadsheet attached to a chat, as the text a model reads.
 *
 *  Only the first sheet is attached, as a compact table: its first rows, each
 *  cell cut short. The message still has to fit the composer's own limit, so a
 *  long sheet says how many rows it left out rather than filling the box. */

/** Rows of the sheet that go into the message. */
export const ATTACH_ROWS = 60

/** The text to attach for a sheet read from `.xlsx` or `.csv`, or `null` when the file
 *  is not a table worth showing as one (a CSV that is one column of plain text goes in as it was). */
export function spreadsheetAttachment(sheet: Spreadsheet, limit = ATTACH_ROWS): string | null {
  const table = sheet.tables[0]
  if (!table) return null
  if (sheet.format === 'csv' && table.header.length < 2) return null
  const total = table.rows.length + (table.truncated ?? 0)
  const cut = total > limit ? ` (first ${limit} of ${total} rows)` : ''
  const others = sheet.tables.slice(1)
  const more = others.length
    ? `\nThis workbook has ${others.length} more ${others.length === 1 ? 'sheet' : 'sheets'}, not attached: ${others.map((one) => one.name).join(', ')}.`
    : ''
  const where = sheet.format === 'xlsx' ? `, sheet "${table.name}"` : ''
  return `Attached document (${sheet.fileName}${where}${cut}; source data):\n${tableToText(table, limit)}${more}`
}

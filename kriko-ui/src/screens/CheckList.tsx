import { useEffect, useMemo, useRef, useState } from 'react'
import { post, seg } from '../engine/api'
import {
  chooseCandidate,
  checkNames,
  MAX_NAMES,
  prepareRows,
  resolveRows,
  resultRows,
  type ColumnRole,
  type Filter,
  type Mapping,
  type Order,
  type Prepared,
  type Resolved,
} from '../engine/checklist'
import { useEngine } from '../engine/Engine'
import { csvOf, downloadFile, xlsxOf } from '../engine/sheet'
import { guessColumns, readSpreadsheet, type Spreadsheet, type Table } from '../engine/spreadsheet'
import { AddDialog } from './checklist/AddDialog'
import { ChooseFile } from './checklist/ChooseFile'
import { MatchColumns } from './checklist/MatchColumns'
import { Results } from './checklist/Results'

/** Check a list (screen id `checklist`): a spreadsheet of products the reader plans to buy,
 *  each row matched to the installed catalogs and said in the engine's own words. It needs no
 *  language model, so it works with a local model or none. The file is read in this window and
 *  never uploaded; only the names go to the engine.
 *
 *  Four steps on one page, each appearing when the one before is done. */

type Phase = 'idle' | 'checking' | 'done'

const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
const reason = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback)

const slug = (name: string) =>
  name.replace(/\.[^.]+$/, '').normalize('NFKD').replace(/[^\w-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'list'

const mappingOf = (table: Table): Mapping => {
  const guess = guessColumns(table)
  return { name: guess.name, quantity: guess.quantity, price: guess.price, currency: guess.currency, vendor: guess.vendor }
}

const detailOf = (book: Spreadsheet): string => {
  const rows = book.tables.reduce((sum, one) => sum + one.rows.length + (one.truncated ?? 0), 0)
  const sheets = book.tables.length > 1 ? `${plural(book.tables.length, 'sheet', 'sheets')}, ` : ''
  return `${sheets}${plural(rows, 'row', 'rows')} read.`
}

export function CheckListScreen({ onOpen }: { onOpen?: (lookupId: string) => void }) {
  const { mode } = useEngine()
  const [book, setBook] = useState<Spreadsheet | null>(null)
  const [reading, setReading] = useState(false)
  const [fileProblem, setFileProblem] = useState('')
  const [sheetAt, setSheetAt] = useState(0)
  const [mapping, setMapping] = useState<Mapping>({})
  const [phase, setPhase] = useState<Phase>('idle')
  const [ran, setRan] = useState<Prepared | null>(null)
  const [base, setBase] = useState<Resolved[] | null>(null)
  const [choices, setChoices] = useState<Record<number, string>>({})
  const [problem, setProblem] = useState('')
  const [note, setNote] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [order, setOrder] = useState<Order>('file')
  const [opening, setOpening] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)
  const [added, setAdded] = useState<{ name: string; created: number; joined: number } | null>(null)
  const abort = useRef<AbortController | null>(null)
  const reads = useRef(0)

  useEffect(() => () => abort.current?.abort(), [])

  const table = book?.tables[sheetAt] ?? null
  const prepared = useMemo(() => (table ? prepareRows(table, mapping.name) : null), [table, mapping.name])
  const items = useMemo(
    () => (base ? base.map((one) => (choices[one.row] ? chooseCandidate(one, choices[one.row]) : one)) : null),
    [base, choices],
  )

  /** Results belong to the sheet and name column they were made from. */
  const forget = () => {
    abort.current?.abort()
    setPhase('idle')
    setRan(null)
    setBase(null)
    setChoices({})
    setProblem('')
    setNote('')
    setAdded(null)
    setFilter('all')
    setOrder('file')
  }

  const open = async (file: File) => {
    const mine = ++reads.current
    setReading(true)
    setFileProblem('')
    try {
      const read = await readSpreadsheet(file)
      if (mine !== reads.current) return
      const first = read.tables[0]
      if (!first || first.rows.length === 0) {
        setFileProblem(`"${file.name}" has no rows under its headings. Add the products, one per row, and choose it again.`)
        return
      }
      forget()
      setBook(read)
      setSheetAt(0)
      setMapping(mappingOf(first))
    } catch (error) {
      if (mine === reads.current) setFileProblem(reason(error, 'The file could not be read. Choose it again.'))
    } finally {
      if (mine === reads.current) setReading(false)
    }
  }

  const changeSheet = (index: number) => {
    const next = book?.tables[index]
    if (!next) return
    forget()
    setSheetAt(index)
    setMapping(mappingOf(next))
  }

  const changeMapping = (role: ColumnRole, column: number | undefined) => {
    if (role === 'name') forget()
    setMapping((now) => ({ ...now, [role]: column }))
  }

  const check = async () => {
    if (!prepared || prepared.rows.length === 0) return
    const controller = new AbortController()
    abort.current?.abort()
    abort.current = controller
    setPhase('checking')
    setProblem('')
    setNote('')
    setAdded(null)
    try {
      const answer = await checkNames(prepared.rows.map((one) => one.name), controller.signal)
      if (controller.signal.aborted) return
      setBase(resolveRows(prepared, answer))
      setRan(prepared)
      setChoices({})
      setFilter('all')
      setOrder('file')
      setPhase('done')
    } catch (error) {
      if (controller.signal.aborted || (error instanceof DOMException && error.name === 'AbortError')) {
        setPhase(base ? 'done' : 'idle')
        setNote('Cancelled. Nothing was changed.')
        return
      }
      setProblem(`${reason(error, 'The engine did not answer.')} Check that Kriko is running and try again.`)
      setPhase(base ? 'done' : 'idle')
    }
  }

  const cancel = () => abort.current?.abort()

  const choose = (row: number, subjectId: string) =>
    setChoices((now) => {
      const next = { ...now }
      if (subjectId) next[row] = subjectId
      else delete next[row]
      return next
    })

  /** A product opens its saved check. The engine keeps one saved check per product. */
  const openProduct = async (item: Resolved) => {
    if (!item.match) return
    setOpening(item.row)
    setProblem('')
    try {
      let lookup = `demo:${item.match.label}`
      if (mode === 'live') {
        const checked = await post<{ lookup_id?: string }>(`/api/products/${seg(item.match.subject_id)}/check`, {})
        if (!checked.lookup_id) throw new Error('The answer was not saved.')
        lookup = checked.lookup_id
      }
      if (onOpen) onOpen(lookup)
      else window.location.hash = `#/result/${encodeURIComponent(lookup)}`
    } catch (error) {
      setProblem(`${reason(error, 'The engine does not answer.')} The product could not be opened.`)
    } finally {
      setOpening(null)
    }
  }

  const download = (kind: 'xlsx' | 'csv') => {
    if (!table || !items) return
    const rows = resultRows(table, items, { csv: kind === 'csv', nameColumn: mapping.name })
    const name = `${slug(book?.fileName ?? 'list')}-checked`
    if (kind === 'xlsx') downloadFile(`${name}.xlsx`, xlsxOf([{ name: 'Checked list', rows }]), XLSX)
    // The byte order mark lets Excel read Turkish and other accented letters in a CSV.
    else downloadFile(`${name}.csv`, `﻿${csvOf(rows)}`, 'text/csv;charset=utf-8')
  }

  const live = mode === 'live'
  const count = prepared?.rows.length ?? 0

  return (
    <section className="k-screen" data-width="wide" aria-label="Check a list">
      <header className="k-head">
        <h1 className="k-title">Check a list</h1>
      </header>

      <ChooseFile
        name={book?.fileName ?? ''}
        detail={book ? detailOf(book) : ''}
        busy={reading}
        problem={fileProblem}
        onFile={(file) => void open(file)}
      />

      {book && table && (
        <MatchColumns
          tables={book.tables}
          sheetAt={sheetAt}
          table={table}
          mapping={mapping}
          onSheet={changeSheet}
          onMapping={changeMapping}
        />
      )}

      {book && table && mapping.name !== undefined && (
        <section className="k-group" aria-labelledby="checklist-step-check">
          <h2 className="k-caption" id="checklist-step-check">3. Check</h2>
          {mode === 'checking' || !live ? (
            <div className="k-empty">
              <strong>{mode === 'checking' ? 'Waiting for the engine' : 'Checking needs the engine'}</strong>
              <p>
                {mode === 'checking'
                  ? 'Kriko is starting. The check will be available in a moment.'
                  : 'The names are compared with your installed catalogs by the engine, and it is not running here. You can still read a file and preview it above.'}
              </p>
            </div>
          ) : (
            <div className="k-card" data-pad>
              <div className="checklist-check">
                {phase === 'checking' ? (
                  <>
                    <div className="checklist-progress">
                      <p className="checklist-status" role="status" aria-live="polite">
                        Checking {plural(count, 'product', 'products')} against your catalogs…
                      </p>
                      <div className="checklist-skeleton" aria-hidden="true">
                        <span /><span /><span />
                      </div>
                    </div>
                    <button type="button" className="k-btn" onClick={cancel}>Cancel</button>
                  </>
                ) : (
                  <>
                    <div className="checklist-check-text">
                      <span>
                        {count > 0
                          ? `${plural(count, 'row has', 'rows have')} a name and will be checked.`
                          : 'No row has a name in that column. Choose another column above.'}
                      </span>
                      {prepared && prepared.blank > 0 && count > 0 && (
                        <span className="checklist-hint">{plural(prepared.blank, 'row has', 'rows have')} no name and {prepared.blank === 1 ? 'is' : 'are'} skipped.</span>
                      )}
                      {prepared && prepared.cut > 0 && (
                        <span className="checklist-hint">
                          Only the first {MAX_NAMES} products are checked. {plural(prepared.cut, 'more row is', 'more rows are')} left out. Split the list to check them.
                        </span>
                      )}
                    </div>
                    <button
                      type="button"
                      className="k-btn"
                      data-kind={items ? undefined : 'primary'}
                      disabled={count === 0}
                      onClick={() => void check()}
                    >
                      {items ? `Check ${plural(count, 'product', 'products')} again` : `Check ${plural(count, 'product', 'products')}`}
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
          {note && <p className="checklist-status" role="status" aria-live="polite">{note}</p>}
          {problem && <p className="k-notice" data-tone="risk" role="alert">{problem}</p>}
        </section>
      )}

      {items && table && ran && (
        <section className="k-group" aria-labelledby="checklist-step-results">
          <div className="checklist-results-head">
            <h2 className="k-caption" id="checklist-step-results">4. Results</h2>
            <div className="k-head-actions">
              <button type="button" className="k-btn" data-size="sm" onClick={() => download('xlsx')}>Download results (.xlsx)</button>
              <button type="button" className="k-btn" data-size="sm" onClick={() => download('csv')}>Download results (.csv)</button>
              <button type="button" className="k-btn" data-kind="primary" data-size="sm" onClick={() => { setAdded(null); setAdding(true) }}>
                Add matched rows to an estimate
              </button>
            </div>
          </div>
          {ran.cut > 0 && (
            <p className="k-notice" data-tone="warn">
              Only the first {MAX_NAMES} products were checked. {plural(ran.cut, 'more row was', 'more rows were')} left out; the downloaded file says so on those rows.
            </p>
          )}
          {added && (
            <p className="k-notice" role="status">
              <span>
                Added {plural(added.created, 'line', 'lines')} to {added.name}
                {added.joined > 0 ? `, and quotes to ${plural(added.joined, 'line', 'lines')} already there` : ''}.
              </span>
              <button
                type="button"
                className="k-btn"
                data-size="sm"
                onClick={() => window.dispatchEvent(new CustomEvent('kriko:navigate', { detail: { screen: 'estimate' } }))}
              >
                Open it
              </button>
            </p>
          )}
          <Results
            items={items}
            filter={filter}
            order={order}
            opening={opening}
            onFilter={setFilter}
            onOrder={setOrder}
            onChoose={choose}
            onOpen={(item) => void openProduct(item)}
          />
        </section>
      )}

      {adding && items && table && (
        <AddDialog
          table={table}
          mapping={mapping}
          items={items}
          fileName={book?.fileName ?? ''}
          onClose={() => setAdding(false)}
          onSaved={(done) => { setAdding(false); setAdded(done) }}
        />
      )}
    </section>
  )
}

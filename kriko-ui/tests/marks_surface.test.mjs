import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

/**
 * Door 4: the reader's own marks, where the pack is already drawn.
 *
 * The extension writes and deletes marks (`extension/background.js`), and until
 * `GET /api/marks` had a caller the list was write-only from every screen this
 * window has. `docs/USAGE.md` refers to "the marks on results"; the route
 * returns the rows, the verdict counts and the verdict vocabulary, and nothing
 * else — no rating, no score, and no subject label beyond the snapshot the row
 * carries. These tests hold the client to exactly that shape and to the place
 * the pack's own counts are drawn.
 */

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')

/** A file outside the UI package: a route or the store's schema, read as the text it is. */
const repo = (path) => readFile(new URL(`../../${path}`, import.meta.url), 'utf8')

/** The columns of one table, read from the store's own schema. */
async function columns(table) {
  const state = await repo('src/app/web/state.py')
  const start = state.indexOf(`CREATE TABLE IF NOT EXISTS ${table} (`)
  const end = state.indexOf(');', start)
  assert.ok(start > -1 && end > start, `state.py no longer creates ${table}`)
  const block = state.slice(start, end)
  return [...block.matchAll(/^\s{4}([a-z_]+)\s+(?:TEXT|INTEGER)\b/gm)].map((one) => one[1])
}

test('every field the marks client names is a column the route returns', async () => {
  const found = await columns('claim_marks')
  assert.deepEqual(found, ['pack_id', 'claim_id', 'verdict', 'note', 'subject_id', 'title', 'created_at', 'updated_at'])

  const client = await read('src/engine/marks.ts')
  const interfaceBlock = client.slice(client.indexOf('export interface Mark {'), client.indexOf('export type MarkCounts'))
  assert.ok(interfaceBlock.length > 0, 'engine/marks.ts no longer declares the Mark shape')
  for (const column of found) {
    assert.match(interfaceBlock, new RegExp(`\\b${column}:`), `the client no longer carries claim_marks.${column}`)
  }
})

test('the client reads the route and invents no mark in demo', async () => {
  const client = await read('src/engine/marks.ts')

  const line = client.split('\n').find((one) => one.includes("'/api/marks?limit=200'"))
  assert.ok(line, 'the marks route is no longer read')
  assert.match(line, /get</)
  assert.match(client, /setMarks\(found\.items \?\? \[\]\)/)
  // A mark is the reader's own record; the window that has no engine draws
  // none rather than a stand-in row.
  assert.doesNotMatch(client, /DEMO/)
  assert.match(client, /if \(mode !== 'live'\) \{\s*setMarks\(null\)/)

  const route = await repo('src/app/web/routers/marks.py')
  assert.match(route, /"items": state\.marks\(conn, verdict=verdict, limit=limit\)/)
  assert.match(route, /"counts": state\.mark_counts\(conn\)/)
  assert.match(route, /"verdicts": list\(state\.VERDICTS\)/)
})

test('a mark is drawn on the catalog row, where that pack is already counted', async () => {
  const panel = await read('src/ui/panels/Catalogs.tsx')
  assert.ok(panel.includes('useMarks()'), 'the panel no longer reads the marks')

  const row = panel.slice(panel.indexOf('function CatalogRow'))
  assert.ok(row.length > 0, 'the panel no longer has a catalog row')
  for (const field of ['mark.verdict', 'mark.title', 'mark.note']) {
    assert.ok(row.includes(field), `the catalog row no longer draws ${field}`)
  }
  // The marks are keyed by the engine's pack id, so a row draws only its own.
  assert.match(panel, /marks=\{\(marks\.marks \?\? \[\]\)\.filter\(\(mark\) => mark\.pack_id === row\.id\)\}/)

  // The verdict is the engine's own id, written as a word: the set is never
  // restated in the interface.
  assert.match(panel, /const verdictWord = \(verdict: string\) => verdict\.replaceAll\('_', ' '\)/)
  // The denominator is the route's counts over the route's own verdict list,
  // and a verdict with none of its own is still printed as zero.
  assert.match(panel, /marks\.counts\[verdict\] \?\? 0/)
  assert.match(panel, /marks\.verdicts\.map\(/)
})

test('a mark that outlives its catalog is still shown, and nothing else is claimed', async () => {
  const panel = await read('src/ui/panels/Catalogs.tsx')

  // `claim_marks` snapshots `title` and `note` so the reader's words survive an
  // update or an uninstall; dropping the rows whose pack is gone would quietly
  // delete exactly those.
  assert.match(panel, /const orphans = \(marks\.marks \?\? \[\]\)\.filter\(\(mark\) => !packIds\.has\(mark\.pack_id\)\)/)
  assert.match(panel, /Marks from catalogs you no longer have/)
  assert.match(panel, /<strong>\{mark\.title \|\| mark\.claim_id\}<\/strong>/)

  // The route supports a verdict, the reader's words and the snapshots — and
  // nothing that would let the screen draw a score or a subject label it was
  // not sent. The panel draws no such figure.
  assert.doesNotMatch(panel, /mark\.(score|rating|subject_label|weight)\b/)
})

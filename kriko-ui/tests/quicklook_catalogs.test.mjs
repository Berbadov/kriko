import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

/**
 * Door 3: a saved quick look the engine could not classify keeps its open
 * question and takes a catalog only from the reader.
 *
 * `POST /api/quick-looks/{id}/categorize` spends an agent,
 * `POST /api/quick-looks/{id}/category` saves a reader's choice, and
 * `/api/history/records` is the only read that carries a look's job id, its
 * saved `categorization` and `categorization_catalogs` — the exact list the
 * category route validates against. `docs/USAGE.md` promises that a look with
 * missing classification or identity evidence "remains available for
 * follow-up" and that "filing is not permission to invent a catalog
 * assignment". These tests keep the abstention an open question and the
 * candidates the engine's list.
 */

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')

/** A file outside the UI package: a route or the store's schema, read as the text it is. */
const repo = (path) => readFile(new URL(`../../${path}`, import.meta.url), 'utf8')

function lineWith(source, needle) {
  const line = source.split('\n').find((one) => one.includes(needle))
  assert.ok(line, `no line carries ${needle}`)
  return line
}

let directory, looks
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-ui-quicklook-'))
  const code = await readFile('src/engine/looks.ts', 'utf8')
  const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  await writeFile(join(directory, 'looks.mjs'), built)
  looks = await import(pathToFileURL(join(directory, 'looks.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

test('an abstention stays an open question, and a decision stays the engine\'s', () => {
  const reply = {
    items: [
      {
        lookup_id: 'job:q1', label: 'Scyrox V7 Gaming Mouse', source: 'quick_look', status: 'succeeded',
        claim_count: 2, category: 'wireless pointer',
        categorization: {
          status: 'uncertain', pack_id: '', pack_name: '', method: 'deterministic',
          message: 'The saved category is not supported by the product title.',
        },
      },
      {
        lookup_id: 'job:q2', label: 'Scyrox V8 Gaming Mouse', source: 'quick_look', status: 'succeeded',
        claim_count: 1,
        categorization: { status: 'assigned', pack_id: 'gaming.mice', pack_name: 'Gaming mice', method: 'reader', message: 'Chosen by the reader.' },
      },
      // A saved check is not a quick look job, and neither category route takes it.
      { lookup_id: 'look-1', label: 'A saved check', source: 'lookup', status: 'succeeded', claim_count: 3 },
    ],
    categorization_catalogs: [{ pack_id: 'gaming.mice', name: 'Gaming mice', enabled: true, editable: true }],
  }

  const found = looks.savedLooks(reply)
  assert.equal(found.looks.length, 2)
  const [open, filed] = found.looks
  assert.equal(open.jobId, 'q1')
  // No catalog is drawn from an abstention, and the engine's sentence is kept.
  assert.equal(open.assignedTo, '')
  assert.equal(open.openQuestion, 'The saved category is not supported by the product title.')
  // The assignment is named by the engine, and so is how it was made.
  assert.equal(filed.assignedTo, 'Gaming mice')
  assert.equal(filed.decidedBy, 'reader')
  assert.equal(filed.openQuestion, '')
  // The candidate list is the engine's own, with the flag it sends.
  assert.deepEqual(found.catalogs, [{ pack_id: 'gaming.mice', name: 'Gaming mice', enabled: true, editable: true }])
})

test('a record without a categorization is still not a catalog decision', () => {
  const found = looks.savedLooks({
    items: [{ lookup_id: 'job:q3', label: 'Unnamed look', source: 'quick_look', status: 'succeeded', claim_count: 0 }],
  })
  assert.equal(found.looks[0].assignedTo, '')
  assert.equal(found.looks[0].openQuestion, '')
  assert.deepEqual(found.catalogs, [])
})

test('the two writes are the two routes, and the choices are the engine\'s list', async () => {
  const client = await read('src/engine/history.ts')
  assert.match(client, /post<\{[^}]*\}>\(\s*`\/api\/quick-looks\/\$\{seg\(jobId\)\}\/category`/)
  assert.match(lineWith(client, '/categorize`'), /post</)
  assert.match(client, /const reply = await get<unknown>\('\/api\/history\/records\?limit=200'\)/)

  const panel = await read('src/ui/panels/Catalogs.tsx')
  // Only a look the engine has not filed gets the choice.
  assert.match(panel, /const unfiled = \(saved\.looks \?\? \[\]\)\.filter\(\(look\) => look\.jobId && look\.status === 'succeeded' && !look\.assignedTo\)/)
  // The candidates are the route's `categorization_catalogs`, joined to the
  // panel's `useSavedLooks()` reply — not a second list and not a literal.
  assert.match(panel, /<SavedLookRow key=\{look\.id\} look=\{look\} catalogs=\{saved\.catalogs\}/)
  assert.match(panel, /\.\.\.catalogs\.map\(\(row\) => \(\{ value: row\.pack_id, label: row\.name \}\)\)/)
  // The engine's own reason is drawn where the choice is offered.
  assert.match(panel, /\{look\.openQuestion && <small className="look-question">\{look\.openQuestion\}<\/small>\}/)
  // Spending an agent is its own press, followed as a job like every other.
  assert.match(panel, /const started = await askAgentToCategorizeLook\(look\.jobId\)/)
  assert.match(panel, /followJob\(started\.job_id/)
  // The reader's press saves through the route that validates the choice.
  assert.match(panel, /const record = await assignSavedLook\(look\.jobId, pick\)/)
})

test('the category route validates against installed catalogs, which is the list the screen offers', async () => {
  const route = await repo('src/app/web/routers/history.py')
  const records = route.slice(route.indexOf('def history_records('), route.indexOf('class ManualCategoryRequest'))
  const manual = route.slice(route.indexOf('def assign_saved_quick_look_category('), route.indexOf('def get_lookup('))
  // `categorization_catalogs` is `categorizer.installed_catalogs`, and the
  // manual route passes the same profiles to `categorizer.manual` — one list,
  // two uses, which is why the screen may offer it as the candidates.
  assert.match(records, /profiles = categorizer\.installed_catalogs\(/)
  assert.match(records, /"categorization_catalogs": catalogs/)
  assert.match(manual, /profiles = categorizer\.installed_catalogs\(/)
  assert.match(manual, /assignment = categorizer\.manual\(body\.pack_id, profiles\)/)
})

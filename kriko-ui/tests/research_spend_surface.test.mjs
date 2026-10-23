import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

/**
 * Door 2: what each research run cost, what it produced, and the undo.
 *
 * `GET /api/research-runs` and `DELETE /api/research-runs/{id}` are the spend
 * surface `src/app/tests/test_research_spend_surface.py` names, and
 * `POST`/`GET` never had a caller in the window. These tests hold the three
 * things the screen must not get wrong: the undo is a job and is followed like
 * one, the confirm says in the reader's words what it takes out, and a figure
 * the plane could not meter is drawn as "not counted" rather than as zero.
 */

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')

/** A file outside the UI package: a route or the store's schema, read as the text it is. */
const repo = (path) => readFile(new URL(`../../${path}`, import.meta.url), 'utf8')

/** The one line of a module a literal sits on, so the verb beside it is read. */
function lineWith(source, needle) {
  const line = source.split('\n').find((one) => one.includes(needle))
  assert.ok(line, `no line carries ${needle}`)
  return line
}

test('the client reads the runs and the sums, and starts the undo as a job', async () => {
  const client = await read('src/engine/research.ts')

  assert.match(lineWith(client, "'/api/research-runs?limit=200'"), /get</)
  assert.match(lineWith(client, "'/api/usage'"), /get</)
  // One place names the route, and the id is the engine's, encoded once.
  assert.match(lineWith(client, '/api/research-runs/${seg(runId)}'), /del</)

  const panel = await read('src/ui/panels/History.tsx')
  assert.ok(panel.includes('useResearchRuns()'), 'the panel no longer reads the runs')
  assert.ok(panel.includes('undoResearchRun(run.run_id)'), 'the panel no longer starts the undo')
  // The route answers 202 with a job id, so the screen follows the handler's
  // own progress instead of claiming the claims are gone on the reply.
  assert.match(panel, /const started = await undoResearchRun\(run\.run_id\)[\s\S]{0,200}followJob\(started\.job_id/)
})

test('the undo is confirmed, in the reader\'s words, and says what it takes out', async () => {
  const panel = await read('src/ui/panels/History.tsx')

  // The number in the sentence is the engine's count, and the sentence names
  // the catalogs it writes to and the fact that it cannot be put back.
  assert.match(panel, /Undo this run\? It takes the \{counted\(run\.claims\)\}/)
  assert.match(panel, /back out of the catalogs that hold them\. Those claims cannot be put back\./)
  // Nothing to take out is no button, so an already-undone run cannot be
  // pressed into a second job that would remove nothing.
  assert.match(panel, /run\.claims > 0 \? \(/)
  // The reply's own account, not a sentence of our own.
  assert.match(panel, /\(ended\.result as \{ note\?: string \} \| null\)\?\.note/)
})

test('a figure the plane could not meter is "not counted", never zero', async () => {
  const panel = await read('src/ui/panels/History.tsx')

  // `cost()`/`count()` are the repository's one answer to a blank figure
  // (`engine/logformat.ts`: "not counted", tested in logs.test.mjs), and the
  // sentence for *why* a column is blank is the engine's own `metered` map.
  assert.match(panel, /import \{ cost, count as counted \} from '\.\.\/\.\.\/engine\/logformat'/)
  assert.match(panel, /cost\(run\.spent_usd\)/)
  assert.match(panel, /usage\?\.metered\.spent_usd/)
  // A failed `/api/usage` draws no total at all — a total of zero for a
  // question nobody answered is the figure this screen must not print.
  assert.match(panel, /const totals = usage && \[/)
  assert.doesNotMatch(panel, /toFixed\(\d\)/, 'the screen formats a cost itself')
})

test('every figure a run row draws is in the engine\'s run shape', async () => {
  const state = await repo('src/app/web/state.py')
  const block = state.slice(state.indexOf('def _research_run('), state.indexOf('def research_runs('))
  const panel = await read('src/ui/panels/History.tsx')

  // The wire shape `routers/research.py` serialises, field for field. A row
  // that drew a field the engine does not send would be an invented number.
  for (const field of ['run_id', 'plane', 'llm', 'search_provider', 'budget_usd', 'spent_usd', 'tokens_used', 'started_at', 'ended_at', 'outcome', 'claims', 'removed']) {
    assert.match(block, new RegExp(`"${field}"`), `state._research_run no longer carries ${field}`)
  }
  for (const field of ['plane', 'llm', 'spent_usd', 'tokens_used', 'started_at', 'outcome', 'claims', 'removed']) {
    assert.match(panel, new RegExp(`\\brun\\.${field}\\b`), `the run row no longer draws ${field}`)
  }
})

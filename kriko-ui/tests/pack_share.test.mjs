import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

/**
 * Door 1: the `.kpack` a harvest produced is shareable.
 *
 * `pack_harvest` already returns the engine's own path to each catalog artifact
 * (`src/app/web/tasks.py`: `"artifact": f"/api/packs/drafts/{slug}/artifact"`),
 * and `GET /api/packs/drafts/{slug}/artifact` serves it as
 * `application/octet-stream` under `{slug}.kpack`. The job result said so and
 * no screen drew it, so the link `CLAUDE.md` promises was reachable only by a
 * caller who already knew the route. These tests hold the two halves that make
 * the row honest: the panel shares the string the job sent, on the base every
 * call uses, and it never rewrites the route or the file name itself.
 */

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')

/** A file outside the UI package: a route or the store's schema, read as the text it is. */
const repo = (path) => readFile(new URL(`../../${path}`, import.meta.url), 'utf8')

let directory, harvest
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-ui-pack-share-'))
  const code = await readFile('src/engine/harvest.ts', 'utf8')
  const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  await writeFile(join(directory, 'harvest.mjs'), built)
  harvest = await import(pathToFileURL(join(directory, 'harvest.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

test('a harvest result shares exactly the artifacts its job sent, and nothing else', () => {
  const sent = {
    filed_quick_looks: ['q1'],
    claims_added: 2,
    packs: [{ slug: 'gaming-mice', pack_id: 'gaming.mice', name: 'Gaming mice', artifact: '/api/packs/drafts/gaming-mice/artifact' }],
  }
  assert.deepEqual(harvest.sharedPacks(sent), [
    { slug: 'gaming-mice', pack_id: 'gaming.mice', name: 'Gaming mice', artifact: '/api/packs/drafts/gaming-mice/artifact' },
  ])
  // A job that filed nothing, or a result without `packs` (an author run, a
  // failed job), shares nothing rather than offering a link to build later.
  assert.deepEqual(harvest.sharedPacks({ claims_added: 0, packs: [] }), [])
  assert.deepEqual(harvest.sharedPacks({ claims_added: 3 }), [])
  assert.deepEqual(harvest.sharedPacks(null), [])
  // A row whose artifact is not a string is not a link: the engine names the
  // file, and an empty name would draw a control that cannot download.
  assert.deepEqual(harvest.sharedPacks({ packs: [{ slug: 'x', name: 'X' }] }), [])
})

test('the .kpack row links the engine path on the one base every call uses', async () => {
  const api = await read('src/engine/api.ts')
  const panel = await read('src/ui/panels/Catalogs.tsx')

  // The base is the one `send()` already uses, and no host or port is written:
  // the engine binds an OS-chosen port (`app/sidecar.py`) and the page is
  // never told it, so a port here would be wrong on the next start.
  assert.match(api, /const BASE = \(import\.meta\.env\.VITE_ENGINE_BASE as string \| undefined\) \?\? ''/)
  assert.match(api, /export const engineUrl = \(path: string\) => BASE \+ path/)
  assert.doesNotMatch(api, /https?:\/\/(?:127\.0\.0\.1|localhost)|:8787|:\d{4,5}\b/)

  // The panel follows the job (the durable id the POST returned), reads the
  // result the job finished with, and links the row's own string.
  assert.match(panel, /const ended = await followJob\(/)
  assert.match(panel, /setShared\(sharedPacks\(ended\.result\)\)/)
  assert.match(panel, /<a\s+className="share-link"\s+href=\{engineUrl\(row\.artifact\)\}/)
  // The route is the engine's to name: the panel never writes `/artifact`, and
  // so cannot drift from `routers/packs.py` when the path changes.
  assert.doesNotMatch(panel, /\/artifact/)
})

test('the route serves a .kpack file, and the row leaves the file name to it', async () => {
  const route = await repo('src/app/web/routers/packs.py')
  assert.match(route, /media_type="application\/octet-stream"/)
  assert.match(route, /filename=f"\{slug\}\.kpack"/)

  const panel = await read('src/ui/panels/Catalogs.tsx')
  // No `download` attribute: the route's own `content-disposition` names the
  // file after its slug, and a second name here would be a second answer.
  assert.doesNotMatch(panel, /<a[^>]*\bdownload\b/)
})

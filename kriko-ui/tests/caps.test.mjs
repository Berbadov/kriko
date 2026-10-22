import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

let directory, caps, meters

before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-ui-caps-'))
  for (const [source, target] of [['src/engine/caprules.ts', 'caprules.mjs'], ['src/engine/usagemeters.ts', 'usagemeters.mjs']]) {
    const code = await readFile(source, 'utf8')
    const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
    await writeFile(join(directory, target), built.replace("'./usagemeters'", "'./usagemeters.mjs'"))
  }
  caps = await import(pathToFileURL(join(directory, 'caprules.mjs')))
  meters = await import(pathToFileURL(join(directory, 'usagemeters.mjs')))
})

after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const example = () => meters.demoMeters(1_000)

test('a cap says where today stands, in the unit the resource is counted in', () => {
  const read = example()
  assert.equal(caps.capLine(read, 'web_search', 50), '37 of 50 searches today')
  assert.equal(caps.capLine(read, 'llm_api', 1), '$0.21 of $1.00 spend today')
  assert.equal(caps.capLine(read, 'cli_agent', 20), '14 of 20 runs today')
})

test('no cap says nothing and is never "over"', () => {
  const read = example()
  assert.equal(caps.capLine(read, 'web_search', null), '')
  assert.equal(caps.overCap(read, 'web_search', null), false)
})

test('a cap is passed at the number, not after it', () => {
  const read = example()
  assert.equal(caps.overCap(read, 'web_search', 38), false)
  assert.equal(caps.overCap(read, 'web_search', 37), true)
  assert.equal(caps.overCap(read, 'llm_api', 0.2), true)
})

test('a cap with nothing counted says so, and is not over', () => {
  const read = example()
  assert.equal(caps.capLine(read, 'local_model', 10), '12 of 10 runs today')
  const empty = { ...read, resources: { ...read.resources, web_search: { ...read.resources.web_search, windows: { ...read.resources.web_search.windows, '24h': { ...read.resources.web_search.windows['24h'], calls: 0 } } } } }
  assert.equal(caps.capLine(empty, 'web_search', 10), '0 of 10 searches today')
  assert.equal(caps.overCap(empty, 'web_search', 10), false)
})

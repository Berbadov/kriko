import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

let directory, format
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-ui-format-'))
  const code = await readFile('src/ui/format.ts', 'utf8')
  const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  await writeFile(join(directory, 'format.mjs'), built)
  format = await import(pathToFileURL(join(directory, 'format.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

test('a duration never reads "60 s" at the end of a minute', () => {
  assert.equal(format.formatSeconds(0), '0.0 s')
  assert.equal(format.formatSeconds(9.94), '9.9 s')
  assert.equal(format.formatSeconds(9.96), '10 s')
  assert.equal(format.formatSeconds(59.4), '59 s')
  assert.equal(format.formatSeconds(59.6), '1 min 0 s')
  assert.equal(format.formatSeconds(119.4), '1 min 59 s')
  assert.equal(format.formatSeconds(119.6), '2 min 0 s')
  assert.equal(format.formatSeconds(3599.9), '1 h 0 min')
  assert.equal(format.formatSeconds(3601), '1 h 0 min')
  assert.equal(format.formatSeconds(-3), '0.0 s')
  assert.equal(format.formatSeconds(Number.NaN), '0.0 s')
})

test('a count of one takes the singular noun', () => {
  assert.equal(format.count(0, 'source'), '0 sources')
  assert.equal(format.count(1, 'source'), '1 source')
  assert.equal(format.count(2, 'source'), '2 sources')
  assert.equal(format.count(1, 'page'), '1 page')
  assert.equal(format.count(1, 'search result'), '1 search result')
  assert.equal(format.count(11, 'step'), '11 steps')
})

// A column the agents could not ground says so, and is never shown as "no
// risks".
//
// The engine already writes the sentence for this on the row
// (`response.diagnostic.message`: "No pages matched this exact product…",
// "Relevant pages were checked, but candidate findings did not pass the
// evidence checks…"). Compare's own head used to print "0 risks" over it,
// which reads as the claim the engine's coverage refuses to make.

import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

let directory, checks
const memory = new Map()

before(async () => {
  globalThis.window = { setTimeout, clearTimeout }
  globalThis.sessionStorage = {
    getItem: (key) => memory.get(key),
    setItem: (key, value) => memory.set(key, value),
    removeItem: (key) => memory.delete(key),
  }
  directory = await mkdtemp(join(process.cwd(), '.compare-findings-'))
  for (const [source, target] of [['src/engine/api.ts', 'api.mjs'],
                                  ['src/engine/thinness.ts', 'thinness.mjs'],
                                  ['src/compare/checks.ts', 'checks.mjs']]) {
    const built = ts.transpileModule(await readFile(source, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    }).outputText
    await writeFile(join(directory, target), built
      .replaceAll('import.meta.env', '({})')
      .replace("'../engine/api'", "'./api.mjs'")
      .replace("'../engine/thinness'", "'./thinness.mjs'"))
  }
  checks = await import(pathToFileURL(join(directory, 'checks.mjs')))
})

after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const column = (over = {}) => ({ lookupId: 'one', name: 'One', category: '', specs: [], risks: [], ...over })
const risk = { title: 'Heat under load', body: 'Only at full load', level: 'high', disputed: false, sources: [] }

test('a column with nothing kept quotes the engine instead of counting to zero', () => {
  const diagnostic = 'No pages matched this exact product. This is insufficient evidence to conclude that the product has no problems.'
  const ungrounded = column({ diagnostic })
  assert.equal(checks.groundingNote(ungrounded), diagnostic)
  assert.notEqual(checks.findingsLabel(ungrounded), '0 risks')
  assert.equal(checks.findingsLabel(ungrounded), 'No grounded findings')
})

test('a column that kept findings counts them as before', () => {
  const one = column({ risks: [risk] })
  assert.equal(checks.groundingNote(one), '', 'a diagnostic never displaces a kept finding')
  assert.equal(checks.findingsLabel(one), '1 risk')
  assert.equal(checks.findingsLabel(column({ risks: [risk, risk] })), '2 risks')
})

test('a row with no diagnostic says what is stored, not what the product lacks', () => {
  const silent = column()
  assert.equal(checks.groundingNote(silent), '')
  assert.equal(checks.findingsLabel(silent), 'No findings stored')
})

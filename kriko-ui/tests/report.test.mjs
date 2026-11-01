import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

// What the report section decides before it asks the engine anything.
let directory, report
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-ui-report-'))
  const code = await readFile('src/engine/reportformat.ts', 'utf8')
  const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  await writeFile(join(directory, 'reportformat.mjs'), built)
  report = await import(pathToFileURL(join(directory, 'reportformat.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const job = (over) => ({ job_id: 'j', kind: 'quick_look', label: 'Model 300', state: 'succeeded', errors: 0, ...over })

test('only runs that went wrong are offered, in the order given', () => {
  const jobs = [job({ job_id: 'a' }), job({ job_id: 'b', state: 'failed' }), job({ job_id: 'c', errors: 2 }), job({ job_id: 'd', state: 'interrupted' })]
  assert.deepEqual(report.reportable(jobs).map((one) => one.job_id), ['b', 'c', 'd'])
})

test('a run reads as what it was, what it was about and how it ended', () => {
  assert.equal(report.jobLabel(job({ state: 'failed' })), 'quick look · Model 300 · failed')
  assert.equal(report.jobLabel(job({ label: '' })), 'quick look · succeeded')
})

test('a suggestion never carries a run, and a problem may be only a run', () => {
  assert.deepEqual(report.askBody('suggestion', 'j', 'more agents'), { kind: 'suggestion', job_id: '', note: 'more agents' })
  assert.equal(report.askBody('error', 'j', '').job_id, 'j')
  assert.equal(report.canDraft('suggestion', 'j', '  '), false)
  assert.equal(report.canDraft('error', 'j', ''), true)
  assert.equal(report.canDraft('error', '', ''), false)
})

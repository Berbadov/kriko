import test from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { createRequire } from 'node:module'

const directory = await mkdtemp(join(process.cwd(), '.compare-saves-'))
const compiled = join(directory, 'researchSaves.cjs')
await writeFile(compiled, ts.transpileModule(await readFile('src/compare/researchSaves.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText)
const { ResearchSaves } = createRequire(import.meta.url)(compiled)
test.after(async () => rm(directory, { recursive: true, force: true }))

for (const state of ['failed', 'cancelled']) {
  test(`pending edits and a later save retain the original result after ${state} research`, async () => {
    const saves = new ResearchSaves()
    const release = saves.begin()
    const ids = ['right', 'original', 'added']
    let written
    const queued = saves.prepare(ids).then((value) => { written = value })
    await new Promise((resolve) => setImmediate(resolve))
    assert.equal(written, undefined, 'pending research cannot write an unfinished job ID')
    assert.deepEqual(ids, ['right', 'original', 'added'])
    saves.confirm('original', 'job', state, ['right', 'job', 'added'])
    release()
    await queued
    assert.deepEqual(written, ids)
    assert.deepEqual(await saves.prepare(['original', 'later']), ['original', 'later'])
  })
}

test('only confirmed success replaces the source in queued edits and preserves their order', async () => {
  const saves = new ResearchSaves()
  const release = saves.begin()
  const queued = saves.prepare(['right', 'original', 'added', 'left'])
  saves.confirm('original', 'job', 'running', ['right', 'job', 'left'])
  saves.confirm('original', 'job', 'succeeded', ['right', 'original', 'left'])
  saves.confirm('original', 'job', 'succeeded', ['right', 'job', 'left'])
  release()
  assert.deepEqual(await queued, ['right', 'job', 'added', 'left'])
  assert.deepEqual(await saves.prepare(['added', 'left']), ['added', 'left'], 'a removed source stays removed')
})

test('a success without a durable replacement cannot rewrite later saves', async () => {
  const saves = new ResearchSaves()
  const release = saves.begin()
  saves.confirm('original', 'job', 'succeeded', ['original'])
  release()
  assert.deepEqual(await saves.prepare(['original', 'added']), ['original', 'added'])
})

test('overlapping jobs hold saves until both settle and only successful sources change', async () => {
  const saves = new ResearchSaves()
  const first = saves.begin()
  const second = saves.begin()
  let written
  const queued = saves.prepare(['a', 'new', 'b']).then((value) => { written = value })
  saves.confirm('a', 'job-a', 'succeeded', ['job-a', 'b'])
  first()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(written, undefined)
  saves.confirm('b', 'job-b', 'cancelled', ['job-a', 'b'])
  second()
  await queued
  assert.deepEqual(written, ['job-a', 'new', 'b'])
})

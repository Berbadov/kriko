import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

// The log screen's plain functions: what a filter asks the engine, how a step
// and a total read, and what the plain text copy says. No window needed.
let directory, log
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-ui-logs-'))
  const code = await readFile('src/engine/logformat.ts', 'utf8')
  const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  await writeFile(join(directory, 'logformat.mjs'), built)
  log = await import(pathToFileURL(join(directory, 'logformat.mjs')))
})
after(async () => { if (directory) await rm(directory, { recursive: true, force: true }) })

const step = (over) => ({
  step_id: 1, job_id: 'j1', at: '2026-10-20T09:00:00.000Z', source: 'note', level: 'info', title: 'a step', state: 'done',
  ms: null, parent_id: null, tokens: null, usd: null, detail: {}, request_chars: 0, response_chars: 0, offset_ms: 0, gap_ms: null, depth: 0, ...over,
})

test('a filter becomes the query the engine understands, and an empty one asks for everything', () => {
  assert.equal(log.queryOf(log.NO_FILTER), '')
  const asked = log.queryOf({ job: 'a b', levels: ['warn', 'error'], sources: ['agent'], q: ' heat & cable ' }, { limit: '5' })
  assert.deepEqual(Object.fromEntries(new URLSearchParams(asked)), { job_id: 'a b', level: 'warn,error', source: 'agent', q: 'heat & cable', limit: '5' })
})

test('what was not counted is said so, and is never shown as nothing', () => {
  assert.equal(log.count(null), 'not counted')
  assert.equal(log.cost(null), 'not counted')
  assert.equal(log.cost(0), '$0.00')
  assert.equal(log.cost(0.0214), '$0.02')
  assert.equal(log.cost(0.0031), '$0.0031')
  assert.equal(log.cost(0.5, false), 'at least $0.50')
  assert.equal(log.span(null), '·')
  assert.equal(log.span(80), '80 ms')
  assert.equal(log.span(1234), '1.23 s')
  assert.equal(log.span(125000), '2 min 5 s')
})

test('a step says what was searched, whether its page was read, and what a call used', () => {
  const searched = log.facts(step({ source: 'search', detail: { queries: ['alpha heat', 'alpha cable'] } }))
  assert.deepEqual(searched, [['Searched for', 'alpha heat, alpha cable']])
  assert.deepEqual(log.facts(step({ source: 'page', detail: { urls: ['https://x.test/a'], read: false } })), [['Not read', 'https://x.test/a']])
  assert.deepEqual(log.facts(step({ source: 'page', detail: { urls: ['https://x.test/a'], read: true } })), [['Page', 'https://x.test/a']])
  const call = log.facts(step({ source: 'agent', tokens: 3180, usd: null, detail: { agent: 'coding', agent_label: 'Coding agent', model: 'm', attempt: 2, prompt_chars: 5210, reply_chars: 40 } }))
  assert.deepEqual(Object.fromEntries(call), {
    Attempt: '2', Agent: 'Coding agent · m', Prompt: '5,210 characters', Reply: '40 characters', Tokens: '3,180', Cost: 'not counted',
  })
})

test('the plain text copy lists each job and its steps in order', () => {
  const jobs = [{ job_id: 'j1', kind: 'research', label: 'Alpha', state: 'succeeded' }, { job_id: 'j2', kind: 'quick_look', label: 'Beta', state: 'failed' }]
  const text = log.plainText(jobs, [step({ title: 'first', offset_ms: 0 }), step({ step_id: 2, title: 'second', offset_ms: 1500, level: 'error' }), step({ step_id: 3, job_id: 'j2', title: 'other' })], false)
  assert.ok(text.indexOf('first') < text.indexOf('second') && text.indexOf('second') < text.indexOf('other'))
  assert.match(text, /\+1\.500s {2}ERROR/)
  assert.match(text, /job j2 {2}quick_look {2}Beta {2}\[failed\]/)
})

import test from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const directory = await mkdtemp(join(process.cwd(), '.compare-research-'))
const compiled = join(directory, 'research.cjs')
const source = await readFile('src/compare/research.ts', 'utf8')
await writeFile(compiled, ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText)
const { researchCompareSlot, selectCompareAgent, compareRecovery, ENGINE_CHOOSES } = require(compiled)

test.after(async () => rm(directory, { recursive: true, force: true }))

function setup({ currentIds = ['left', 'quick/job', 'right', 'added'], publishedIds, ended = { state: 'succeeded' }, wanted = true } = {}) {
  const calls = []
  let current = { draft_id: 'draft/one', name: 'Compare', lookup_ids: currentIds }
  const io = {
    start: async (path, body) => { calls.push(['start', path, body]); return { job_id: 'quick/job' } },
    follow: async (job, stillWanted) => { calls.push(['follow', job, stillWanted()]); return ended },
    drafts: async () => { calls.push(['drafts']); return { items: [current] } },
    waitForSaves: async () => { calls.push(['flush']) },
    pause: async () => {
      calls.push(['pause'])
      if (publishedIds) current = { ...current, lookup_ids: publishedIds }
    },
  }
  return { calls, io, get current() { return current }, wanted: () => wanted }
}

test('research sends the selected local agent and reconciles the latest draft order', async () => {
  const state = setup()
  let acceptedJob = ''
  const result = await researchCompareSlot('draft/one', 'old', { id: 'local', backend: 'local', label: 'Local' }, state.io, state.wanted, (id) => { acceptedJob = id })
  assert.deepEqual(state.calls[0], ['start', '/api/compare-drafts/draft%2Fone/research', { lookup_id: 'old', harness: 'local', backend: 'local' }])
  assert.equal(acceptedJob, 'quick/job')
  assert.deepEqual(result.lookup_ids, ['left', 'quick/job', 'right', 'added'])
  assert.equal(state.calls.some(([kind]) => kind === 'save'), false, 'the UI relies on the worker’s durable slot replacement')
})

test('research preserves a concurrent removal and does not resurrect its column', async () => {
  const state = setup({ currentIds: ['left', 'right', 'added'] })
  const result = await researchCompareSlot('draft/one', 'old', { id: 'codex', backend: 'harness', label: 'Codex' }, state.io, state.wanted, () => {})
  assert.deepEqual(result.lookup_ids, ['left', 'right', 'added'])
  assert.equal(state.calls.some(([kind]) => kind === 'save'), false)
})

test('research waits for the worker replacement and keeps its latest ordering', async () => {
  const state = setup({ currentIds: ['left', 'old', 'right'], publishedIds: ['right', 'quick/job', 'left'] })
  const result = await researchCompareSlot('draft/one', 'old', { id: 'codex', backend: 'harness', label: 'Codex' }, state.io, state.wanted, () => {})
  assert.deepEqual(result.lookup_ids, ['right', 'quick/job', 'left'])
  assert.equal(state.calls.filter(([kind]) => kind === 'drafts').length, 2)
  assert.equal(state.calls.some(([kind]) => kind === 'save'), false)
})

test('cancelled jobs surface their reason and do not refresh or replace the draft', async () => {
  const state = setup({ ended: { state: 'cancelled', message: 'Stopped by reader.' } })
  await assert.rejects(researchCompareSlot('draft/one', 'old', { id: 'codex', backend: 'harness', label: 'Codex' }, state.io, state.wanted, () => {}), /Stopped by reader/)
  assert.equal(state.calls.some(([kind]) => kind === 'drafts' || kind === 'save'), false)
})

test('unmount after the job poll stops before reading or mutating the board', async () => {
  const state = setup({ wanted: false })
  const result = await researchCompareSlot('draft/one', 'old', { id: 'codex', backend: 'harness', label: 'Codex' }, state.io, state.wanted, () => {})
  assert.equal(result, null)
  assert.equal(state.calls.some(([kind]) => kind === 'drafts' || kind === 'save'), false)
})

test('an unavailable saved agent never silently switches to another agent', () => {
  const roster = [
    { id: 'codex', backend: 'harness', label: 'Codex' },
    { id: 'local', backend: 'local', label: 'Local' },
  ]
  assert.equal(selectCompareAgent(roster, 'removed-agent', true), undefined)
  assert.equal(selectCompareAgent(roster, 'codex', true), roster[0])
  assert.equal(selectCompareAgent(roster, '', true), roster[0])
  assert.equal(selectCompareAgent(roster, 'codex', false), undefined)
})

test('a stored agent the engine did not list is offered the engine’s own roster', () => {
  // The observed dead end: `/api/agent-availability` reported the CLI roster
  // and a stored `preferred_harness` that was not in it, so every Compare
  // column said "Choose an available agent in Settings."
  const roster = [
    { id: 'codex', backend: 'harness', label: 'Codex' },
    { id: 'local', backend: 'local', label: 'Local' },
  ]
  const recovery = compareRecovery(roster, 'kriko-agent', true)
  assert.deepEqual(recovery.choices, roster, 'the rows are the engine’s, not a list written here')
  assert.equal(recovery.engineChooses, false)
  assert.match(recovery.note, /kriko-agent/, 'the stored pick is named the way the engine reported it')
  assert.doesNotMatch(recovery.note, /Settings/)
})

test('recovery never invents an agent the engine listed nothing of', () => {
  const engineDefault = compareRecovery([], 'kriko-agent', false)
  assert.deepEqual(engineDefault.choices, [], 'no agent is offered on the engine’s behalf')
  assert.equal(engineDefault.engineChooses, true, 'the press asks the engine to resolve one')
  assert.deepEqual(ENGINE_CHOOSES, { id: '', label: 'Default agent', backend: 'harness' },
    'the press sends the engine’s own "no pick named" shape')
})

test('the engine is left to refuse with its own words when it listed no agent', async () => {
  // The press has to reach the job: `harness_researcher` then either falls back
  // visibly or raises `NoHarness`, naming the CLIs looked for and the key the
  // API agent is missing. A validation error here would replace that sentence.
  const state = setup({ ended: { state: 'failed', message: 'NoHarness: no coding-agent CLI on PATH' } })
  await assert.rejects(
    researchCompareSlot('draft/one', 'old', ENGINE_CHOOSES, state.io, state.wanted, () => {}),
    /no coding-agent CLI on PATH/)
  assert.deepEqual(state.calls[0][2].harness, '')
  assert.deepEqual(state.calls[0][2].backend, 'harness')
})

test('a failed job reports the engine’s own message and never refreshes the board', async () => {
  const state = setup({ ended: { state: 'failed', message: 'The selected research agent is unavailable: Codex is not installed here.' } })
  await assert.rejects(
    researchCompareSlot('draft/one', 'old', { id: 'codex', backend: 'harness', label: 'Codex' }, state.io, state.wanted, () => {}),
    /Codex is not installed here/)
  assert.equal(state.calls.some(([kind]) => kind === 'drafts' || kind === 'save'), false,
    'a failed run leaves the column it could not replace')
})

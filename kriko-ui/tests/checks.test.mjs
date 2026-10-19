import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

let directory, checks, api
const memory = new Map()
before(async () => {
  globalThis.window = { setTimeout, clearTimeout }
  globalThis.sessionStorage = { getItem: (key) => memory.get(key), setItem: (key, value) => memory.set(key, value), removeItem: (key) => memory.delete(key) }
  directory = await mkdtemp(join(tmpdir(), 'kriko-ui-tests-'))
  for (const [source, target] of [['src/engine/api.ts','api.mjs'], ['src/compare/checks.ts','checks.mjs']]) {
    const code = await readFile(source, 'utf8')
    const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
    await writeFile(join(directory, target), built.replaceAll('import.meta.env', '({})').replace("'../engine/api'", "'./api.mjs'"))
  }
  checks = await import(pathToFileURL(join(directory, 'checks.mjs')))
  api = await import(pathToFileURL(join(directory, 'api.mjs')))
})
after(async () => { if (directory) await rm(directory, {recursive:true, force:true}) })

const reply = (value) => ({ status: 200, text: async () => JSON.stringify(value) })

test('an unfiled Quick Look keeps its specifications, source, coverage and exact variant', async () => {
  globalThis.fetch = async () => reply({ label: 'Model B', created_at: '2026-10-19T12:00:00Z', response: {
    assumed: 'EU revision B', coverage: { status: 'thin', pages_read: 1 }, diagnostic: { message: 'Only one source was readable.' },
    specs: [{ name: 'Weight', value: '2 kg', url: 'https://maker.example/manual', quote: 'Weight: 2 kg' }],
    claims: [{ title: 'Heat under load', body: 'Only at full load', applicability: 'conditional', advice: 'Check ventilation', sources: [{ url: 'https://maker.example/manual', quote: 'Allow ventilation' }] }],
  } })
  const loaded = await checks.loadCheck('saved-look')
  assert.equal(loaded.specs[0].value, '2 kg')
  assert.equal(loaded.specs[0].quote, 'Weight: 2 kg')
  assert.equal(loaded.specs[0].source, 'https://maker.example/manual')
  assert.equal(loaded.coverage.status, 'thin')
  assert.equal(loaded.assumed, 'EU revision B')
  assert.equal(loaded.risks[0].applicability, 'conditional')
})

test('an ambiguous match does not substitute the specifications of the product with more risks', async () => {
  const requested = []
  globalThis.fetch = async (path) => { requested.push(path); return reply({ response: { subjects: [{subject_id:'a',claims:1},{subject_id:'b',claims:50}], claims: [] } }) }
  assert.deepEqual((await checks.loadCheck('ambiguous')).specs, [])
  assert.equal(requested.length, 1)
})

test('comparison normalizes supported quantities while retaining real differences', () => {
  const base = {lookupId:'a', name:'A', category:'', risks:[], specs:[{label:'Weight',value:'2 kg',source:''}]}
  const equivalent = {...base, lookupId:'b', specs:[{label:'Weight',value:'2000 g',source:''}]}
  assert.equal(checks.specRows([base,equivalent])[0].differs, false)
  assert.notEqual(checks.comparableValue('2 kWh'), checks.comparableValue('2 kW'))
  const risk = {title:'Heat',body:'At full load',level:'high',disputed:false,sources:[],applicability:'conditional'}
  assert.equal(checks.riskRows([{...base,risks:[risk]},{...equivalent,risks:[{...risk,body:'At idle'}]}])[0].differs, true)
})

test('a lost send response reuses its request identity, while a completed intentional repeat gets a new one', async () => {
  const ids = []
  globalThis.fetch = async (_path, options) => {
    ids.push(JSON.parse(options.body).client_request_id)
    if (ids.length === 1) throw new Error('lost response')
    return reply({job_id:'same-job'})
  }
  const path = '/api/chat/threads/thread/messages'
  await assert.rejects(api.postQuestion(path, {text:'Find this product'}))
  await api.postQuestion(path, {text:'Find this product'})
  await api.postQuestion(path, {text:'Find this product'})
  assert.equal(ids[0], ids[1])
  assert.notEqual(ids[1], ids[2])
})

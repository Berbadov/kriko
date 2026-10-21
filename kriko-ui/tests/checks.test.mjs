import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

let directory, checks, api, thinness, view, steps, meters, pix
const memory = new Map()
before(async () => {
  globalThis.window = { setTimeout, clearTimeout }
  globalThis.sessionStorage = { getItem: (key) => memory.get(key), setItem: (key, value) => memory.set(key, value), removeItem: (key) => memory.delete(key) }
  directory = await mkdtemp(join(tmpdir(), 'kriko-ui-tests-'))
  for (const [source, target] of [['src/engine/api.ts','api.mjs'], ['src/engine/thinness.ts','thinness.mjs'], ['src/chat/view.ts','view.mjs'], ['src/compare/checks.ts','checks.mjs'], ['src/engine/steps.ts','steps.mjs'], ['src/engine/usagemeters.ts','usagemeters.mjs'], ['src/engine/pixicons.ts','pixicons.mjs']]) {
    const code = await readFile(source, 'utf8')
    const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
    await writeFile(join(directory, target), built.replaceAll('import.meta.env', '({})').replace("'../engine/api'", "'./api.mjs'").replace("'../engine/thinness'", "'./thinness.mjs'"))
  }
  checks = await import(pathToFileURL(join(directory, 'checks.mjs')))
  api = await import(pathToFileURL(join(directory, 'api.mjs')))
  thinness = await import(pathToFileURL(join(directory, 'thinness.mjs')))
  view = await import(pathToFileURL(join(directory, 'view.mjs')))
  steps = await import(pathToFileURL(join(directory, 'steps.mjs')))
  meters = await import(pathToFileURL(join(directory, 'usagemeters.mjs')))
  pix = await import(pathToFileURL(join(directory, 'pixicons.mjs')))
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

test('the sensitivity setting hides by level, counts what it hides, and never hides a claim that carries no doubt', () => {
  const levels = ['solid', 'partial', 'thin', undefined]
  const visible = (setting) => levels.filter((level) => thinness.shown(level, setting))
  assert.deepEqual(visible('all'), levels)
  assert.deepEqual(visible('hide_thin'), ['solid', 'partial', undefined])
  assert.deepEqual(visible('strict'), ['solid', undefined])
  assert.equal(thinness.hiddenCount(levels, 'hide_thin'), 1)
  assert.equal(thinness.hiddenCount(levels, 'strict'), 2)
  assert.equal(thinness.normalise('Hide-thin'), 'hide_thin')
  assert.equal(thinness.normalise('nonsense'), 'all')
  assert.equal(thinness.evidenceOf({ level: 'weird' }), undefined)
  assert.deepEqual(thinness.evidenceOf({ level: 'thin', reasons: [{ code: 'one_site', text: 'One site.' }, 7] }).reasons, [{ code: 'one_site', text: 'One site.' }])
})

test('the right column lists each page once in the order it was touched, and a lead nobody opened is not a source', () => {
  const activity = [
    { kind: 'search', url: 'https://lead.example/x', state: 'done' },
    { kind: 'read', url: 'https://a.example/p', state: 'failed' },
    { kind: 'read', url: 'https://b.example/q', state: 'done', trust: { label: 'Maker', domain: 'b.example', standing: 'trusted' } },
    { kind: 'read', url: 'https://a.example/p', state: 'done' },
  ]
  const pages = view.pagesFrom(activity, ['https://c.example/named'])
  assert.deepEqual(pages.map((page) => [page.host, page.read]), [['a.example', 'read'], ['b.example', 'read'], ['c.example', 'listed']])
  assert.equal(pages[1].standing, 'trusted')
})

test('the context bar warns from 70% and 90%, and a turn with no report says so instead of guessing', () => {
  assert.deepEqual([null, 0.5, 0.7, 0.89, 0.9].map(view.toneOf), ['ok', 'ok', 'amber', 'amber', 'red'])
  assert.equal(view.usageFrom(undefined), undefined)
  const usage = view.usageFrom({ tokens: 900, context: { state: 'not_reported', window: 4096 } })
  assert.equal(usage.tokensIn, null)
  assert.equal(view.turnLine(usage), '900 tokens (split not reported) · cost not reported')
  assert.equal(view.formatTokens(18400), '18.4K')
})

test('a claim source keeps where the engine stands it, and one it could not place carries none', async () => {
  globalThis.fetch = async () => reply({ label: 'Model C', created_at: '2026-10-19T12:00:00Z', response: {
    claims: [{ title: 'Heat under load', body: 'Only at full load', sources: [
      { url: 'https://maker.example/manual', domain: 'maker.example', quote: 'Allow ventilation', stance: 'supports', tier: 'manufacturer', standing: 'trusted' },
      { url: 'https://forum.example/t/1', domain: 'forum.example', quote: 'Mine runs hot', stance: 'supports', tier: 'forum_ugc', standing: 'low' },
      { url: 'https://odd.example/p', quote: 'Warm', standing: 'excellent' },
    ] }],
  } })
  const [first, second, third] = (await checks.loadCheck('saved-standing')).risks[0].sources
  assert.deepEqual([first.standing, first.tier], ['trusted', 'manufacturer'])
  assert.equal(second.standing, 'low')
  assert.equal(third.standing, undefined, 'a word the engine does not use is no mark')
})

test('the agent stepper reads its step from the reported progress, in quarters', () => {
  assert.deepEqual(steps.stepOf(0, 'waiting', 4), { at: -1, within: 0 }, 'a waiting run has no current step')
  assert.deepEqual(steps.stepOf(0.1, 'researching', 4), { at: 0, within: 0.4 })
  assert.equal(steps.stepOf(0.5, 'researching', 4).at, 2)
  assert.equal(steps.stepOf(0.99, 'paused', 4).at, 3, 'a paused run keeps its step')
  assert.deepEqual(steps.stepOf(0.3, 'done', 4), { at: 4, within: 1 }, 'a finished run is every step done')
  assert.equal(steps.stepOf(Number.NaN, 'researching', 4).at, 0, 'a progress the engine did not give is the first step')
  assert.equal(steps.stepOf(7, 'researching', 4).at, 3, 'progress past the end stays on the last step')
})

test('the usage card leaves out what was never used and what nobody reported', () => {
  const quiet = meters.demoMeters(1000)
  quiet.resources.local_model.used = false
  assert.deepEqual(meters.usedResources(quiet), ['cli_agent', 'llm_api', 'web_search'])
  assert.deepEqual(meters.usedResources(null), [])
  assert.equal(meters.left(null), null, 'no figure from the agent is no figure')
  assert.equal(meters.left(0.62), 0.38)
  assert.equal(meters.left(1.4), 0, 'a window over its limit has nothing left')
})

test('a coding agent window is called what the agent called it, and is never worked out', () => {
  assert.equal(meters.standingOf({ used: 0.3, status: 'allowed', resets_at: null, overage: null, seen_at: null }), 'ok')
  assert.equal(meters.standingOf({ used: 0.85, status: null, resets_at: null, overage: null, seen_at: null }), 'warn')
  assert.equal(meters.standingOf({ used: 0.97, status: null, resets_at: null, overage: null, seen_at: null }), 'out')
  assert.equal(meters.standingOf({ used: null, status: 'rejected', resets_at: null, overage: null, seen_at: null }), 'out', 'its word counts where it gave no figure')
  assert.equal(meters.standingOf({ used: null, status: 'allowed_warning', resets_at: null, overage: null, seen_at: null }), 'warn')
})

test('reset and report times are said in plain words', () => {
  assert.equal(meters.resetsIn(1000 + 2 * 3600 + 10 * 60, 1000), '2 h 10 min')
  assert.equal(meters.resetsIn(1000 + 45 * 60, 1000), '45 min')
  assert.equal(meters.resetsIn(900, 1000), 'now')
  assert.equal(meters.resetsIn(null, 1000), '')
  assert.equal(meters.ago(1000 - 14 * 60, 1000), '14 min ago')
  assert.equal(meters.ago(1000, 1000), 'just now')
  assert.equal(meters.ago(null, 1000), '')
})

test('the windows read in the order a reader thinks of them: 5 hours, week, then the rest', () => {
  const resource = { used: true, windows: {}, by_source: [], limits: { 'claude-code': {
    seven_day_opus: { used: 0.1, status: null, resets_at: null, overage: null, seen_at: 5 },
    seven_day: { used: 0.2, status: null, resets_at: null, overage: null, seen_at: 9 },
    five_hour: { used: 0.3, status: null, resets_at: null, overage: null, seen_at: 7 },
    odd_window: { used: null, status: 'allowed', resets_at: null, overage: null, seen_at: null },
  } } }
  const [agent] = meters.agentLimits(resource)
  assert.deepEqual(agent.windows.map((w) => w.id), ['five_hour', 'seven_day', 'seven_day_opus', 'odd_window'])
  assert.deepEqual(agent.windows.map((w) => w.label), ['5 hours', 'Week', 'Week, Opus', 'odd window'])
  assert.equal(agent.newest, 9)
  assert.deepEqual(meters.agentLimits(undefined), [])
})

test('the pill says the tightest window left and what the last day cost, and nothing it was not told', () => {
  const full = meters.pillParts(meters.demoMeters(1000))
  assert.equal(full.fill, 0.38, 'the tighter of 5 hours and the week')
  assert.equal(full.text, '$0.21 · 37 searches')
  const bare = meters.demoMeters(1000)
  bare.resources.cli_agent.limits = {}
  bare.resources.llm_api.windows['24h'].usd = null
  bare.resources.web_search.windows['24h'].calls = 0
  assert.deepEqual(meters.pillParts(bare), { fill: null, text: '' })
  assert.deepEqual(meters.pillParts(null), { fill: null, text: '' })
})

test('every agent mark is sixteen by sixteen, lit with the two cell kinds, and carries its signature square', () => {
  assert.deepEqual([...pix.PIX_NAMES].sort(), ['blocks', 'burst', 'chip', 'peak', 'pointer', 'prompt', 'spark'])
  for (const name of pix.PIX_NAMES) {
    const rows = pix.draw(name)
    assert.equal(rows.length, 16, `${name} has sixteen rows`)
    for (const row of rows) {
      assert.equal(row.length, 16, `${name} has sixteen cells in every row`)
      assert.match(row, /^[ #o]+$/, `${name} uses only empty, lit and signature cells`)
    }
    const lit = rows.join('').replaceAll(' ', '')
    assert.ok(lit.includes('o'), `${name} has a signature cell, as the logo has its square`)
    assert.ok(lit.length >= 16, `${name} draws something`)
  }
  assert.deepEqual(pix.draw('no-such-agent'), pix.draw('spark'), 'an unknown agent draws the fallback, never nothing')
})

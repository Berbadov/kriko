import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import ts from 'typescript'

/**
 * The dust engine, run without a screen. These check what the eye would: that
 * grains end up where a scene says dust belongs, that motion settings mean what
 * they say, and that a cursor pushes the cloud aside.
 */

async function load() {
  const source = await readFile(new URL('../src/dust/engine.ts', import.meta.url), 'utf8')
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  const dir = await mkdtemp(join(tmpdir(), 'dust-'))
  const file = join(dir, 'engine.mjs')
  await writeFile(file, js)
  try {
    return await import(file)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

const D = await load()

/** Mean density under the grains, against the mean density of the field. */
function fit(dust, scene) {
  let under = 0
  for (let i = 0; i < dust.count; i++) under += scene.density(dust.x[i], dust.y[i], dust.w, dust.h)
  let field = 0
  const n = 4000
  const r = D.rng(3)
  for (let i = 0; i < n; i++) field += scene.density(r() * dust.w, r() * dust.h, dust.w, dust.h)
  return { under: under / dust.count, field: field / n }
}

test('settled grains sit where the scene puts dust, not evenly', () => {
  const dust = new D.Dust({ count: 3000 })
  dust.resize(400, 300)
  for (const scene of [D.product('keyboard'), D.product('bike'), D.jack]) {
    dust.show(scene, { settle: true })
    const { under, field } = fit(dust, scene)
    assert.ok(under > field * 2, `${scene.name}: ${under.toFixed(3)} under the grains, ${field.toFixed(3)} on average`)
  }
})

test('moving grains gather into a new scene within a few seconds', () => {
  const dust = new D.Dust({ count: 2000 })
  dust.resize(400, 300)
  dust.show(D.reading, { settle: true })
  const scene = D.product('phone')
  dust.show(scene)
  for (let f = 0; f < 240; f++) dust.step(1, f / 60)
  const { under, field } = fit(dust, scene)
  assert.ok(under > field * 1.8, `after four seconds ${under.toFixed(3)} against ${field.toFixed(3)}`)
})

test('still moves nothing, calm moves less than full', () => {
  const spread = (motion) => {
    const dust = new D.Dust({ count: 500, seed: 11 })
    dust.resize(300, 300)
    dust.show(D.cloud(), { settle: true })
    const x0 = Float32Array.from(dust.x)
    for (let f = 0; f < 60; f++) dust.step(1, f / 60, motion)
    let moved = 0
    for (let i = 0; i < dust.count; i++) moved += Math.abs(dust.x[i] - x0[i])
    return moved / dust.count
  }
  assert.equal(spread('still'), 0)
  assert.ok(spread('calm') < spread('full'))
})

test('a cursor clears the dust around it', () => {
  const dust = new D.Dust({ count: 3000 })
  dust.resize(300, 300)
  dust.show(D.reading, { settle: true })
  const near = () => { let n = 0; for (let i = 0; i < dust.count; i++) if (Math.hypot(dust.x[i] - 150, dust.y[i] - 150) < 30) n++; return n }
  const before = near()
  dust.point(150, 150, 50)
  for (let f = 0; f < 30; f++) dust.step(1, f / 60)
  assert.ok(near() < before / 3, `${before} grains near the cursor before, ${near()} after`)
})

test('every grain is drawn exactly once', () => {
  const dust = new D.Dust({ count: 1234 })
  dust.resize(200, 120)
  dust.show(D.cloud(), { settle: true })
  const out = dust.buffers(10)
  dust.sort(out, { band: { y: 60, width: 20 } })
  assert.equal(out.counts.reduce((a, b) => a + b, 0), 1234)
})

test('a picture comes from generic product words, and a plain box otherwise', () => {
  assert.equal(D.kindFor('Logitech Bluetooth keyboard'), 'keyboard')
  assert.equal(D.kindFor('E-bike M', '2022'), 'bike')
  assert.equal(D.kindFor('Çamaşır makinesi 9 kg'), 'washer')
  assert.equal(D.kindFor('Battery range', 'electric-bikes'), 'bike')
  assert.equal(D.kindFor('Bosch', 'washing-machines'), 'washer')
  assert.equal(D.kindFor('Something nobody named'), 'box')
})

test('a field carries grains in proportion to its size, within a cap', () => {
  assert.equal(D.grainsFor(10, 10), 400)
  assert.equal(D.grainsFor(1200, 900), 26000)
  assert.equal(D.grainsFor(600, 240), 12000)
})

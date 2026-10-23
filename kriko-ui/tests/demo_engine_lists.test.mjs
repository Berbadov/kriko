import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

/**
 * Demo mode has no engine, so `engine/settings.ts` carries copies of two lists
 * the engine owns: the key providers, and the providers a shared-access code
 * carries. Both are drawn by panels that otherwise read the engine's reply
 * generically — so a copy that drifts is invisible on the live screen and only
 * wrong while the window says demo, which is exactly how the Keys list came to
 * be short by anthropic, mistral, mercury and the hosted page reader's
 * `parallel`.
 *
 * The engine declares each list; the demo window must show the same ones. These
 * are deliberate cross-boundary reads: the ids are one contract with two
 * declarations, and a test is what keeps two declarations equal.
 */

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')

/** The ids of the engine's `PROVIDERS` tuple, in the order it declares them. */
async function engineProviderIds() {
  const keys = await readFile(new URL('../../src/app/keys.py', import.meta.url), 'utf8')
  const start = keys.indexOf('PROVIDERS = (')
  const end = keys.indexOf('BY_ID =', start)
  assert.ok(start > -1 && end > start, 'app/keys.py no longer declares a PROVIDERS tuple')
  return [...keys.slice(start, end).matchAll(/^\s+id=["']([a-z0-9_-]+)["'],\s*$/gm)].map((one) => one[1])
}

/** The ids of the engine's `SHARED_PROVIDERS` tuple, in its order. */
async function engineSharedIds() {
  const share = await readFile(new URL('../../src/app/sharekeys.py', import.meta.url), 'utf8')
  const found = /^SHARED_PROVIDERS = \(([^)]*)\)/m.exec(share)
  assert.ok(found, 'app/sharekeys.py no longer declares SHARED_PROVIDERS')
  return [...found[1].matchAll(/["']([a-z0-9_-]+)["']/g)].map((one) => one[1])
}

test('the demo Keys panel draws the providers the engine declares, in its order', async () => {
  const ts = await read('src/engine/settings.ts')
  const start = ts.indexOf('const DEMO_KEYS')
  const end = ts.indexOf('export function usePrefsDoc', start)
  assert.ok(start > -1 && end > start, 'engine/settings.ts no longer declares DEMO_KEYS')
  const block = ts.slice(start, end)
  const from = block.indexOf('providers: [')
  assert.ok(from > -1, 'DEMO_KEYS has no providers list')
  const demo = [...block.slice(from).matchAll(/id: ['"]([a-z0-9_-]+)['"]/g)].map((one) => one[1])

  const engine = await engineProviderIds()
  // A guard on the reader, not on the answer: an empty read would make the
  // comparison below pass for the wrong reason.
  assert.ok(engine.length >= 8, `only ${engine.length} engine providers were read from app/keys.py`)

  // Both directions and the order: a provider the engine has and the demo lacks
  // is a row the reader cannot set, and one the demo invents is a promise the
  // engine does not make.
  assert.deepEqual(demo, engine, 'the demo window and the engine disagree about the key providers')
})

test('the demo shared-access grant names the providers the engine shares', async () => {
  const ts = await read('src/engine/settings.ts')
  // Only the plain lists, and only `providers` itself: the demo Keys doc declares
  // its rows as objects, and `search_providers` is another list entirely. An
  // empty list is a window with no grant yet, which names nothing and copies
  // nothing.
  const lists = [...ts.matchAll(/(?<![\w_])providers: \[([^\]{]*)\]/g)]
    .map((one) => [...one[1].matchAll(/['"]([a-z0-9_-]+)['"]/g)].map((id) => id[1]))
    .filter((list) => list.length > 0)
  assert.equal(lists.length, 2, 'the demo shared-access provider lists were not found')

  const engine = await engineSharedIds()
  assert.ok(engine.length >= 2, `only ${engine.length} shared providers were read from app/sharekeys.py`)
  for (const list of lists) {
    assert.deepEqual(list, engine, 'the demo grant and the engine disagree about the shared providers')
  }
})

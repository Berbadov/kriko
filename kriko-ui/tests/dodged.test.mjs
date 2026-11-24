// The Dodged ledger, from the window: the hook reads the list and the totals,
// keeps one press, and removes one row. The pure helpers decide which finding
// prefills the reason and how a saved total is written.

import test, { after, before } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'
import React from 'react'
import { createRoot } from 'react-dom/client'

const require = createRequire(import.meta.url)
let directory, helpers, useDodged, dom, root, listing, calls, failing
const originalLoad = require('node:module')._load

const api = {
  EngineError: class EngineError extends Error {
    constructor(status, message) {
      super(message)
      this.status = status
    }
  },
  get: async (path) => {
    if (path === '/api/buyer/dodged') return listing
    throw new Error(`unexpected request ${path}`)
  },
  post: async (path, body) => {
    if (failing) throw new api.EngineError(422, 'that price is not a number')
    calls.push(['POST', path, body])
    listing = { items: [{ ...body, price: Number(body.price), dodge_id: 'd2', decided_at: '2026-11-22T10:00:00+00:00' }, ...listing.items], totals: [], count: listing.count + 1, priced: listing.priced + 1 }
    return listing.items[0]
  },
  del: async (path) => {
    calls.push(['DELETE', path])
    listing = { ...listing, items: listing.items.filter((one) => one.dodge_id !== path.split('/').pop()) }
    return { deleted: true }
  },
  put: async () => ({}),
  seg: (id) => encodeURIComponent(id),
}

before(async () => {
  directory = await mkdtemp(join(process.cwd(), '.dodged-'))

  const pure = await readFile('src/engine/dodged.ts', 'utf8')
  const pureBuilt = ts.transpileModule(pure, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  await writeFile(join(directory, 'dodged.mjs'), pureBuilt)
  helpers = await import(pathToFileURL(join(directory, 'dodged.mjs')))

  const code = await readFile('src/engine/buyer.ts', 'utf8')
  const built = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText
  const buyerPath = join(directory, 'buyer.cjs')
  await writeFile(buyerPath, built)
  require('node:module')._load = function (request, parent, isMain) {
    if (parent?.filename === buyerPath) {
      if (request === './api') return api
      if (request === './Engine') return { useEngine: () => ({ mode: 'live' }) }
      if (request === './jobs') return { followJob: async () => null }
    }
    return originalLoad.call(this, request, parent, isMain)
  }
  ;({ useDodged } = require(buyerPath))
})

after(async () => {
  if (root) await React.act(async () => root.unmount())
  require('node:module')._load = originalLoad
  dom?.window.close()
  if (directory) await rm(directory, { recursive: true, force: true })
})

async function mount() {
  calls = []
  failing = false
  listing = {
    items: [{ dodge_id: 'd1', name: 'Kettle', url: '', price: 49.9, currency: 'EUR', reason: 'hinge', decided_at: '2026-11-21T10:00:00+00:00' }],
    totals: [{ currency: 'EUR', amount: 49.9, count: 1, priced: 1 }],
    count: 1,
    priced: 1,
  }
  dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://localhost/' })
  globalThis.window = dom.window
  globalThis.document = dom.window.document
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  let current
  function Probe() {
    current = useDodged()
    return React.createElement('output', null, String(current.count))
  }
  const { act } = React
  root = createRoot(dom.window.document.getElementById('root'))
  await act(async () => {
    root.render(React.createElement(Probe))
    await new Promise((resolve) => setImmediate(resolve))
  })
  return () => current
}

test('the gravest finding is the one that prefills the reason', () => {
  const concern = (title, level) => ({ title, level, body: '', disputed: false, sources: [] })
  assert.equal(helpers.strongestConcern([concern('Low noise', 'low'), concern('Hinge snaps', 'critical'), concern('Battery', 'high')]), 'Hinge snaps')
  assert.equal(helpers.strongestConcern([concern('Unrated', 'unrated')]), 'Unrated')
  assert.equal(helpers.strongestConcern([]), '')
})

test('a total is written with its currency only when it has one', () => {
  assert.match(helpers.moneyText(1234.5, 'EUR'), /234\.5 EUR$/)
  assert.match(helpers.moneyText(20, ''), /^20$/)
})

test('the hook reads the list, the per-currency total and the count', async () => {
  const read = await mount()
  assert.equal(read().count, 1)
  assert.equal(read().priced, 1)
  assert.deepEqual(read().totals, [{ currency: 'EUR', amount: 49.9, count: 1, priced: 1 }])
  assert.equal(read().items[0].name, 'Kettle')
})

test('keeping a dodge posts one line and reloads the ledger', async () => {
  const read = await mount()
  const { act } = React
  let kept
  await act(async () => {
    kept = await read().add(' Kettle Pro ', '49.90', 'EUR', '  hinge cracks ', 'https://shop.test/k')
  })
  assert.equal(kept, true)
  assert.deepEqual(calls, [['POST', '/api/buyer/dodged', { name: 'Kettle Pro', price: '49.90', currency: 'EUR', reason: 'hinge cracks', url: 'https://shop.test/k' }]])
  assert.equal(read().count, 2, 'the list is read again, not patched in place')
})

test('a price left empty is sent as null, never as zero', async () => {
  const read = await mount()
  const { act } = React
  await act(async () => {
    await read().add('Kettle', '  ', '', '', '')
  })
  assert.deepEqual(calls[0][2], { name: 'Kettle', price: null, currency: '', reason: '', url: '' })
})

test('a refused dodge keeps the form open and says why', async () => {
  const read = await mount()
  const { act } = React
  let kept
  failing = true
  await act(async () => {
    kept = await read().add('Kettle', 'abc', 'EUR', '', '')
  })
  assert.equal(kept, false)
  assert.equal(read().problem, 'that price is not a number')
})

test('removing a dodge is one delete and a reload', async () => {
  const read = await mount()
  const { act } = React
  let removed
  await act(async () => {
    removed = await read().forget('d1')
  })
  assert.equal(removed, true)
  assert.deepEqual(calls, [['DELETE', '/api/buyer/dodged/d1']])
  assert.equal(read().items.length, 0)
})

test('the screen and the product surface are wired to the hook', async () => {
  const app = await readFile('src/App.tsx', 'utf8')
  const topbar = await readFile('src/ui/TopBar.tsx', 'utf8')
  const product = await readFile('src/screens/Product.tsx', 'utf8')
  const screen = await readFile('src/screens/Dodged.tsx', 'utf8')
  assert.ok(app.includes('<DodgedScreen />'), 'App does not render the Dodged screen')
  assert.ok(topbar.includes("id: 'dodged'"), 'the top bar does not offer Dodged')
  assert.ok(product.includes('<DodgeDialog') && product.includes('Not buying this'), 'the product page cannot record a dodge')
  assert.ok(product.includes('<UsedCard'), 'the product page does not show the secondhand card')
  assert.ok(screen.includes('Money saved') && screen.includes('dodged.forget'), 'the screen does not show the total and a remove action')
})

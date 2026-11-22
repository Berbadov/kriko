// Prices: "Add as a quote" on a watch, and the price history drawn from its reads.
//
// A watch is a page, not a catalog product, so the dialog asks which product
// the price is for, remembers the answer, and creates the same quote the
// Estimate screen would (vendor = the page's host, the page's own price, today,
// default VAT). The history never invents a point: the line is drawn through
// the reads it was given and nothing between them.
//
// The real modules are compiled and imported. Only the HTTP layer and the
// engine context are stubbed, so the saves and reads asserted are the app's own.

import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { basename, join } from 'node:path'
import { createRequire } from 'node:module'
import { JSDOM } from 'jsdom'
import React from 'react'

const require = createRequire(import.meta.url)
const Module = require('node:module')
const originalLoad = Module._load

let directory
let files
const routes = { get: null, post: null }
const apiStub = {
  seg: (id) => encodeURIComponent(id),
  get: (path) => routes.get(path),
  post: (path, body) => routes.post(path, body),
  del: async () => ({}),
}
let engineMode = 'live'
const engineStub = { useEngine: () => ({ mode: engineMode }) }

const saved = { window: globalThis.window, document: globalThis.document, Event: globalThis.Event, CustomEvent: globalThis.CustomEvent }

before(async () => {
  directory = await mkdtemp(join(process.cwd(), '.prices-quote-test-'))
  const compile = async (source, name) => {
    const code = await readFile(source, 'utf8')
    const out = ts.transpileModule(code, {
      fileName: source,
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
    }).outputText
    const path = join(directory, `${name}.cjs`)
    await writeFile(path, out)
    return path
  }
  files = {
    money: await compile('src/engine/money.ts', 'money'),
    format: await compile('src/ui/format.ts', 'format'),
    figures: await compile('src/compare/figures.ts', 'figures'),
    estimates: await compile('src/engine/estimates.ts', 'estimates'),
    procurement: await compile('src/engine/procurement.ts', 'procurement'),
    priceHistory: await compile('src/screens/prices/priceHistory.ts', 'priceHistory'),
    watchHistory: await compile('src/screens/prices/watchHistory.ts', 'watchHistory'),
    watchSubjects: await compile('src/screens/prices/watchSubjects.ts', 'watchSubjects'),
    quoteRequest: await compile('src/screens/prices/quoteRequest.ts', 'quoteRequest'),
    WatchQuote: await compile('src/screens/prices/WatchQuote.tsx', 'WatchQuote'),
  }
  Module._load = function (request, parent, isMain) {
    if (parent?.filename?.startsWith(directory) && request.startsWith('.')) {
      const base = basename(request).replace(/\.(tsx?|cjs)$/, '')
      if (base === 'api') return apiStub
      if (base === 'Engine') return engineStub
      if (base in files) return require(files[base])
    }
    return originalLoad.call(this, request, parent, isMain)
  }
  globalThis.window = new EventTarget()
})

after(async () => {
  Module._load = originalLoad
  Object.assign(globalThis, saved)
  if (directory) await rm(directory, { recursive: true, force: true })
})

// ── fixtures ──

const isoDay = (date) => {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

const watch = (over = {}) => ({
  watch_id: 'w1', url: 'https://www.shop.example/p/pump-9?utm_source=ad', name: 'Pump 9 at Shop', currency: 'EUR',
  target: null, started_price: 130, last_price: 120, last_checked: '2026-11-19T10:00:00+00:00', last_error: '', cloud: 0, ...over,
})

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function mountDom(render) {
  const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://localhost/' })
  globalThis.window = dom.window
  globalThis.document = dom.window.document
  globalThis.Event = dom.window.Event
  globalThis.CustomEvent = dom.window.CustomEvent
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const { createRoot } = require('react-dom/client')
  const root = createRoot(dom.window.document.getElementById('root'))
  const flush = () => React.act(async () => { await wait(0) })
  await React.act(async () => root.render(render()))
  return {
    dom,
    document: dom.window.document,
    flush,
    act: (fn) => React.act(async () => fn()),
    unmount: async () => { await React.act(async () => root.unmount()); dom.window.close() },
  }
}

/** The engine's answers: the estimates, the catalog search, and the saves. */
function serve() {
  const calls = []
  const saves = []
  routes.get = (path) => {
    calls.push(path)
    if (path === '/api/estimates?limit=100') {
      return Promise.resolve({ items: [
        { estimate_id: 'e1', name: 'Pumps', currency: 'TRY', lines_count: 1, updated_at: '2026-11-02' },
        { estimate_id: 'e2', name: 'Lab', currency: 'USD', lines_count: 0, updated_at: '2026-11-01' },
      ] })
    }
    if (path === '/api/estimates/e1') return Promise.resolve({ estimate: { estimate_id: 'e1', name: 'Pumps', currency: 'TRY', years: 5, maintenance_pct: 5, discount_pct: 8, vat_rate: 20, fx: {}, lines: [] } })
    if (path.startsWith('/api/search?q=')) return Promise.resolve({ items: [{ subject_id: 'pump-9', pack_id: 'pumps', label: 'Pump 9' }, { subject_id: 'pump-10', pack_id: 'pumps', label: 'Pump 10' }] })
    return Promise.reject(new Error(`unexpected read ${path}`))
  }
  routes.post = (path, body) => {
    calls.push(`POST ${path}`)
    saves.push(body)
    return Promise.resolve({ estimate: { ...body, estimate_id: body.estimate_id || 'new-1', fx: body.fx ?? {}, lines: body.lines.map((item, i) => ({ ...item, line_id: `l${i}` })) } })
  }
  return { calls, saves }
}

const type = async (view, node, value) => {
  const proto = node.tagName === 'SELECT' ? view.dom.window.HTMLSelectElement.prototype : view.dom.window.HTMLInputElement.prototype
  const set = Object.getOwnPropertyDescriptor(proto, 'value').set
  await view.act(() => {
    set.call(node, value)
    node.dispatchEvent(new view.dom.window.Event(node.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
  })
}

const buttonNamed = (document, text) => [...document.querySelectorAll('button')].find((node) => node.textContent === text)

// ── the button and its reasons ──

test('the button is disabled in plain words when the page has no price, and when the engine is not live', async () => {
  const { WatchQuote } = require(files.WatchQuote)
  serve()
  engineMode = 'live'
  let view = await mountDom(() => React.createElement(WatchQuote, { watch: watch({ last_price: null }) }))
  try {
    const button = buttonNamed(view.document, 'Add as a quote')
    assert.equal(button.disabled, true)
    assert.ok(view.document.body.textContent.includes('This page has no price yet. Check it first.'))
    assert.equal(button.getAttribute('aria-describedby') != null, true, 'the reason is tied to the button')
    await view.act(() => button.click())
    assert.equal(view.document.querySelector('[role="dialog"]'), null)
  } finally {
    await view.unmount()
  }
  engineMode = 'demo'
  view = await mountDom(() => React.createElement(WatchQuote, { watch: watch() }))
  try {
    assert.equal(buttonNamed(view.document, 'Add as a quote').disabled, true)
    assert.ok(view.document.body.textContent.includes('Needs the engine.'))
  } finally {
    await view.unmount()
    engineMode = 'live'
  }
})

// ── the dialog ──

test('the dialog is labelled, takes focus, and Escape closes it with focus back on the button', async () => {
  engineMode = 'live'
  serve()
  const { WatchQuote } = require(files.WatchQuote)
  const view = await mountDom(() => React.createElement(WatchQuote, { watch: watch() }))
  try {
    const { document, act, flush } = view
    const button = buttonNamed(document, 'Add as a quote')
    assert.equal(button.disabled, false)
    await act(() => button.click())
    await flush()
    const dialog = document.querySelector('[role="dialog"]')
    assert.ok(dialog)
    assert.equal(document.getElementById(dialog.getAttribute('aria-labelledby')).textContent, 'Add as a quote')
    assert.equal(document.activeElement, dialog)
    await act(() => dialog.dispatchEvent(new view.dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    assert.equal(document.querySelector('[role="dialog"]'), null)
    assert.equal(document.activeElement, button)
  } finally {
    await view.unmount()
  }
})

test('searching, choosing a product and an estimate creates the page\'s own price as a quote, and remembers the product', async () => {
  engineMode = 'live'
  const { calls, saves } = serve()
  const { WatchQuote } = require(files.WatchQuote)
  const { WATCH_SUBJECTS_KEY } = require(files.watchSubjects)
  const view = await mountDom(() => React.createElement(WatchQuote, { watch: watch() }))
  const navigations = []
  view.dom.window.addEventListener('kriko:navigate', (event) => navigations.push(event.detail))
  try {
    const { document, act, flush } = view
    await act(() => buttonNamed(document, 'Add as a quote').click())
    await flush()
    assert.equal(buttonNamed(document, 'Add quote').disabled, true, 'no product yet')
    assert.ok(document.body.textContent.includes('Choose the product this price is for.'))

    await type(view, document.querySelector('[role="dialog"] input[type="search"]'), 'pump')
    await act(() => wait(320))
    await flush()
    assert.ok(calls.includes('/api/search?q=pump&limit=12'), 'the catalogs are searched with /api/search')
    const hit = [...document.querySelectorAll('.prices-hit')].find((node) => node.textContent.includes('Pump 9'))
    await act(() => hit.click())

    const preview = document.querySelector('[aria-label="The quote that will be created"]').textContent
    assert.ok(preview.includes('shop.example') && !preview.includes('www.'), 'the vendor is the host of the page')
    assert.ok(preview.includes('120 EUR'), 'the price is the watch\'s last price in its currency')
    assert.ok(preview.includes(isoDay(new Date())), 'dated today')
    assert.match(document.body.textContent, /page's own figure/)
    assert.match(document.body.textContent, /VAT is the default: 20%, included/)

    const add = buttonNamed(document, 'Add quote')
    assert.equal(add.disabled, false)
    await type(view, document.querySelector('[role="dialog"] input[type="number"]'), '3')
    await act(() => add.click())
    await flush()

    assert.equal(saves.length, 1)
    const body = saves[0]
    assert.equal(body.estimate_id, 'e1', 'the first estimate is the default')
    const added = body.lines.at(-1)
    assert.equal(added.subject_id, 'pump-9')
    assert.equal(added.pack_id, 'pumps')
    assert.equal(added.quantity, 3)
    assert.equal(added.quotes.length, 1)
    const quote = added.quotes[0]
    assert.equal(quote.vendor, 'shop.example')
    assert.equal(quote.unit_price, 120)
    assert.equal(quote.currency, 'EUR')
    assert.equal(quote.vat_rate, 20)
    assert.equal(quote.vat_included, true)
    assert.equal(quote.quote_date, isoDay(new Date()))
    assert.equal(quote.selected, true)

    assert.ok(document.body.textContent.includes('Added to Pumps.'))
    await act(() => buttonNamed(document, 'Open it').click())
    assert.deepEqual(navigations, [{ screen: 'estimate' }])

    const kept = JSON.parse(view.dom.window.localStorage.getItem(WATCH_SUBJECTS_KEY))
    assert.deepEqual(kept, { w1: { subject_id: 'pump-9', pack_id: 'pumps', label: 'Pump 9' } })
  } finally {
    await view.unmount()
  }
})

test('the next press skips the search: the remembered product is already chosen, and it can be changed', async () => {
  engineMode = 'live'
  const { calls } = serve()
  const { WatchQuote } = require(files.WatchQuote)
  const { WATCH_SUBJECTS_KEY } = require(files.watchSubjects)
  const view = await mountDom(() => React.createElement(WatchQuote, { watch: watch() }))
  try {
    const { document, act, flush } = view
    view.dom.window.localStorage.setItem(WATCH_SUBJECTS_KEY, JSON.stringify({ w1: { subject_id: 'pump-9', pack_id: 'pumps', label: 'Pump 9' } }))
    await act(() => buttonNamed(document, 'Add as a quote').click())
    await flush()
    assert.equal(document.querySelector('[role="dialog"] input[type="search"]'), null, 'no search field')
    assert.ok(document.querySelector('.prices-chosen').textContent.includes('Pump 9'))
    assert.equal(buttonNamed(document, 'Add quote').disabled, false)
    assert.ok(!calls.some((path) => path.startsWith('/api/search')))
    await act(() => buttonNamed(document, 'Change product').click())
    assert.ok(document.querySelector('[role="dialog"] input[type="search"]'), 'the search is back')
    assert.equal(view.dom.window.localStorage.getItem(WATCH_SUBJECTS_KEY), '{}')
  } finally {
    await view.unmount()
  }
})

test('a watch with no currency asks for one and does not add until it is chosen', async () => {
  engineMode = 'live'
  const { saves } = serve()
  const { WatchQuote } = require(files.WatchQuote)
  const { WATCH_SUBJECTS_KEY } = require(files.watchSubjects)
  const view = await mountDom(() => React.createElement(WatchQuote, { watch: watch({ currency: '' }) }))
  try {
    const { document, act, flush } = view
    view.dom.window.localStorage.setItem(WATCH_SUBJECTS_KEY, JSON.stringify({ w1: { subject_id: 'pump-9', pack_id: 'pumps', label: 'Pump 9' } }))
    await act(() => buttonNamed(document, 'Add as a quote').click())
    await flush()
    const select = [...document.querySelectorAll('[role="dialog"] select')].find((node) => [...node.options].some((option) => option.value === 'TRY'))
    assert.deepEqual([...select.options].map((option) => option.value), ['', 'TRY', 'EUR', 'USD'])
    assert.equal(buttonNamed(document, 'Add quote').disabled, true)
    assert.ok(document.body.textContent.includes('Choose the currency of the price.'))
    await type(view, select, 'USD')
    await act(() => buttonNamed(document, 'Add quote').click())
    await flush()
    assert.equal(saves[0].lines.at(-1).quotes[0].currency, 'USD')
    assert.equal(saves[0].lines.at(-1).quotes[0].unit_price, 120)
  } finally {
    await view.unmount()
  }
})

test('a new estimate can be named instead, and an engine failure is said in the dialog', async () => {
  engineMode = 'live'
  const { saves } = serve()
  const { WatchQuote } = require(files.WatchQuote)
  const { WATCH_SUBJECTS_KEY } = require(files.watchSubjects)
  const view = await mountDom(() => React.createElement(WatchQuote, { watch: watch() }))
  try {
    const { document, act, flush } = view
    view.dom.window.localStorage.setItem(WATCH_SUBJECTS_KEY, JSON.stringify({ w1: { subject_id: 'pump-9', pack_id: 'pumps', label: 'Pump 9' } }))
    await act(() => buttonNamed(document, 'Add as a quote').click())
    await flush()
    await type(view, document.querySelector('[role="dialog"] select'), '__new')
    await type(view, document.querySelector('[role="dialog"] input[placeholder="Untitled estimate"]'), 'Winter')
    routes.post = () => Promise.reject(new Error('The engine said no.'))
    await act(() => buttonNamed(document, 'Add quote').click())
    await flush()
    assert.ok(document.querySelector('[role="alert"]').textContent.includes('The engine said no.'))
    routes.post = (path, body) => { saves.push(body); return Promise.resolve({ estimate: { ...body, estimate_id: 'n', lines: [] } }) }
    await act(() => buttonNamed(document, 'Add quote').click())
    await flush()
    assert.equal(saves.at(-1).name, 'Winter')
    assert.ok(document.body.textContent.includes('Added to Winter.'))
  } finally {
    await view.unmount()
  }
})

test('the remembered product survives blocked storage: nothing throws and nothing is remembered', () => {
  const { readWatchSubjects, rememberWatchSubject, forgetWatchSubject } = require(files.watchSubjects)
  globalThis.window = { localStorage: { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } } }
  assert.deepEqual(readWatchSubjects(), {})
  assert.doesNotThrow(() => rememberWatchSubject('w1', { subject_id: 's', pack_id: 'p', label: 'L' }))
  assert.doesNotThrow(() => forgetWatchSubject('w1'))
  globalThis.window = { localStorage: { getItem: () => '{"w1":{"subject_id":"s"},"w2":"x","w3":{"subject_id":"a","pack_id":"b","label":"c"}}', setItem: () => {} } }
  assert.deepEqual(readWatchSubjects(), { w3: { subject_id: 'a', pack_id: 'b', label: 'c' } }, 'a malformed entry is dropped, not trusted')
})

// ── the history ──

test('the sparkline puts the lowest read on the bottom edge, the highest on the top, and the last read at the right', () => {
  const { sparkline } = require(files.priceHistory)
  const spark = sparkline([120, 100, 110], 120, 28, 3)
  assert.equal(spark.points.length, 3, 'one point per read and nothing between them')
  assert.deepEqual(spark.points.map((point) => point.x), [3, 60, 117])
  assert.deepEqual(spark.points.map((point) => point.y), [3, 25, 14])
  assert.equal(spark.path, 'M3 3 L60 25 L117 14')
  assert.deepEqual(spark.last, { x: 117, y: 14 })
})

test('a flat series is a level line, and fewer than two reads draw nothing', () => {
  const { sparkline } = require(files.priceHistory)
  const flat = sparkline([50, 50, 50], 120, 28, 3)
  assert.deepEqual(new Set(flat.points.map((point) => point.y)), new Set([14]))
  assert.deepEqual(sparkline([50]), { path: '', last: null, points: [] })
  assert.deepEqual(sparkline([]), { path: '', last: null, points: [] })
  assert.equal(sparkline([10, Number.NaN, 20]).points.length, 2, 'a value that is not a number is not a point')
})

const history = (prices, currency = 'TRY') => ({
  items: prices.map((price, i) => ({ price, currency, seen_at: `2026-11-${String(i + 1).padStart(2, '0')}T09:00:00+00:00` })),
  low: Math.min(...prices), high: Math.max(...prices), first: prices[0], last: prices.at(-1),
})

test('the label says how many reads, from where to where, and the lowest', () => {
  const { sparkLabel } = require(files.priceHistory)
  const plain = (n) => n.toLocaleString(undefined, { maximumFractionDigits: 2 })
  const prices = [1200, 1150, 1090, 1130, 1100, 1120, 1110, 1105, 1100]
  assert.equal(sparkLabel(history(prices)), `Price over 9 reads: from ${plain(1200)} to ${plain(1100)}, lowest ${plain(1090)}`)
  assert.equal(sparkLabel(history([5])), '')
})

test('the figures say lowest, highest and the move since the first read, and "Lowest so far" needs an earlier higher read', () => {
  const { figuresOf, isLowestSoFar } = require(files.priceHistory)
  const fell = history([1200, 1150, 1090])
  const figures = figuresOf(fell, 'TRY')
  assert.deepEqual(figures.map((one) => one.label), ['Lowest', 'Highest', 'Since first read'])
  assert.ok(figures[0].value.includes('1,090') || figures[0].value.includes('1090'))
  assert.match(figures[2].value, /^Down .*110.* TRY \(9\.2%\)$/)
  assert.equal(isLowestSoFar(fell), true)
  assert.equal(isLowestSoFar(history([1090, 1150, 1200])), false, 'the lowest was earlier, not now')
  assert.equal(isLowestSoFar(history([100, 100])), false, 'a price that never moved is not a low')
  assert.equal(isLowestSoFar(history([100])), false)
  assert.deepEqual(figuresOf(history([100]), 'TRY'), [], 'one read says nothing about a move')
  assert.equal(figuresOf(history([100, 100]), 'TRY')[2].value, 'No change')
  assert.match(figuresOf(history([100, 110]), 'TRY')[2].value, /^Up /)
})

test('a watch\'s history is asked for once and kept for 30 seconds, and a new read asks again at once', async () => {
  const { fetchHistory, clearHistoryCache, HISTORY_CACHE_MS } = require(files.watchHistory)
  clearHistoryCache()
  const calls = []
  routes.get = (path) => { calls.push(path); return Promise.resolve(history([10, 9])) }
  await Promise.all([fetchHistory('w1', 'a', 1000), fetchHistory('w1', 'a', 1000)])
  await fetchHistory('w1', 'a', 1000 + HISTORY_CACHE_MS - 1)
  assert.deepEqual(calls, ['/api/prices/watches/w1/history'], 'two rows asking at once, and a later ask, share one request')
  await fetchHistory('w1', 'a', 1000 + HISTORY_CACHE_MS + 1)
  assert.equal(calls.length, 2, 'after 30 seconds it asks again')
  await fetchHistory('w1', 'b', 1000 + HISTORY_CACHE_MS + 2)
  assert.equal(calls.length, 3, 'a watch read since asks again')
  await fetchHistory('w2', 'a', 1000)
  assert.equal(calls.at(-1), '/api/prices/watches/w2/history')
})

// Procurement across the app: what an estimate is worth, what needs the eye,
// and how a product gets onto an estimate from any screen.
//
// The money is the Estimate screen's own (`quoteMoney`), so the numbers here
// are the numbers the forecast uses. The rules a reader can argue with:
// gross is summed per currency and never mixed; a quote in a currency with no
// rate is uncomparable and is left out of every sum; an unpriced line is
// counted, not read as free.
//
// The engine modules are compiled and imported for real. Only the HTTP layer
// (`./api`) and the engine context (`./Engine`) are stubbed, so the saves and
// reads a test asserts are the ones the app makes.

import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { basename, join } from 'node:path'
import { createRequire } from 'node:module'
import { JSDOM } from 'jsdom'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const require = createRequire(import.meta.url)
const Module = require('node:module')
const originalLoad = Module._load

let directory
let files
let procurement, estimates
const routes = { get: null, post: null }
const apiStub = {
  seg: (id) => encodeURIComponent(id),
  get: (path) => routes.get(path),
  post: (path, body) => routes.post(path, body),
  del: async () => ({}),
}
let engineMode = 'live'
const engineStub = { useEngine: () => ({ mode: engineMode }) }

const savedWindow = globalThis.window
const savedDocument = globalThis.document
const savedEvent = globalThis.Event
const savedCustomEvent = globalThis.CustomEvent

before(async () => {
  directory = await mkdtemp(join(process.cwd(), '.procurement-test-'))
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
    estimates: await compile('src/engine/estimates.ts', 'estimates'),
    procurement: await compile('src/engine/procurement.ts', 'procurement'),
    RiskMark: await compile('src/ui/RiskMark.tsx', 'RiskMark'),
    AddToEstimate: await compile('src/ui/AddToEstimate.tsx', 'AddToEstimate'),
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
  procurement = require(files.procurement)
  estimates = require(files.estimates)
  // The pure tests dispatch change events on a bare EventTarget.
  globalThis.window = new EventTarget()
})

after(async () => {
  Module._load = originalLoad
  globalThis.window = savedWindow
  globalThis.document = savedDocument
  globalThis.Event = savedEvent
  globalThis.CustomEvent = savedCustomEvent
  if (directory) await rm(directory, { recursive: true, force: true })
})

// ── fixtures ──

const TODAY = new Date(2026, 10, 20)
const isoDay = (date) => {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
const plus = (days) => isoDay(new Date(2026, 10, 20 + days))

const quote = (over = {}) => ({
  vendor: 'Vendor', seller: '', url: '', unit_price: 100, currency: 'TRY', vat_rate: 0, vat_included: false,
  delivery_days: null, warranty_months: null, quote_date: '', valid_until: '', note: '', selected: true,
  ...over,
})

const line = (subjectId, quotes, over = {}) => ({
  subject_id: subjectId, pack_id: 'pumps', label: subjectId.toUpperCase(), quantity: 1, unit_price: null, note: '',
  depreciation: 'straight_line', life_years: null, salvage: null, vuk_rate: null, quotes, ...over,
})

const estimate = (over = {}) => ({
  estimate_id: 'e1', name: 'Estimate', currency: 'TRY', years: 5, maintenance_pct: 5, discount_pct: 8, vat_rate: 20,
  fx: { TRY: 1, USD: 30, EUR: 33 }, created_at: '', updated_at: '2026-11-01T00:00:00Z', lines: [], ...over,
})

// ── the money and the rules ──

test('gross is summed per estimate currency and never mixed across currencies', () => {
  const lira = estimate({ estimate_id: 'a', currency: 'TRY', lines: [line('pump', [quote({ unit_price: 100 })], { quantity: 2 })] })
  const dollar = estimate({ estimate_id: 'b', currency: 'USD', lines: [line('valve', [quote({ unit_price: 50, currency: 'USD' })], { quantity: 3 })] })
  const summary = procurement.summarize([lira, dollar], TODAY)
  assert.deepEqual(summary.gross, { TRY: 200, USD: 150 })
  assert.equal(summary.estimates, 2)
  assert.equal(summary.lines, 2)
})

test('a quote in another currency is converted at the stated rates, not at 1', () => {
  const dollar = estimate({ currency: 'USD', lines: [line('sensor', [quote({ unit_price: 10, currency: 'EUR' })])] })
  const summary = procurement.summarize([dollar], TODAY)
  assert.ok(Math.abs(summary.gross.USD - 11) < 1e-9, `10 EUR at 33 TRY over 30 TRY per USD is 11 USD, got ${summary.gross.USD}`)
})

test('an unpriced line is counted as unpriced and contributes nothing to gross', () => {
  const lines = estimate({
    lines: [
      line('none', []),
      line('blank', [quote({ unit_price: null })]),
      line('priced', [quote({ unit_price: 10 })]),
    ],
  })
  const summary = procurement.summarize([lines], TODAY)
  assert.equal(summary.lines, 3)
  assert.equal(summary.unpricedLines, 2)
  assert.equal(summary.quotedLines, 2)
  assert.deepEqual(summary.gross, { TRY: 10 })
  const [none] = procurement.linesOf(lines, TODAY)
  assert.equal(none.unpriced, true)
  assert.ok(none.reasons.includes('No quote yet'))
})

test('a quote whose currency has no rate is uncomparable and left out of gross', () => {
  const noEuro = estimate({ currency: 'USD', fx: { TRY: 1, USD: 30 }, lines: [line('lens', [quote({ unit_price: 10, currency: 'EUR' })])] })
  const summary = procurement.summarize([noEuro], TODAY)
  assert.equal(summary.uncomparable, 1)
  assert.deepEqual(summary.gross, {})
  const [item] = procurement.linesOf(noEuro, TODAY)
  assert.equal(item.bestLanded, null)
  assert.equal(item.best, null)
  assert.equal(item.unpriced, false)
  assert.ok(item.reasons.includes('No EUR rate'))
})

test('a quote already in the estimate currency needs no rate', () => {
  const dollarNoRate = estimate({ currency: 'USD', fx: { TRY: 1 }, lines: [line('cable', [quote({ unit_price: 10, currency: 'USD' })])] })
  const summary = procurement.summarize([dollarNoRate], TODAY)
  assert.equal(summary.uncomparable, 0)
  assert.deepEqual(summary.gross, { USD: 10 })
})

test('expiring and expired split at 14 days, against a fixed today', () => {
  const dated = (label, days) => line(label, [quote({ valid_until: plus(days) })])
  const shop = estimate({
    lines: [dated('today', 0), dated('two-weeks', 14), dated('fifteen', 15), dated('yesterday', -1), dated('month', -30)],
  })
  const summary = procurement.summarize([shop], TODAY)
  assert.deepEqual(summary.expiring.map((item) => item.label), ['TODAY', 'TWO-WEEKS'])
  assert.deepEqual(summary.expired.map((item) => item.label), ['YESTERDAY', 'MONTH'])
  const fifteen = procurement.linesOf(shop, TODAY).find((item) => item.label === 'FIFTEEN')
  assert.equal(fifteen.expiresInDays, 15)
  assert.ok(!summary.expiring.some((item) => item.label === 'FIFTEEN'))
})

test('at risk lists red before amber and leaves out green and unrated', () => {
  const rated = (label, level) => line(label, [quote({ risk: { level, reasons: [`${level} reason`] } })])
  const shop = estimate({ lines: [rated('amber', 'amber'), rated('red', 'red'), rated('green', 'green'), rated('unknown', 'unknown')] })
  const summary = procurement.summarize([shop], TODAY)
  assert.deepEqual(summary.atRisk.map((item) => item.label), ['RED', 'AMBER'])
})

test('the best quote is the cheapest landed price, and saving is the gap to the runner-up', () => {
  const shop = estimate({
    lines: [line('pump', [quote({ unit_price: 120, vendor: 'Mid' }), quote({ unit_price: 100, vendor: 'Low' }), quote({ unit_price: 150, vendor: 'High' })])],
  })
  const [item] = procurement.linesOf(shop, TODAY)
  assert.equal(item.best.vendor, 'Low')
  assert.equal(item.bestLanded, 100)
  assert.equal(item.nextLanded, 120)
  assert.equal(item.saving, 20)
  assert.equal(item.quotes, 3)
})

test('the engine ranking decides the order when it ranks every priced quote', () => {
  const cheap = quote({ unit_price: 100, vendor: 'Cheap', quote_id: 'q1' })
  const dear = quote({ unit_price: 120, vendor: 'Dear', quote_id: 'q2' })
  const shop = estimate({
    lines: [line('pump', [cheap, dear], {
      ranking: [
        { quote_id: 'q2', rank: 1, landed: 120, reasons: [] },
        { quote_id: 'q1', rank: 2, landed: 100, reasons: [] },
      ],
    })],
  })
  const [item] = procurement.linesOf(shop, TODAY)
  assert.equal(item.best.vendor, 'Dear')
})

test('findProduct finds a subject on every estimate that holds it', () => {
  const first = estimate({ estimate_id: 'e1', lines: [line('pump-1', [quote()]), line('pump-2', [quote()])] })
  const second = estimate({ estimate_id: 'e2', name: 'Second', lines: [line('pump-1', [quote()])] })
  const found = procurement.findProduct([first, second], 'pump-1')
  assert.deepEqual(found.map((item) => item.estimateId), ['e1', 'e2'])
  assert.deepEqual(procurement.findProduct([first, second], 'nothing'), [])
})

test('the risk mark says its level in words', () => {
  const { RiskMark } = require(files.RiskMark)
  const mark = (level) => renderToStaticMarkup(React.createElement(RiskMark, { level }))
  assert.equal(mark('green'), '<span class="k-risk" data-level="green">Low</span>')
  assert.equal(mark('amber'), '<span class="k-risk" data-level="amber">Medium</span>')
  assert.equal(mark('red'), '<span class="k-risk" data-level="red">High</span>')
  assert.equal(mark('unknown'), '<span class="k-risk" data-level="unknown">Not rated</span>')
})

// ── adding to an estimate ──

/** Replace the two calls addToEstimate makes, with an in-memory store. */
async function withStore(seed, body) {
  const store = new Map(Object.entries(seed))
  const saves = []
  let counter = 0
  const originals = { load: estimates.loadEstimate, save: estimates.saveEstimate }
  estimates.loadEstimate = async (id) => structuredClone(store.get(id))
  estimates.saveEstimate = async (payload) => {
    saves.push(structuredClone(payload))
    const id = payload.estimate_id || `new-${++counter}`
    const saved = {
      estimate_id: id, name: payload.name, currency: payload.currency ?? 'USD', years: 5, maintenance_pct: 5,
      discount_pct: 8, vat_rate: 20, fx: payload.fx ?? {}, created_at: '', updated_at: '', lines: payload.lines.map((item, i) => ({
        ...item, line_id: `l${i}`, quotes: item.quotes.map((q, j) => ({ ...q, quote_id: q.quote_id || `q${++counter}-${j}` })),
      })),
    }
    store.set(id, saved)
    return structuredClone(saved)
  }
  try {
    return await body({ saves, store })
  } finally {
    estimates.loadEstimate = originals.load
    estimates.saveEstimate = originals.save
  }
}

const pump = { subject_id: 'pump-2', pack_id: 'pumps', label: 'Pump 2' }

test('addToEstimate appends a line for a new subject, with the first quote selected', async () => {
  await withStore({ e1: estimate({ lines: [line('pump-1', [quote()])] }) }, async ({ saves }) => {
    let events = 0
    window.addEventListener('kriko:procurement-changed', () => { events += 1 })
    const saved = await procurement.addToEstimate({
      estimateId: 'e1',
      subject: pump,
      quote: { vendor: 'Shop', unit_price: 100, url: 'https://www.shop.example/p' },
    })
    assert.equal(saved.lines.length, 2)
    const added = saved.lines[1]
    assert.equal(added.subject_id, 'pump-2')
    assert.equal(added.quantity, 1)
    assert.equal(added.quotes.length, 1)
    assert.equal(added.quotes[0].selected, true)
    assert.equal(added.quotes[0].currency, 'TRY', 'the quote takes the estimate currency')
    assert.equal(added.quotes[0].vat_rate, 20)
    assert.equal(added.quotes[0].vat_included, true)
    assert.equal(saves.length, 1)
    assert.equal(events, 1, 'other screens are told to reload')
  })
})

test('a second quote for a subject merges into its line and the first stays selected', async () => {
  await withStore({ e1: estimate({ lines: [line('pump-1', [quote()])] }) }, async () => {
    await procurement.addToEstimate({ estimateId: 'e1', subject: pump, quote: { vendor: 'Shop', unit_price: 100 } })
    const saved = await procurement.addToEstimate({ estimateId: 'e1', subject: pump, quote: { vendor: 'Other', unit_price: 90 } })
    assert.equal(saved.lines.length, 2, 'no second line for the same subject')
    const quotes = saved.lines[1].quotes
    assert.deepEqual(quotes.map((q) => q.vendor), ['Shop', 'Other'])
    assert.deepEqual(quotes.map((q) => q.selected), [true, false])
  })
})

test('a line holds at most 20 quotes', async () => {
  const full = Array.from({ length: 20 }, (_, i) => quote({ vendor: `V${i}`, selected: i === 0 }))
  await withStore({ e1: estimate({ lines: [line('pump-2', full)] }) }, async ({ saves }) => {
    await assert.rejects(
      procurement.addToEstimate({ estimateId: 'e1', subject: pump, quote: { vendor: 'Twenty-one', unit_price: 1 } }),
      /at most 20 quotes/,
    )
    assert.equal(saves.length, 0, 'nothing is saved when the cap is hit')
  })
})

test('a new estimate starts from the name and the default currency, and selects its first quote', async () => {
  await withStore({}, async ({ saves }) => {
    const saved = await procurement.addToEstimate({
      newName: 'Winter',
      subject: pump,
      quote: { vendor: 'Shop', unit_price: 5, currency: 'eur' },
    })
    assert.equal(saves[0].name, 'Winter')
    assert.equal(saves[0].currency, undefined, 'saveEstimate supplies its own default')
    assert.equal(saved.name, 'Winter')
    assert.equal(saved.lines[0].quotes[0].currency, 'EUR')
    assert.equal(saved.lines[0].quotes[0].selected, true)
  })
})

test('a watched price becomes a quote with its host as the vendor', () => {
  const quoteFromWatch = procurement.quoteFromWatch({
    watch_id: 'w1', url: 'https://www.shop.example/pump?ref=1', name: 'Pump', currency: 'EUR', target: null,
    started_price: 90, last_price: 120, last_checked: '', last_error: '', cloud: 0,
  })
  assert.equal(quoteFromWatch.vendor, 'shop.example')
  assert.equal(quoteFromWatch.url, 'https://www.shop.example/pump?ref=1')
  assert.equal(quoteFromWatch.unit_price, 120)
  assert.equal(quoteFromWatch.currency, 'EUR')
  assert.equal(quoteFromWatch.note, 'From a watched price')
  assert.equal(quoteFromWatch.quote_date, isoDay(new Date()))
})

// ── the screen-facing pieces, in a real DOM ──

async function mountDom(render) {
  const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://localhost/' })
  globalThis.window = dom.window
  globalThis.document = dom.window.document
  globalThis.Event = dom.window.Event
  globalThis.CustomEvent = dom.window.CustomEvent
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  // Loaded after the DOM globals exist: react-dom decides at load time whether it can use the DOM.
  const { createRoot } = require('react-dom/client')
  const root = createRoot(dom.window.document.getElementById('root'))
  const flush = () => React.act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
  await React.act(async () => root.render(render()))
  return {
    dom,
    document: dom.window.document,
    flush,
    act: (fn) => React.act(async () => fn()),
    unmount: async () => { await React.act(async () => root.unmount()); dom.window.close() },
  }
}

const ESTIMATES_PATH = '/api/estimates?limit=100'
const pumpsFixture = estimate({ estimate_id: 'e1', name: 'Pumps', lines: [line('pump-1', [quote()])] })
const labFixture = estimate({ estimate_id: 'e2', name: 'Lab', lines: [] })

/** The engine's answers for the list, the reads and the saves. */
function serve() {
  const calls = []
  routes.get = (path) => {
    calls.push(path)
    if (path === ESTIMATES_PATH) {
      return Promise.resolve({ items: [
        { estimate_id: 'e1', name: 'Pumps', currency: 'TRY', lines_count: 1, updated_at: '2026-11-02' },
        { estimate_id: 'e2', name: 'Lab', currency: 'USD', lines_count: 0, updated_at: '2026-11-01' },
      ] })
    }
    if (path === '/api/estimates/e1') return Promise.resolve({ estimate: structuredClone(pumpsFixture) })
    if (path === '/api/estimates/e2') return Promise.resolve({ estimate: structuredClone(labFixture) })
    return Promise.reject(new Error(`unexpected read ${path}`))
  }
  routes.post = (path, body) => {
    calls.push(`POST ${path}`)
    const id = body.estimate_id || 'new-1'
    return Promise.resolve({ estimate: { ...body, estimate_id: id, currency: body.currency ?? 'USD', fx: body.fx ?? {}, lines: body.lines.map((item, i) => ({ ...item, line_id: `l${i}` })) } })
  }
  return calls
}

const SUBJECT = { subject_id: 'pump-9', pack_id: 'pumps', label: 'Pump 9' }

test('the popover opens on its button, takes focus, and closes on Escape with focus back on the button', async () => {
  engineMode = 'live'
  const calls = serve()
  const { AddToEstimate } = require(files.AddToEstimate)
  const view = await mountDom(() => React.createElement(AddToEstimate, { subject: SUBJECT, quote: { vendor: 'Shop', unit_price: 40 } }))
  try {
    const { document, flush, act } = view
    const button = [...document.querySelectorAll('button')].find((node) => node.textContent === 'Add to estimate')
    assert.ok(button, 'the Add to estimate button is there')
    assert.equal(button.disabled, false)
    await act(() => button.click())
    await flush()
    const dialog = document.querySelector('[role="dialog"]')
    assert.ok(dialog, 'the popover is a dialog')
    assert.equal(document.getElementById(dialog.getAttribute('aria-labelledby')).textContent, 'Add to estimate')
    assert.equal(document.activeElement, dialog, 'focus moves into the popover')
    const rows = [...dialog.querySelectorAll('button.k-row')].map((node) => node.textContent)
    assert.equal(rows.length, 2)
    assert.ok(rows[0].includes('Pumps') && rows[0].includes('1 line') && rows[0].includes('TRY'))
    assert.ok(calls.includes(ESTIMATES_PATH))

    await act(() => dialog.dispatchEvent(new view.dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    assert.equal(document.querySelector('[role="dialog"]'), null, 'Escape closes it')
    assert.equal(document.activeElement, button, 'focus returns to the button')
  } finally {
    await view.unmount()
  }
})

test('a press outside the popover closes it', async () => {
  engineMode = 'live'
  serve()
  const { AddToEstimate } = require(files.AddToEstimate)
  const view = await mountDom(() => React.createElement(AddToEstimate, { subject: SUBJECT }))
  try {
    const { document, flush, act } = view
    const button = [...document.querySelectorAll('button')].find((node) => node.textContent === 'Add to estimate')
    await act(() => button.click())
    await flush()
    assert.ok(document.querySelector('[role="dialog"]'))
    await act(() => document.body.dispatchEvent(new view.dom.window.Event('pointerdown', { bubbles: true })))
    assert.equal(document.querySelector('[role="dialog"]'), null)
  } finally {
    await view.unmount()
  }
})

test('outside the live engine the button is disabled and says it needs the engine', async () => {
  engineMode = 'demo'
  serve()
  const { AddToEstimate } = require(files.AddToEstimate)
  const view = await mountDom(() => React.createElement(AddToEstimate, { subject: SUBJECT }))
  try {
    const button = [...view.document.querySelectorAll('button')].find((node) => node.textContent === 'Add to estimate')
    assert.equal(button.disabled, true)
    assert.ok(view.document.body.textContent.includes('Needs the engine'))
  } finally {
    await view.unmount()
    engineMode = 'live'
  }
})

test('choosing an estimate saves the product and offers to open the Procurement screen', async () => {
  engineMode = 'live'
  const calls = serve()
  const { AddToEstimate } = require(files.AddToEstimate)
  const view = await mountDom(() => React.createElement(AddToEstimate, { subject: SUBJECT, quote: { vendor: 'Shop', unit_price: 40 } }))
  const navigations = []
  const listener = (event) => navigations.push(event.detail)
  view.dom.window.addEventListener('kriko:navigate', listener)
  try {
    const { document, flush, act } = view
    const button = [...document.querySelectorAll('button')].find((node) => node.textContent === 'Add to estimate')
    await act(() => button.click())
    await flush()
    const row = [...document.querySelectorAll('[role="dialog"] button.k-row')].find((node) => node.textContent.includes('Pumps'))
    await act(() => row.click())
    await flush()
    assert.ok(calls.includes('POST /api/estimates'), 'the estimate is saved through the API')
    assert.ok(document.body.textContent.includes('Added to Pumps.'))
    const open = [...document.querySelectorAll('[role="dialog"] button')].find((node) => node.textContent === 'Open it')
    await act(() => open.click())
    assert.deepEqual(navigations, [{ screen: 'estimate' }])
  } finally {
    view.dom.window.removeEventListener('kriko:navigate', listener)
    await view.unmount()
  }
})

test('a new estimate can be named and created with the subject in one step', async () => {
  engineMode = 'live'
  const calls = serve()
  const { AddToEstimate } = require(files.AddToEstimate)
  const view = await mountDom(() => React.createElement(AddToEstimate, { subject: SUBJECT }))
  try {
    const { document, flush, act } = view
    const button = [...document.querySelectorAll('button')].find((node) => node.textContent === 'Add to estimate')
    await act(() => button.click())
    await flush()
    const input = document.querySelector('[role="dialog"] input.k-input')
    const setValue = Object.getOwnPropertyDescriptor(view.dom.window.HTMLInputElement.prototype, 'value').set
    await act(() => {
      setValue.call(input, 'Winter')
      input.dispatchEvent(new view.dom.window.Event('input', { bubbles: true }))
    })
    const form = document.querySelector('[role="dialog"] form')
    await act(() => form.dispatchEvent(new view.dom.window.Event('submit', { bubbles: true, cancelable: true })))
    await flush()
    assert.ok(calls.includes('POST /api/estimates'))
    assert.ok(document.body.textContent.includes('Added to Winter.'))
  } finally {
    await view.unmount()
  }
})

test('five screens mounting read the estimates once, and a change reloads them once', async () => {
  engineMode = 'live'
  const calls = serve()
  // The shared cache is 20 seconds: move the clock past anything an earlier test cached.
  const realNow = Date.now
  let clock = realNow() + 3_600_000
  Date.now = () => clock
  function Probe({ seen }) {
    seen.push(procurement.useProcurement())
    return null
  }
  const seen = []
  const view = await mountDom(() => React.createElement(React.Fragment, null,
    ...Array.from({ length: 5 }, (_, i) => React.createElement(Probe, { key: i, seen })),
  ))
  try {
    await view.flush()
    await view.flush()
    const listed = () => calls.filter((path) => path === ESTIMATES_PATH).length
    assert.equal(listed(), 1, 'five mounts share one request')
    const last = seen[seen.length - 1]
    assert.equal(last.loading, false)
    assert.equal(last.estimates.length, 2)
    assert.equal(last.summary.estimates, 2)

    await view.act(() => {
      clock += 1
      view.dom.window.dispatchEvent(new view.dom.window.Event('kriko:procurement-changed'))
    })
    await view.flush()
    assert.equal(listed(), 2, 'the change reloads once for all mounted hooks')
  } finally {
    Date.now = realNow
    await view.unmount()
  }
})

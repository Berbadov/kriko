import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'
import ts from 'typescript'
import { h, loadSource, mount } from './settings_support.mjs'

/**
 * Speed budgets, checked without a browser. What they pin is behaviour a reader
 * feels: the first paint ships only what Ask needs, a read asked for twice is one
 * request, and decoration never competes with the first interactive window.
 *
 * Measured with Playwright against `vite preview`, a 4x CPU throttle through CDP,
 * the live engine, median of six cold loads, four interleaved sessions on one machine
 * (2026-11-22; the spread is the machine's, so ranges are given):
 *
 *                                     before        after
 *   first-load JS, gzip               312 KB        196 KB  (index 72 + react 68 + motion 51 + 5)
 *   first-load JS, raw                1075 KB       632 KB
 *   JS fetched before Ask is up       1061 KB       214 KB
 *   Ask composer in the DOM           565-757 ms    463-573 ms
 *   composer takes focus              1.76-2.28 s   0.98-1.19 s  (the page's main thread is free sooner)
 *   long-task time until then         929-1339 ms   299-385 ms
 *   idle main thread, Ask, motion on  99 %          65 %   (4x throttle; sky at 30 fps, half grains on <=4 cores)
 *   idle main thread, motion off      22 %          4 %    (no frame loop, no per-frame style read)
 *   markdown pipeline (46 KB gz)      on the path   lazy: first answer on screen, or idle
 *   every other screen                on the path   14 chunks, warmed one by one when idle
 *
 * API requests on a cold load: the Ask landing makes the same 22 reads before and after
 * (the six estimate details come from the procurement strip, which another file owns;
 * `/api/agent-market` is a new read from another agent's feature). No read is duplicated.
 * The Catalogs list no longer reads `/api/subjects/{id}` for every product: only for
 * rows scrolled into view, six at a time, kept for a minute.
 */

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')

// ---- the first paint ships only what Ask needs ----

test('every screen beyond Ask is a lazy chunk, and the shell imports none of them statically', async () => {
  const lazy = await read('src/lazyScreens.ts')
  for (const name of ['CompareScreen', 'EstimateScreen', 'PricesScreen', 'ProductScreen', 'QueueScreen', 'SettingsScreen', 'HistoryPanel', 'ForYouPanel', 'CatalogsPanel', 'SitesPanel', 'Tour']) {
    assert.match(lazy, new RegExp(`export const ${name} = lazy\\(`), `${name} is not a lazy chunk`)
  }
  const app = await read('src/App.tsx')
  const staticImports = [...app.matchAll(/^import[^;]*?from '([^']+)'/gms)].map((hit) => hit[1])
  for (const heavy of ['./screens/Compare', './screens/Estimate', './screens/Prices', './screens/Product', './screens/Queue', './screens/Settings', './ui/panels/Catalogs', './ui/panels/ForYou', './ui/panels/History', './ui/panels/Sites', './tour/Tour']) {
    assert.ok(!staticImports.includes(heavy), `App statically imports ${heavy}`)
  }
  assert.ok(staticImports.includes('./screens/Chat'), 'Ask is meant to be eager')
  assert.match(app, /<Suspense fallback=\{<PageSkeleton \/>\}>/, 'a screen waiting for its chunk has no calm fallback')
})

test('the Ask landing does not pull the markdown pipeline: it is loaded the first time an answer is drawn', async () => {
  const wrapper = await read('src/ui/Markdown.tsx')
  assert.match(wrapper, /lazy\(\(\) => import\('\.\/MarkdownBody'\)/)
  assert.doesNotMatch(wrapper, /from 'react-markdown'|from 'remark-gfm'/)
  const body = await read('src/ui/MarkdownBody.tsx')
  assert.match(body, /from 'react-markdown'/)
  // Nothing else in the window imports the renderer's libraries directly.
  const { readdir } = await import('node:fs/promises')
  const walk = async (dir) => {
    let hits = []
    for (const entry of await readdir(new URL(`../${dir}/`, import.meta.url), { withFileTypes: true })) {
      const path = `${dir}/${entry.name}`
      if (entry.isDirectory()) hits = hits.concat(await walk(path))
      else if (/\.tsx?$/.test(entry.name) && path !== 'src/ui/MarkdownBody.tsx' && /from '(react-markdown|remark-gfm)'/.test(await read(path))) hits.push(path)
    }
    return hits
  }
  assert.deepEqual(await walk('src'), [])
})

test('the build splits the vendors, so React and motion are shared and markdown stands alone', async () => {
  const config = await read('vite.config.ts')
  assert.match(config, /codeSplitting/)
  for (const name of ['vendor-react', 'vendor-motion', 'vendor-markdown']) assert.ok(config.includes(`'${name}'`), `no ${name} group`)
})

test('every chunk is warmed in the idle time after the first paint, and on hover or focus of the rail', async () => {
  const app = await read('src/App.tsx')
  assert.match(app, /whenIdle\(\(\) => prefetchAll\(/)
  assert.match(app, /onPointerOver=\{warm\} onFocus=\{warm\}/)
  const lazy = await read('src/lazyScreens.ts')
  assert.match(lazy, /whenIdle\(next, 1500\)/, 'the prefetch is not spread across idle slices')
})

test('the performance stylesheet is loaded last and skips the layout of long lists below the fold', async () => {
  const main = await read('src/main.tsx')
  const styles = [...main.matchAll(/import '\.\/styles\/([^']+)'/g)].map((hit) => hit[1])
  assert.equal(styles.at(-1), 'perf.css', 'perf.css must come last, or later rules override it')
  const css = await read('src/styles/perf.css')
  assert.match(css, /content-visibility:\s*auto/)
  assert.match(css, /contain-intrinsic-size:\s*auto 72px/)
  // The first rows are left alone, so a focus ring on a visible row is never clipped.
  assert.match(css, /\.k-list > :nth-child\(n \+ 31\)/)
  // Only the moving page is promoted, and only while it moves.
  assert.match(css, /\.page\[data-moving='true'\]\s*\{\s*will-change:\s*opacity, transform/)
  assert.doesNotMatch(css, /\.page\s*\{[^}]*will-change/)
})

test('the page entrance moves opacity and transform only', async () => {
  const app = await read('src/App.tsx')
  const variants = app.slice(app.indexOf('variants={{'), app.indexOf('initial="enter"'))
  assert.match(variants, /opacity/)
  assert.match(variants, /\bx:/)
  assert.doesNotMatch(variants, /\b(width|height|top|left|margin|padding)\b/, 'a layout property is animated')
})

// ---- the providers do not redraw the whole window for every streamed word ----

test('the shell reads the chat, queue and board through stable handles, not the streaming state', async () => {
  const app = await read('src/App.tsx')
  assert.match(app, /useChatActions\(\)/)
  assert.match(app, /useQueueActive\(\)/)
  assert.match(app, /useCompareAdd\(\)/)
  assert.doesNotMatch(app, /\buseChat\(\)|\buseQueue\(\)|\buseCompare\(\)/, 'the shell subscribes to a context that changes every tick')
  const live = await read('src/engine/live.ts')
  assert.match(live, /return useMemo\(\(\) => \(\{ run, turns, threadId/, 'the live run API changes identity at every render')
})

// ---- the API client: identical reads in flight make one request ----

async function loadApi() {
  const source = await read('src/engine/api.ts')
  const code = ts
    .transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
    .outputText.replace('import.meta.env.VITE_ENGINE_BASE', 'undefined')
  const dir = await mkdtemp(join(tmpdir(), 'kriko-api-'))
  try {
    await writeFile(join(dir, 'api.mjs'), code)
    return await import(pathToFileURL(join(dir, 'api.mjs')).href)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

const api = await loadApi()

/** A fake engine: counts requests and answers each after `delay` ms. */
function fakeEngine({ delay = 5, status = 200 } = {}) {
  const calls = []
  let version = 0
  globalThis.window = { setTimeout, clearTimeout, dispatchEvent() {} }
  globalThis.fetch = async (url, options = {}) => {
    calls.push(`${options.method ?? 'GET'} ${url}`)
    const n = ++version
    await new Promise((resolve) => setTimeout(resolve, delay))
    return { status, text: async () => JSON.stringify({ n, items: [1, 2, 3] }) }
  }
  return calls
}

test('two identical GETs in flight make one request, and each caller gets its own copy', async () => {
  api.forgetSharedReads()
  const calls = fakeEngine()
  const [a, b] = await Promise.all([api.get('/api/history?limit=4'), api.get('/api/history?limit=4')])
  assert.equal(calls.length, 1)
  assert.deepEqual(a, b)
  a.items.push(99)
  assert.deepEqual(b.items, [1, 2, 3], 'one caller changed the other caller\'s data')
})

test('different paths are different requests', async () => {
  api.forgetSharedReads()
  const calls = fakeEngine()
  await Promise.all([api.get('/api/a'), api.get('/api/b')])
  assert.equal(calls.length, 2)
})

test('the same read within two seconds is answered from memory, and after two seconds it is read again', async () => {
  api.forgetSharedReads()
  const calls = fakeEngine()
  const realNow = Date.now
  let clock = 1_000_000
  Date.now = () => clock
  try {
    await api.get('/api/prices/watches')
    clock += 1500
    await api.get('/api/prices/watches')
    assert.equal(calls.length, 1, 'a read inside the window went to the engine again')
    clock += 600
    await api.get('/api/prices/watches')
    assert.equal(calls.length, 2, 'a read after the window was served from memory')
  } finally {
    Date.now = realNow
  }
})

test('a POST is never coalesced or remembered', async () => {
  api.forgetSharedReads()
  const calls = fakeEngine()
  await Promise.all([api.post('/api/queue/complete', { a: 1 }), api.post('/api/queue/complete', { a: 1 })])
  assert.equal(calls.length, 2)
  await api.del('/api/estimates/x')
  await api.del('/api/estimates/x')
  assert.equal(calls.length, 4)
})

test('a write empties what was remembered, so the next read reaches the engine', async () => {
  api.forgetSharedReads()
  const calls = fakeEngine()
  await api.get('/api/estimates?limit=100')
  await api.post('/api/estimates', { name: 'x' })
  await api.get('/api/estimates?limit=100')
  assert.deepEqual(calls.filter((call) => call.startsWith('GET')).length, 2)
})

test('a read that was in flight when a write happened is not kept, and a later read does not join it', async () => {
  api.forgetSharedReads()
  const calls = fakeEngine({ delay: 20 })
  const early = api.get('/api/estimates?limit=100')
  const write = api.post('/api/estimates', { name: 'x' })
  await Promise.all([early, write])
  await api.get('/api/estimates?limit=100')
  assert.equal(calls.filter((call) => call.startsWith('GET')).length, 2, 'an answer older than the write was reused')
})

test('?fresh and polled paths skip both tables', async () => {
  api.forgetSharedReads()
  const calls = fakeEngine()
  await Promise.all([api.get('/api/estimates?fresh=1'), api.get('/api/estimates?fresh=1')])
  assert.equal(calls.length, 2)
  await api.get('/api/jobs/abc')
  await api.get('/api/jobs/abc')
  await api.get('/api/queue')
  await api.get('/api/queue')
  assert.equal(calls.length, 6, 'a polled path was remembered')
})

test('an engine problem still surfaces, and a failed read is not remembered', async () => {
  api.forgetSharedReads()
  const calls = fakeEngine({ status: 500 })
  await assert.rejects(api.get('/api/history'), (error) => error.status === 500)
  await assert.rejects(api.get('/api/history'), (error) => error.status === 500)
  assert.equal(calls.length, 2)
  globalThis.fetch = async () => {
    throw new TypeError('network down')
  }
  await assert.rejects(api.get('/api/other'), (error) => error.status === 0 && /Could not reach Kriko/.test(error.message))
})

// ---- decoration waits, and stops when it cannot be seen ----

test('the motes are not drawn before the window has been idle, and none are drawn when motion is off', async () => {
  const stub = (on) => ({ '../prefs': { usePrefs: () => ({ motion: { on }, profile: 'standard', resolved: 'dark' }) } })
  const on = loadSource('src/dust/Motes.tsx', stub(true))
  const page = await mount(h(on.Motes))
  try {
    assert.equal(page.document.querySelector('.motes'), null, 'the motes are on the first paint')
    await page.flush()
    await new Promise((resolve) => setTimeout(resolve, 1700))
    await page.flush()
    assert.ok(page.document.querySelector('.motes'), 'the motes never appeared')
    assert.ok(page.document.querySelectorAll('.motes i').length > 0)
  } finally {
    await page.unmount()
  }
  const off = loadSource('src/dust/Motes.tsx', stub(false))
  const still = await mount(h(off.Motes))
  try {
    await new Promise((resolve) => setTimeout(resolve, 1700))
    await still.flush()
    assert.equal(still.document.querySelector('.motes'), null, 'motes are drawn with motion off')
  } finally {
    await still.unmount()
  }
})

test('the shared frame loop draws at most 30 times a second and stops when hidden or when motion is off', async () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { pretendToBeVisual: true })
  const frames = []
  const saved = ['document', 'requestAnimationFrame', 'cancelAnimationFrame'].map((name) => [name, globalThis[name]])
  globalThis.document = dom.window.document
  globalThis.requestAnimationFrame = (callback) => frames.push(callback)
  globalThis.cancelAnimationFrame = () => frames.splice(0)
  try {
    const source = await read('src/dust/ticker.ts')
    const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
    const dir = await mkdtemp(join(tmpdir(), 'kriko-ticker-'))
    let ticker
    try {
      await writeFile(join(dir, 'ticker.mjs'), code)
      ticker = await import(pathToFileURL(join(dir, 'ticker.mjs')).href)
    } finally {
      await rm(dir, { recursive: true, force: true })
    }
    let ticks = 0
    const stop = ticker.onFrame(() => ticks++)
    // One second of a 60 Hz display.
    let now = 1000
    for (let i = 0; i < 60; i++) {
      const next = frames.splice(0)
      now += 1000 / 60
      for (const callback of next) callback(now)
    }
    assert.ok(ticks >= 25 && ticks <= 31, `${ticks} draws in one second at 60 Hz`)

    // Motion off: the loop ends and nothing is scheduled again.
    dom.window.document.documentElement.dataset.motion = 'off'
    for (const callback of frames.splice(0)) callback((now += 17))
    assert.equal(frames.length, 0, 'a frame is still requested with motion off')
    stop()
  } finally {
    for (const [name, value] of saved) {
      if (value === undefined) delete globalThis[name]
      else globalThis[name] = value
    }
    dom.window.close()
  }
})

test('a dust field draws once and subscribes to no frame loop while motion is off or the field is out of view', async () => {
  const field = await read('src/dust/DustField.tsx')
  assert.match(field, /useAfterIdle\(\)/, 'the field does not wait for idle')
  assert.match(field, /const moving = s\.visible && s\.motion !== 'still'/)
  assert.match(field, /if \(moving && !stop\) stop = onFrame\(tick\)/)
  assert.match(field, /lowCores\(\)/, 'a machine with few cores gets the full grain count')
  assert.match(field, /\+\+frames % 30 === 0/, 'the ink is read at every frame, which forces a style recalculation each time')
})

test('the tour and the dust come after the first idle, the sprite library does not (glyphs need it)', async () => {
  const app = await read('src/App.tsx')
  assert.match(app, /const tourReady = useAfterIdle\(/)
  assert.match(app, /\{tourReady && \(/)
  assert.match(app, /<PixelSprites \/>/)
  const idle = await read('src/idle.ts')
  assert.match(idle, /useState\(false\)/, 'decoration is ready before the first idle')
})

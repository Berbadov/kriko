import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, readdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

/**
 * The shell's routes: which place a name opens, and whether every screen the
 * rail offers has a page behind it.
 *
 * `drawerEvents.ts` is pure (its only window use is inside `showDrawer`), so it
 * is transpiled and imported here the way `estimate.test.mjs` imports its maths.
 * The rail and the render branches are read as text, because they are React.
 */

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')

let routes
let directory
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-shell-'))
  const code = await read('src/ui/drawerEvents.ts')
  const built = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  await writeFile(join(directory, 'drawerEvents.mjs'), built)
  routes = await import(pathToFileURL(join(directory, 'drawerEvents.mjs')))
})
after(async () => {
  if (directory) await rm(directory, { recursive: true, force: true })
})

test('every named place opens the screen and Settings section it was given', () => {
  const expected = {
    history: { screen: 'history' },
    foryou: { screen: 'foryou' },
    browse: { screen: 'catalogs' },
    sites: { screen: 'sites' },
    settings: { screen: 'settings', section: 'general' },
    agents: { screen: 'settings', section: 'research' },
    chat: { screen: 'settings', section: 'research' },
    local: { screen: 'settings', section: 'keys' },
    setup: { screen: 'settings', section: 'connections' },
    logs: { screen: 'settings', section: 'data' },
    backups: { screen: 'settings', section: 'data' },
    updates: { screen: 'settings', section: 'data' },
    report: { screen: 'settings', section: 'data' },
  }
  for (const [panel, route] of Object.entries(expected)) {
    assert.deepEqual(routes.routeFor(panel), route, `routeFor(${panel})`)
  }
})

test('a place with no name, and a name the shell does not know, route nowhere', () => {
  assert.equal(routes.routeFor(null), null)
  for (const unknown of ['', 'drawer', 'More', 'constructor', '__proto__', 'toString']) {
    assert.equal(routes.routeFor(unknown), null, `routeFor(${JSON.stringify(unknown)})`)
  }
})

test('a place that is a screen of its own has no section', () => {
  assert.equal(routes.routeFor('history').section, undefined)
  assert.equal(routes.routeFor('foryou').section, undefined)
})

test('the shortcuts reach Ask, Compare, Prices and Procurement, in that order', () => {
  assert.deepEqual(routes.ORDER, ['chat', 'compare', 'prices', 'estimate'])
})

test('every screen the rail offers has a render branch in App', async () => {
  const rail = await read('src/ui/Rail.tsx')
  const app = await read('src/App.tsx')
  const railIds = [...rail.matchAll(/\{ id: '([a-z]+)'/g)].map((m) => m[1])
  assert.ok(railIds.length >= 9, 'the rail lists too few screens to be the rail')
  for (const id of [...railIds, 'settings']) {
    assert.ok(app.includes(`screen === '${id}'`), `App has no render branch for the ${id} screen`)
  }
})

test('the rail, read top to bottom, is the order Next and Back move through', async () => {
  const rail = await read('src/ui/Rail.tsx')
  const railIds = [...rail.matchAll(/\{ id: '([a-z]+)'/g)].map((m) => m[1])
  assert.deepEqual([...railIds, 'settings'], routes.RAIL_ORDER)
})

test('every screen a place routes to is one the rail can show', async () => {
  const rail = await read('src/ui/Rail.tsx')
  const railIds = new Set([...rail.matchAll(/\{ id: '([a-z]+)'/g)].map((m) => m[1]))
  for (const panel of ['history', 'foryou', 'browse', 'sites', 'settings', 'agents', 'chat', 'local', 'setup', 'logs', 'backups', 'updates', 'report']) {
    const { screen } = routes.routeFor(panel)
    assert.ok(screen === 'settings' || railIds.has(screen), `${panel} routes to ${screen}, which the rail does not show`)
  }
})

test('the rail keeps the hooks the tour and the tests point at, and no More button', async () => {
  const rail = await read('src/ui/Rail.tsx')
  for (const hook of ['nav-chat', 'nav-compare', 'nav-prices', 'nav-estimate', 'nav-queue', 'history', 'new-chat', 'settings', 'agent-pill']) {
    assert.ok(rail.includes(`'${hook}'`) || rail.includes(`data-tour="${hook}"`), `the shell has no data-tour="${hook}"`)
  }
  const sources = await Promise.all(['src/App.tsx', 'src/tour/Tour.tsx', 'src/ui/Rail.tsx', 'src/ui/TitleBar.tsx'].map(read))
  for (const source of sources) assert.doesNotMatch(source, /data-tour="more"/, 'a More button is still a tour target')
})

/** Every .ts and .tsx file under src, as text, except the tour itself (it names every target). */
async function sourceText(dir = new URL('../src/', import.meta.url)) {
  let text = ''
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const child = new URL(`${entry.name}${entry.isDirectory() ? '/' : ''}`, dir)
    if (entry.isDirectory()) text += await sourceText(child)
    else if (/\.tsx?$/.test(entry.name) && entry.name !== 'Tour.tsx') text += `\n${await readFile(child, 'utf8')}`
  }
  return text
}

test('the tour points only at hooks that some screen carries', async () => {
  const tour = await read('src/tour/Tour.tsx')
  const everywhere = await sourceText()
  for (const [, target] of tour.matchAll(/target: '([a-z-]+)'/g)) {
    assert.ok(everywhere.includes(`data-tour="${target}"`) || everywhere.includes(`'${target}'`), `the tour targets ${target}, and no screen carries it`)
  }
})

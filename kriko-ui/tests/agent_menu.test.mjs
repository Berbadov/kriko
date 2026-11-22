// The agent pill and its menu, and the usage card's one sentence.
//
// The menu is mounted in jsdom from the shipped `AgentMenu.tsx`. Its two
// picture imports (the agent marks and the icons) are stubbed, because they
// are Vite's and not Node's; everything the reader does with the menu is the
// real component. The verdict sentence is pure, so it is tested as a function.

import test, { before, after, afterEach } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'
import React from 'react'
import { createRoot } from 'react-dom/client'

const OPTIONS = {
  module: ts.ModuleKind.ESNext,
  jsx: ts.JsxEmit.ReactJSX,
  target: ts.ScriptTarget.ES2022,
  esModuleInterop: true,
}

const build = async (source) => ts.transpileModule(await readFile(source, 'utf8'), { compilerOptions: OPTIONS }).outputText

let directory, AgentMenu, usage, dom, root

before(async () => {
  // Inside the repository, so the stubs resolve the same React the test uses.
  directory = await mkdtemp(join(process.cwd(), '.agent-menu-'))
  await writeFile(
    join(directory, 'AgentMark.mjs'),
    "import { createElement } from 'react'\nexport function AgentMark({ id, state }) { return createElement('span', { 'data-mark': id, 'data-state': state, 'aria-hidden': 'true' }) }\n",
  )
  await writeFile(
    join(directory, 'Icon.mjs'),
    "import { createElement } from 'react'\nexport function Icon({ name }) { return createElement('i', { 'data-icon': name, 'aria-hidden': 'true' }) }\n",
  )
  const menu = (await build('src/ui/AgentMenu.tsx'))
    .replace("'../engine/usagemeters'", "'./usagemeters.mjs'")
    .replace("'./AgentMark'", "'./AgentMark.mjs'")
    .replace("'./Icon'", "'./Icon.mjs'")
  await writeFile(join(directory, 'AgentMenu.mjs'), menu)
  await writeFile(join(directory, 'usagemeters.mjs'), await build('src/engine/usagemeters.ts'))
  ;({ AgentMenu } = await import(pathToFileURL(join(directory, 'AgentMenu.mjs'))))
  usage = await import(pathToFileURL(join(directory, 'usagemeters.mjs')))
})

after(async () => {
  if (directory) await rm(directory, { recursive: true, force: true })
})

afterEach(async () => {
  if (root) await React.act(async () => root.unmount())
  root = null
  dom?.window.close()
  dom = null
})

const AGENTS = [
  { id: '', label: 'Default agent', backend: 'harness' },
  { id: 'claude-code', label: 'Claude Code', backend: 'harness' },
  { id: 'mistral-api', label: 'Mistral API', backend: 'harness' },
  { id: 'local', label: 'Local model', backend: 'local' },
  { id: 'cursor', label: 'Cursor', backend: 'harness' },
]

const MARKET = new Map([
  ['claude-code', { id: 'claude-code', state: 'ready', kind: 'cli' }],
  ['mistral-api', { id: 'mistral-api', state: 'needs_setup', kind: 'api' }],
  ['local', { id: 'local', state: 'needs_setup', kind: 'local' }],
  ['cursor', { id: 'cursor', state: 'not_installed', kind: 'cli' }],
])

async function mount(props = {}) {
  dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://localhost/' })
  globalThis.window = dom.window
  globalThis.document = dom.window.document
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const calls = { open: 0, choose: [], verify: 0, settings: 0 }
  root = createRoot(dom.window.document.getElementById('root'))
  const element = React.createElement(AgentMenu, {
    agents: AGENTS,
    preferred: 'claude-code',
    busy: false,
    live: true,
    market: MARKET,
    tour: 'agent-pill',
    onOpen: () => calls.open++,
    onChoose: (id) => calls.choose.push(id),
    onVerify: () => calls.verify++,
    onSettings: () => calls.settings++,
    ...props,
  })
  await React.act(async () => root.render(element))
  return { calls, doc: dom.window.document, win: dom.window }
}

const pill = (doc) => doc.querySelector('[data-tour="agent-pill"]')
const menu = (doc) => doc.querySelector('[role="menu"]')
const items = (doc) => [...doc.querySelectorAll('[role="menuitemradio"]')]

async function press(win, element) {
  await React.act(async () => element.dispatchEvent(new win.MouseEvent('click', { bubbles: true })))
}

async function key(win, element, name) {
  await React.act(async () => element.dispatchEvent(new win.KeyboardEvent('keydown', { key: name, bubbles: true })))
}

/** The accessible name, close enough: an aria-label, else the text and the labelled marks inside. */
function nameOf(el) {
  if (el.getAttribute('aria-label')) return el.getAttribute('aria-label')
  const labelled = [...el.querySelectorAll('[aria-label]')].map((node) => node.getAttribute('aria-label'))
  return [el.textContent.trim(), ...labelled].filter(Boolean).join(' ')
}

test('the pill names the agent in use, says its standing, and opens the menu', async () => {
  const { doc, calls, win } = await mount()
  const button = pill(doc)
  assert.equal(button.getAttribute('aria-haspopup'), 'menu')
  assert.equal(button.getAttribute('aria-expanded'), 'false')
  assert.match(nameOf(button), /Claude Code Ready/)
  assert.equal(menu(doc), null, 'the menu is shut until it is pressed')

  await press(win, button)
  assert.equal(button.getAttribute('aria-expanded'), 'true')
  assert.equal(calls.open, 1, 'opening asks the caller to read the market once')
  assert.ok(menu(doc), 'the menu did not open')
})

test('the menu lists every agent with its state in words, and marks the one in use', async () => {
  const { doc, win } = await mount()
  await press(win, pill(doc))
  const rows = items(doc)
  assert.deepEqual(rows.map((row) => row.querySelector('strong').textContent), ['Default agent', 'Claude Code', 'Mistral API', 'Local model', 'Cursor'])
  const words = rows.map((row) => row.querySelector('small').textContent)
  assert.deepEqual(words, ['Used when no agent is chosen', 'Ready', 'Needs a key', 'Needs setup', 'Not installed'])

  const checked = rows.filter((row) => row.getAttribute('aria-checked') === 'true')
  assert.equal(checked.length, 1)
  assert.equal(checked[0].querySelector('strong').textContent, 'Claude Code')
  assert.match(checked[0].textContent, /In use/)
  assert.ok(rows.every((row) => nameOf(row).length > 0), 'a menu row has no name')
})

test('choosing an agent calls the choose function once, closes, and gives the focus back to the pill', async () => {
  const { doc, calls, win } = await mount()
  await press(win, pill(doc))
  const mistral = items(doc).find((row) => row.querySelector('strong').textContent === 'Mistral API')
  await press(win, mistral)
  assert.deepEqual(calls.choose, ['mistral-api'], 'chooseAgent was not called exactly once, with the agent')
  assert.equal(menu(doc), null, 'the menu stayed open after a choice')
  assert.equal(doc.activeElement, pill(doc), 'the focus did not come back to the pill')
})

test('Escape closes the menu and returns the focus to the pill', async () => {
  const { doc, win } = await mount()
  await press(win, pill(doc))
  assert.equal(doc.activeElement, items(doc)[1], 'the agent in use did not take the focus on open')
  await key(win, doc.activeElement, 'Escape')
  assert.equal(menu(doc), null, 'Escape did not close the menu')
  assert.equal(doc.activeElement, pill(doc), 'Escape did not give the focus back')
})

test('the arrow keys, Home and End move between the agents and wrap', async () => {
  const { doc, win } = await mount()
  await press(win, pill(doc))
  const rows = items(doc)
  assert.equal(doc.activeElement, rows[1])
  await key(win, doc.activeElement, 'ArrowDown')
  assert.equal(doc.activeElement, rows[2])
  await key(win, doc.activeElement, 'ArrowUp')
  await key(win, doc.activeElement, 'ArrowUp')
  assert.equal(doc.activeElement, rows[0])
  await key(win, doc.activeElement, 'ArrowUp')
  assert.equal(doc.activeElement, rows[4], 'the last agent did not wrap from the first')
  await key(win, doc.activeElement, 'Home')
  assert.equal(doc.activeElement, rows[0])
  await key(win, doc.activeElement, 'End')
  assert.equal(doc.activeElement, rows[4])
})

test('the two foot buttons say what they do and hand over to the agent drawer', async () => {
  const { doc, calls, win } = await mount()
  await press(win, pill(doc))
  const buttons = [...doc.querySelectorAll('.agent-menu-foot button')]
  assert.deepEqual(buttons.map((b) => b.textContent), ['Verify this agent', 'Agent settings'])
  await press(win, buttons[0])
  assert.equal(calls.verify, 1)
  assert.equal(menu(doc), null)
  await press(win, pill(doc))
  await press(win, [...doc.querySelectorAll('.agent-menu-foot button')][1])
  assert.equal(calls.settings, 1)
})

test('every control in the strip has a name', async () => {
  const { doc, win } = await mount({ busy: true })
  await press(win, pill(doc))
  const controls = [...doc.querySelectorAll('.agent-menu button')]
  assert.ok(controls.length >= 8, 'the menu has fewer controls than it lists')
  for (const control of controls) assert.ok(nameOf(control).length > 0, `a control has no name: ${control.outerHTML.slice(0, 80)}`)
})

test('a running research job says so in words, on the pill and on the agent in use', async () => {
  const { doc, win } = await mount({ busy: true })
  assert.match(pill(doc).textContent, /Working/)
  assert.match(nameOf(pill(doc)), /Working now/)
  await press(win, pill(doc))
  const inUse = items(doc).find((row) => row.getAttribute('aria-checked') === 'true')
  assert.match(nameOf(inUse), /Working now/)
})

test('a demo says nothing was checked, and does not invent a state for any agent', async () => {
  const { doc, win } = await mount({ live: false, market: null })
  assert.match(nameOf(pill(doc)), /Not checked in demo/)
  await press(win, pill(doc))
  assert.ok(items(doc).every((row) => !/Ready|Needs|Not installed/.test(row.textContent)), 'a demo row claims a state the engine never gave')
})

test('an agent the engine did not report says so, and the market before its read says Checking', async () => {
  const { doc, win } = await mount({ market: null })
  await press(win, pill(doc))
  const claude = items(doc).find((row) => row.querySelector('strong').textContent === 'Claude Code')
  assert.equal(claude.querySelector('small').textContent, 'Checking')

  await React.act(async () => root.render(React.createElement(AgentMenu, { agents: AGENTS, preferred: 'claude-code', busy: false, live: true, market: new Map(), tour: 'agent-pill', onOpen() {}, onChoose() {}, onVerify() {}, onSettings() {} })))
  const later = items(doc).find((row) => row.querySelector('strong').textContent === 'Claude Code')
  assert.equal(later.querySelector('small').textContent, 'Not reported by the engine')
})

// ---- the usage card's one sentence, and the words for an agent's standing ----

const example = () => usage.demoMeters(1_000)

test('the verdict says how much of the tightest window is used, in plain words', () => {
  const read = example()
  assert.equal(usage.verdictLine(read, []), 'You have used 62% of the tightest window. Research will keep working.')
})

test('a window running short says research may run short, and a full one says runs may be refused', () => {
  const near = example()
  near.resources.cli_agent.limits['claude-code'].five_hour.used = 0.9
  assert.equal(usage.verdictLine(near, []), 'You have used 90% of the tightest window. Research may run short before it resets.')

  const full = example()
  full.resources.cli_agent.limits['claude-code'].five_hour.used = 0.97
  assert.equal(usage.verdictLine(full, []), 'You have used 97% of the tightest window. Runs may be refused until it resets.')

  const refused = example()
  refused.resources.cli_agent.limits['claude-code'].five_hour = { used: null, status: 'rejected', resets_at: null, overage: null, seen_at: null }
  assert.equal(usage.verdictLine(refused, []), 'The coding agent says its limit is reached, so runs may be refused until it resets.')
})

test('a passed daily cap is named ahead of the window, and several are joined in words', () => {
  const read = example()
  assert.equal(usage.verdictLine(read, ['web_search']), 'You have passed your daily cap for web search.')
  assert.equal(usage.verdictLine(read, ['cli_agent', 'llm_api', 'web_search']), 'You have passed your daily cap for the coding agent, the LLM API and web search.')
})

test('with no coding agent limit reported, the sentence says the day spend, or that nothing is priced', () => {
  const read = example()
  delete read.resources.cli_agent.limits
  assert.equal(usage.verdictLine(read, []), 'In the last 24 hours you have spent $0.21 on LLM APIs. No coding agent limit has been reported.')

  const unpriced = example()
  delete unpriced.resources.cli_agent.limits
  unpriced.resources.llm_api.windows['24h'].usd = null
  assert.equal(usage.verdictLine(unpriced, []), 'Kriko has counted use. No coding agent limit has been reported yet.')
})

test('no meters, or nothing used, gives no sentence at all', () => {
  assert.equal(usage.verdictLine(null, []), '')
  const quiet = example()
  for (const id of Object.keys(quiet.resources)) quiet.resources[id].used = false
  assert.equal(usage.verdictLine(quiet, []), '')
})

test('an agent standing is said in words, and a hosted agent that needs setup needs a key', () => {
  assert.equal(usage.standingWords('ready', 'cli'), 'Ready')
  assert.equal(usage.standingWords('needs_setup', 'api'), 'Needs a key')
  assert.equal(usage.standingWords('needs_setup', 'local'), 'Needs setup')
  assert.equal(usage.standingWords('not_installed', 'cli'), 'Not installed')
  assert.equal(usage.standingWords('something_new', 'cli'), 'Not ready')
})

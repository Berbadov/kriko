import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import ts from 'typescript'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { JSDOM } from 'jsdom'
import { realSettingsParts, unnamedButtons } from './settings_support.mjs'

const h = React.createElement

/**
 * A row in the settings drawer is an icon, a name and one control. The text that
 * used to sit under a label as a grey line is gone, and the three groups that
 * carried the most of it (web search, proxies, chat clients) are drawn here from
 * the engine's own shapes to prove it. What stays is a state pill beside the name,
 * an error, or an icon whose tooltip holds the one fact a setting must keep (data
 * that leaves, money). Every icon-only press carries its name.
 */

const compile = (source) =>
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText

async function load(file, exportName, stubs) {
  const directory = await mkdtemp(join(process.cwd(), '.settings-rows-'))
  const require = createRequire(import.meta.url)
  const loader = require('node:module')
  const originalLoad = loader._load
  const compiled = join(directory, 'Group.cjs')
  const parts = await realSettingsParts(directory)
  await writeFile(compiled, compile(await readFile(file, 'utf8')) + `\nexports.${exportName} = ${exportName}\n`)
  loader._load = function (request, parent, isMain) {
    if (parent?.filename === compiled && request.startsWith('.')) {
      if (request.endsWith('.css')) return {}
      if (request in parts) return parts[request]
      if (!(request in stubs)) throw new Error(`no stub for ${request}`)
      return stubs[request]
    }
    return originalLoad.call(this, request, parent, isMain)
  }
  const component = require(compiled)[exportName]
  return {
    component,
    done: () => {
      loader._load = originalLoad
      return rm(directory, { recursive: true, force: true })
    },
  }
}

const controls = {
  Select: ({ label }) => h('select', { 'aria-label': label }),
  Switch: ({ label }) => h('button', { role: 'switch', 'aria-label': label }),
}

/** Every row's label span holds text only: no second line under it. */
function assertRowsAreLabelAndControl(document) {
  const rows = [...document.querySelectorAll('.setting')]
  assert.ok(rows.length > 0, 'the group drew no rows')
  for (const row of rows) {
    assert.equal(row.querySelector('small'), null, `a row keeps a sub-line: ${row.textContent}`)
  }
  assert.deepEqual(unnamedButtons(document), [], 'an icon-only control has no name')
}

const health = { calls: 4, recent: 4, last_success: Math.round(Date.now() / 1000) - 60, last_failure: null, last_problem: '', miss_rate: 0 }
const quiet = { calls: 0, recent: 0, last_success: null, last_failure: null, last_problem: '', miss_rate: null }

test('web search draws its first choice and its fallbacks as rows with no sub-line, and a cloud says that a hosted provider sees the words', async () => {
  const doc = {
    primary: 'a',
    fallback: [],
    automatic: true,
    effective: ['a'],
    providers: [
      { id: 'a', label: 'Alpha', needs_key: false, key_saved: null, ready: true, note: 'Runs here. Long description that no longer shows.', health },
      { id: 'b', label: 'Beta', needs_key: true, key_saved: false, ready: false, note: 'Hosted. Long description.', health: quiet },
    ],
  }
  const { component, done } = await load('src/ui/panels/SearchProviders.tsx', 'SearchProvidersGroup', {
    '../../engine/websearch': { useSearchProviders: () => ({ doc, problem: '', tested: {}, save() {}, test() {}, reload() {} }) },
    '../controls': controls,
    '../../styles/providers.css': {},
  })
  try {
    const page = new JSDOM(renderToStaticMarkup(h(component))).window.document
    assertRowsAreLabelAndControl(page)
    const text = page.body.textContent
    assert.match(text, /First/)
    assert.match(text, /Automatic/)
    assert.match(text, /Needs a key/)
    // The fact that words leave the machine is a cloud-up icon with a name.
    const cloud = page.querySelector('button[aria-label="Words sent"]')
    assert.ok(cloud, 'the data note is an icon with a name')
    assert.match(page.getElementById(cloud.getAttribute('aria-describedby')).textContent, /A hosted provider receives the words you search/)
    assert.doesNotMatch(text, /Long description/, 'the engine description is not drawn under a provider')
    assert.ok(page.querySelector('button[aria-label="Test Alpha"]'), 'the test press is named')
    // Alpha answered lately, so its icon carries a live dot. Beta has not.
    assert.equal(page.querySelectorAll('.live-dot').length, 1)
  } finally {
    await done()
  }
})

test('proxies keep one fact about who sees the pages behind an icon, and fold the rest away', async () => {
  const doc = { enabled: true, pool: [], login_saved: false, active: false, learned: null, limits: { tries: 3, retire_seconds: 300, block_memory_seconds: 1800 } }
  const { component, done } = await load('src/ui/panels/Proxies.tsx', 'ProxiesGroup', {
    '../../engine/proxies': { useProxies: () => ({ doc, problem: '', checked: null, save() {}, check() {}, reload() {} }) },
    '../controls': controls,
    '../../styles/providers.css': {},
  })
  try {
    const page = new JSDOM(renderToStaticMarkup(h(component))).window.document
    assertRowsAreLabelAndControl(page)
    const eye = page.querySelector('button[aria-label="Who sees pages"]')
    assert.ok(eye, 'the data note is an icon with a name')
    assert.match(page.getElementById(eye.getAttribute('aria-describedby')).textContent, /A proxy sees which pages you read/)
    // Turned on with no address is a state, as a pill.
    assert.match(page.body.textContent, /Needs an address/)
    // The long explanation is in a closed disclosure, not under a row.
    const fold = page.querySelector('details.disclosure')
    assert.ok(fold && !fold.open && /robots\.txt/.test(fold.textContent))
  } finally {
    await done()
  }
})

test('the chat-client group is a client row with its state, the config, and a coin for the cost', async () => {
  const doc = {
    server_name: 'kriko',
    store: '/store',
    command: 'kriko',
    frozen: false,
    url: '',
    clients: [
      { id: 'generic', label: 'Any client', note: 'Where it goes depends on the client.', snippet: '{}', path: '/home/me/mcp.json', writable: true, state: 'absent' },
    ],
  }
  const { component, done } = await load('src/ui/panels/McpClients.tsx', 'McpClientsGroup', {
    '../../engine/mcpclients': { useMcpClients: () => ({ doc, problem: '', writing: '', write() {} }) },
    '../clipboard': { copyText: async () => true },
    '../controls': controls,
    '../../styles/mcp.css': {},
  })
  try {
    const page = new JSDOM(renderToStaticMarkup(h(component))).window.document
    assertRowsAreLabelAndControl(page)
    const text = page.body.textContent
    assert.match(text, /Not added/)
    const coin = page.querySelector('button[aria-label="Cost"]')
    assert.ok(coin, 'the cost note is an icon with a name')
    assert.match(page.getElementById(coin.getAttribute('aria-describedby')).textContent, /Lookups are free\. A chat answer uses your agent\./)
    const fold = page.querySelector('details.disclosure')
    assert.ok(fold && !fold.open && /Where it goes depends/.test(fold.textContent), 'the client note moves into a closed disclosure')
  } finally {
    await done()
  }
})

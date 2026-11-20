import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { domOf, h, loadSource, mount, unnamedButtons } from './settings_support.mjs'

/**
 * The agent surface, drawn inside Research's first section.
 *
 * `src/app/web/routers/agent.py` answers all of this, and the window must call
 * every verb it serves. The first two tests keep that true by name. The rest
 * mount the section over a fake engine that answers the way the real one does,
 * so what a reader presses is what the engine is asked, and what they read back
 * is what the engine said.
 */

const read = (path) => readFile(fileURLToPath(new URL(`../${path}`, import.meta.url)), 'utf8')
const PANEL = 'src/ui/panels/Agents.tsx'

/** The one line of a module a literal sits on, so the verb beside it is read. */
function lineWith(source, needle) {
  const line = source.split('\n').find((one) => one.includes(needle))
  assert.ok(line, `no line carries ${needle}`)
  return line
}

test('the window names every agent verb the engine serves', async () => {
  const client = await read('src/engine/agents.ts')
  const calls = [
    ["'/api/agent-market'", /get</],
    ["'/api/agent-targets'", /get</],
    ["'/api/agent-skill'", /get</],
    ['`/api/agent-targets/${seg(targetId)}/connect`', /post</],
    ['`/api/agent-targets/${seg(targetId)}/skill`', /post</],
    ["'/api/agent-verify'", /post</],
    ['`/api/agents/${seg(agentId)}/install`', /post</],
  ]
  for (const [path, verb] of calls) {
    assert.match(lineWith(client, path), verb, `${path} is not called through ${verb}`)
  }
  assert.match(client, /import \{ get, post, seg \} from '\.\/api'/)
  assert.doesNotMatch(client, /DEMO_/, 'this client carries no invented rows')
})

test('the Agent section calls every verb the client names, and names no path of its own', async () => {
  const panel = await read(PANEL)
  for (const call of ['readMarket', 'readTargets', 'readSkill', 'connectTarget', 'rewriteTargetSkill', 'verifyAgent', 'installAgent']) {
    assert.ok(panel.includes(call), `the section no longer calls ${call}`)
  }
  // The install is a job: a durable id comes back and the row follows it.
  assert.match(panel, /installAgent\(agent\.id\)[\s\S]{0,200}followJob\(/)
  const code = panel.replace(/\/\*[\s\S]*?\*\//g, '')
  assert.doesNotMatch(code, /['"`]\/api\//, 'the section writes its own engine path')
  // A failure is the engine's own sentence: every press hands the caught error on.
  assert.doesNotMatch(code, /failed\((?!error,)/, 'a failure is answered with a sentence of our own')
})

// ---- rendering over a fake engine ----

/** The engine the section talks to, for the whole file. The module is compiled
 *  once, and every test resets this world: the routes it answers, the mode it
 *  reports, and the calls it has been asked. */
const world = { routes: {}, mode: 'live', calls: [], followJob: null }

const answer = (method, path) => {
  world.calls.push(`${method} ${path}`)
  const route = world.routes[`${method} ${path}`]
  if (route === undefined) throw new Error(`the fake engine has no route for ${method} ${path}`)
  return typeof route === 'function' ? route() : route
}

const engineStub = { useEngine: () => ({ mode: world.mode, setPreferred() {} }) }

const { AgentsSection } = loadSource(PANEL, {
  './api': {
    get: async (path) => answer('GET', path),
    post: async (path) => answer('POST', path),
    put: async () => {
      throw new Error('the Agent section does not write preferences itself')
    },
    del: async () => {
      throw new Error('the Agent section deletes nothing')
    },
    seg: (id) => encodeURIComponent(id),
    notifyAgentsChanged() {},
  },
  '../../engine/Engine': engineStub,
  './Engine': engineStub,
  '../../engine/jobs': {
    followJob: async (jobId, onStep, wanted) => (world.followJob ?? (async () => ({ state: 'succeeded', message: 'Installed.', result: {} })))(jobId, onStep, wanted),
  },
  '../ReportButton': { ReportButton: () => null },
  '../Disclosure': { Disclosure: ({ title, children }) => h('details', null, h('summary', null, title), children) },
  '../ExternalLink': { ExternalLink: (props) => h('a', { href: props.href, className: props.className }, props.children) },
  '../Icon': { Icon: () => null },
})

const MARKET = {
  chosen: 'claude-code',
  agents: [
    { id: 'claude-code', label: 'Claude Code', kind: 'cli', state: 'ready', detail: '', where: 'C:/bin/claude.exe', wiring: 'stale', action: 'use', can_install: false, url: '', chosen: true, local: false },
    { id: 'cursor', label: 'Cursor', kind: 'cli', state: 'ready', detail: '', where: 'cursor', wiring: '', action: 'use', can_install: false, url: '', chosen: false, local: false },
    { id: 'codex', label: 'Codex', kind: 'cli', state: 'not_installed', detail: 'npm install -g @openai/codex', where: 'codex', wiring: '', action: 'install', can_install: true, url: 'https://example.test/codex', chosen: false, local: false },
    { id: 'mistral-api', label: 'Mistral API', kind: 'api', state: 'needs_setup', detail: 'save a key for it in Keys and models', where: '', wiring: '', action: 'setup', can_install: false, url: 'https://example.test/keys', chosen: false, local: false },
  ],
}

const TARGETS = {
  server_name: 'kriko',
  store: '/home/reader/.kriko/knowledge.sqlite',
  targets: [
    { id: 'claude-code', label: 'Claude Code', path: '/home/reader/.claude.json', exists: true, state: 'stale', detail: 'points at a different store than this window is reading', skill: { supported: true, path: '/home/reader/.claude/skills/kriko/SKILL.md', present: true, stale: true } },
    { id: 'cursor', label: 'Cursor', path: '/home/reader/.cursor/mcp.json', exists: false, state: 'absent', skill: { supported: false, path: null, present: false, stale: false } },
  ],
}

const PREFS = {
  chosen: { preferred_harness: 'claude-code' },
  effective: { ready: true, reason: '', harness: 'claude-code', harness_ready: true, harness_note: '' },
  harnesses: [
    { id: 'claude-code', label: 'Claude Code', llm: '', llms: ['sonnet', 'opus'], effort: '', efforts: [], search: 'own', search_choices: [{ id: 'own', label: "The agent's own" }, { id: 'kriko', label: "Kriko's" }] },
    { id: 'cursor', label: 'Cursor', llm: '', llms: [], effort: '', efforts: [], search: 'own', search_choices: [] },
  ],
  unusable: [],
  missing: [],
  source_kinds: [],
  research: { sources: 0, kinds: [], thoroughness: 50, validation_sensitivity: 50 },
  search_providers: [],
  classification_providers: [],
  market_regions: [],
}

/** The section over the fake engine, reset for one test. `calls` is the list the
 *  engine has been asked, read live; `saves` is what the section saved. */
function section({ routes = {}, mode = 'live', prefs = PREFS, followJob = null } = {}) {
  world.routes = { 'GET /api/agent-market': MARKET, 'GET /api/agent-targets': TARGETS, ...routes }
  world.mode = mode
  world.calls = []
  world.followJob = followJob
  const saves = []
  const element = h(AgentsSection, {
    doc: prefs,
    busy: false,
    save: (patch) => saves.push(patch),
    reload: async () => {},
  })
  return { element, calls: world.calls, saves }
}

const press = (view, text) => {
  const node = [...view.document.querySelectorAll('button, a')].find((one) => one.textContent.trim() === text)
  assert.ok(node, `no control reads "${text}"`)
  return node
}

const rowOf = (view, name) => [...view.document.querySelectorAll('.research-agent')].find((row) => row.querySelector('.k-row-title')?.textContent.includes(name))

test('the answering agent is the first row, and Change opens the list in place', async () => {
  const { element } = section()
  const view = await mount(element)
  try {
    await view.flush()
    const first = view.document.querySelector('[data-setting]')
    assert.match(first.querySelector('[data-setting-label]').textContent, /Answering agent/)
    assert.match(first.querySelector('.k-row-value').textContent, /Claude Code/)
    assert.equal(view.document.querySelectorAll('.research-agent').length, 0, 'the list is shut until Change is pressed')

    await view.click(press(view, 'Change'))
    assert.equal(press(view, 'Close').getAttribute('aria-expanded'), 'true')
    const rows = [...view.document.querySelectorAll('.research-agent')].map((row) => row.querySelector('.k-row-title').textContent)
    assert.deepEqual(rows.map((text) => text.replace(/Ready|Not installed|Needs a key|Needs setup/g, '').trim()), ['Claude Code', 'Cursor', 'Codex', 'Mistral API'])
    assert.ok(rowOf(view, 'Codex').querySelector('.k-pill').textContent.includes('Not installed'))
    assert.ok(rowOf(view, 'Mistral API').querySelector('.k-pill').textContent.includes('Needs a key'))
    assert.ok(rowOf(view, 'Cursor').querySelector('.k-pill').textContent.includes('Ready'))
    assert.deepEqual(unnamedButtons(view.document), [], 'a control has no name')
  } finally {
    await view.unmount()
  }
})

test('each row offers only the words its state allows', async () => {
  const { element } = section()
  const view = await mount(element)
  try {
    await view.click(press(view, 'Change'))
    await view.flush()
    const words = (name) => [...rowOf(view, name).querySelectorAll('button, a')].map((node) => node.textContent.trim())
    assert.deepEqual(words('Claude Code'), ['Verify', 'Set up'], 'the answering agent is verified and wired, not used again')
    assert.deepEqual(words('Cursor'), ['Use', 'Set up'], 'a ready agent that is not answering is offered for use, and wired')
    assert.deepEqual(words('Codex'), ['Install', 'Get it'])
    assert.deepEqual(words('Mistral API'), ['Get it'], 'a keyed agent offers the link to its key, not an install')
  } finally {
    await view.unmount()
  }
})

test('Use saves the chosen agent as the preferred one', async () => {
  const { element, saves } = section()
  const view = await mount(element)
  try {
    await view.click(press(view, 'Change'))
    await view.click(press(view, 'Use'))
    assert.deepEqual(saves, [{ preferred_harness: 'cursor' }])
  } finally {
    await view.unmount()
  }
})

test('Verify runs the advertised command and reads back the engine answer', async () => {
  const { element, calls } = section({
    routes: {
      'POST /api/agent-verify': { ok: true, server: 'kriko', tools: ['research_brief'], steps: [{ id: 'start', state: 'ok' }, { id: 'tools', state: 'ok' }], log: '$ kriko --mcp' },
    },
  })
  const view = await mount(element)
  try {
    await view.click(press(view, 'Change'))
    await view.click(press(view, 'Verify'))
    await view.flush()
    assert.ok(calls.includes('POST /api/agent-verify'))
    // The report sits under the answering agent's row, so the page is read, not the row.
    assert.match(view.document.body.textContent, /kriko answered with 1 tool\(s\)/)
    assert.match(view.document.body.textContent, /research_brief/)
  } finally {
    await view.unmount()
  }
})

test('a verify that fails says why, in the engine words', async () => {
  const detail = 'could not start the command: [WinError 2] The system cannot find the file specified'
  const { element } = section({
    routes: { 'POST /api/agent-verify': { ok: false, detail, steps: [{ id: 'start', state: 'failed' }], log: '' } },
  })
  const view = await mount(element)
  try {
    await view.click(press(view, 'Change'))
    await view.click(press(view, 'Verify'))
    await view.flush()
    const alert = view.document.querySelector('[role="alert"]')
    assert.ok(alert, 'a failed verify is an alert')
    assert.ok(alert.textContent.includes(detail))
  } finally {
    await view.unmount()
  }
})

test('a verify the engine cannot answer shows that error, not a sentence of the window', async () => {
  const { element } = section({
    routes: { 'POST /api/agent-verify': () => { throw new Error('The engine is not answering.') } },
  })
  const view = await mount(element)
  try {
    await view.click(press(view, 'Change'))
    await view.click(press(view, 'Verify'))
    await view.flush()
    assert.ok(view.document.querySelector('[role="alert"]').textContent.includes('The engine is not answering.'))
  } finally {
    await view.unmount()
  }
})

test('Install runs the installer as a job and follows it into the row', async () => {
  const { element, calls } = section({
    routes: {
      'POST /api/agents/codex/install': { job_id: 'job-1', kind: 'agent_install' },
      'GET /api/agent-market': MARKET,
    },
    followJob: async (jobId, onStep) => {
      assert.equal(jobId, 'job-1')
      onStep({ message: 'Downloading the installer' })
      return { state: 'succeeded', message: 'Installed.', result: { path: '/bin/codex' } }
    },
  })
  const view = await mount(element)
  try {
    await view.click(press(view, 'Change'))
    await view.click(press(view, 'Install'))
    await view.flush()
    assert.ok(calls.includes('POST /api/agents/codex/install'))
    assert.match(rowOf(view, 'Codex').textContent, /Installed\./)
    assert.match(rowOf(view, 'Codex').textContent, /\/bin\/codex/)
  } finally {
    await view.unmount()
  }
})

test('Set up writes the config and reads back what the engine says it is now', async () => {
  const { element, calls } = section({
    routes: {
      'POST /api/agent-targets/claude-code/connect': { ...TARGETS.targets[0], state: 'connected', detail: '', skill: '/home/reader/.claude/skills/kriko/SKILL.md' },
    },
  })
  const view = await mount(element)
  try {
    await view.click(press(view, 'Change'))
    await view.click(press(view, 'Set up'))
    await view.flush()
    assert.ok(calls.includes('POST /api/agent-targets/claude-code/connect'))
    assert.match(rowOf(view, 'Claude Code').textContent, /Claude Code now reads this store\./)
  } finally {
    await view.unmount()
  }
})

test('a market that did not answer says so, and draws no agent only the market knows', async () => {
  const { element } = section({
    routes: { 'GET /api/agent-market': () => { throw new Error('The market could not be read.') } },
  })
  const view = await mount(element)
  try {
    await view.click(press(view, 'Change'))
    await view.flush()
    assert.ok(view.document.body.textContent.includes('The market could not be read.'))
    // The store's own agents still answer from /api/prefs; the ones only the market knows are not drawn.
    assert.ok(rowOf(view, 'Claude Code'), 'the store\'s own agent is still listed')
    assert.ok(!rowOf(view, 'Codex'), 'an agent only the market knows is drawn without a market')
    assert.ok(!rowOf(view, 'Mistral API'), 'an agent only the market knows is drawn without a market')
  } finally {
    await view.unmount()
  }
})

test('with no engine, the list is the store\'s own, and no press reaches the machine', async () => {
  for (const mode of ['demo', 'offline', 'checking']) {
    const { element, calls } = section({ mode })
    const view = await mount(element)
    try {
      await view.click(press(view, 'Change'))
      await view.flush()
      const names = [...view.document.querySelectorAll('.research-agent .k-row-title')].map((node) => node.textContent)
      assert.ok(names.some((text) => text.includes('Claude Code')), `${mode} dropped the store's own agent`)
      for (const verb of ['Verify', 'Install', 'Set up', 'Check again']) {
        assert.ok(![...view.document.querySelectorAll('button')].some((node) => node.textContent === verb), `${mode} offers ${verb}`)
      }
      assert.deepEqual(calls, [], `${mode} asked the engine for something`)
    } finally {
      await view.unmount()
    }
  }
})

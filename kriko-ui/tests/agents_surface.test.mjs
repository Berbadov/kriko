import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import ts from 'typescript'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { JSDOM } from 'jsdom'

/**
 * The desktop app's half of the agent-integration surface.
 *
 * `src/app/web/routers/agent.py` answered all of this and the window called
 * none of it: the engine could list a market, wire a harness, render its
 * protocol, verify one and install one, and no screen asked. These are the
 * tests that keep that from happening again. The first one names every verb
 * here, so deleting a call site fails; the rest render the screen over
 * responses the engine would send, so a screen that started drawing its own
 * rows — or its own failure sentence — fails too.
 */

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')

/** The one line of a module a literal sits on, so the verb beside it is read. */
function lineWith(source, needle) {
  const line = source.split('\n').find((one) => one.includes(needle))
  assert.ok(line, `no line carries ${needle}`)
  return line
}

test('the window names every agent verb the engine serves', async () => {
  const client = await read('src/engine/agents.ts')

  // Each entry is a path and the verb it must be called through, as the source
  // writes both on one line.
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

  // Every id that reaches a path is one the engine gave us, encoded once.
  assert.match(client, /export const seg|import \{ get, post, seg \}/)
  assert.doesNotMatch(client, /DEMO_/, 'this client carries no invented rows')
})

test('the Agents panel draws every call the client names, and names no path of its own', async () => {
  const panel = await read('src/ui/panels/Agents.tsx')
  for (const call of ['readMarket', 'readTargets', 'readSkill', 'connectTarget', 'rewriteTargetSkill', 'verifyAgent', 'installAgent']) {
    assert.ok(panel.includes(call), `the panel no longer calls ${call}`)
  }
  // The install is a job: a durable id comes back and the screen follows it the
  // way every other job-starting screen does.
  assert.match(panel, /installAgent\(agent\.id\)[\s\S]{0,200}followJob\(/)
  // One place names a route: `engine/agents.ts`. A panel that spelled its own
  // `/api/...` would drift from the client the route guard reads. Comments are
  // where this screen explains itself and may well name a route, so only the
  // code that can run is read here.
  const code = panel.replace(/\/\*[\s\S]*?\*\//g, '')
  assert.doesNotMatch(code, /['"`]\/api\//, 'the panel writes its own engine path')
  // A failure is the engine's own sentence, so every press that can fail hands
  // the caught error to the shared `failed()` helper.
  assert.doesNotMatch(code, /failed\((?!error,)/, 'a failure is answered with a sentence of our own')
})

// ---- rendering, over responses the engine would send ----

const COMPILER = {
  module: ts.ModuleKind.CommonJS,
  jsx: ts.JsxEmit.ReactJSX,
  target: ts.ScriptTarget.ES2022,
}

async function compile(directory, name, out) {
  const source = await read(name)
  const code = ts.transpileModule(source, { compilerOptions: COMPILER }).outputText
  await writeFile(join(directory, out), code)
}

/** The panel compiled with the engine modules stubbed: the panel's own drawing
 *  is under test, not the React context it sits in. The two compiled files get
 *  names that differ by more than case, because on Windows they would otherwise
 *  be one file and the client would overwrite the panel. */
async function panel() {
  const directory = await mkdtemp(join(process.cwd(), '.agents-surface-'))
  const require = createRequire(import.meta.url)
  const loader = require('node:module')
  const originalLoad = loader._load
  const compiled = join(directory, 'AgentsPanel.cjs')
  const client = join(directory, 'engine-agents.cjs')

  await compile(directory, 'src/engine/agents.ts', 'engine-agents.cjs')
  const panelSource = await read('src/ui/panels/Agents.tsx')
  const panelCode = ts.transpileModule(panelSource, { compilerOptions: COMPILER }).outputText
  await writeFile(
    compiled,
    panelCode + '\nexports.AgentsPanel = AgentsPanel;\nexports.MarketRows = MarketRows;\n'
      + 'exports.TargetsRows = TargetsRows;\nexports.VerifyReport = VerifyReport;\n'
      + 'exports.SkillReport = SkillReport;\n',
  )

  // What the panel reads around itself. The engine's own mode is the one dial
  // the rendering test needs to move, so it is read from here at call time.
  const mode = { now: 'live' }
  const prefs = {
    chosen: { preferred_harness: 'claude-code' },
    effective: { ready: true, reason: '', harness: 'claude-code', harness_ready: true, harness_note: '' },
    harnesses: [], unusable: [], missing: [],
  }

  loader._load = function (request, parent, isMain) {
    // The real helpers (`IDLE`, `wiringWords`, `skillWords`) are under test too,
    // so the client module is loaded for real; only its HTTP layer is not.
    if (parent?.filename === client && request.startsWith('.')) return {}
    if (parent?.filename === compiled) {
      if (request === '../../engine/agents') return require(client)
      if (request === 'motion/react') return { AnimatePresence: ({ children }) => children, motion: {} }
      if (request === '../../engine/Engine') return { useEngine: () => ({ mode: mode.now }) }
      if (request === '../../engine/settings') return { usePrefsDoc: () => ({ doc: prefs, problem: '', busy: false, save() {}, reload() {} }) }
      if (request === '../../engine/jobs') return { followJob: async () => null }
      if (request === '../../prefs') return { usePrefs: () => ({ motion: { tx: { soft: {} } } }) }
      if (request.startsWith('.')) {
        // The panel sits in `src/ui/panels`, so these are its own siblings.
        if (request === '../Icon') return { Icon: () => React.createElement('svg') }
        if (request === '../controls') return { Select: () => React.createElement('select') }
        // The fold-away detail is Arc's accordion in the app; a plain details
        // element here keeps what the screen says readable in static markup.
        if (request === '../Disclosure') {
          return { Disclosure: ({ title, children }) => React.createElement('details', null, React.createElement('summary', null, title), children) }
        }
        if (request === '../ExternalLink') {
          return { ExternalLink: (props) => React.createElement('a', { href: props.href, className: props.className }, props.children) }
        }
        return {}
      }
    }
    return originalLoad.call(this, request, parent, isMain)
  }

  return {
    require: () => require(compiled),
    setMode: (next) => { mode.now = next },
    done: async () => {
      loader._load = originalLoad
      await rm(directory, { recursive: true, force: true })
    },
  }
}

const render = (element) => {
  const dom = new JSDOM(renderToStaticMarkup(element))
  const text = dom.window.document.body.textContent
  const html = dom.window.document.body.innerHTML
  return { text, html, dom, close: () => dom.window.close() }
}

const MARKET = {
  chosen: 'claude-code',
  agents: [
    { id: 'claude-code', label: 'Claude Code', kind: 'cli', state: 'ready', detail: '', where: 'C:/bin/claude.exe', wiring: 'connected', action: 'use', can_install: false, url: '', chosen: true, local: false },
    { id: 'codex', label: 'Codex', kind: 'cli', state: 'not_installed', detail: 'npm install -g @openai/codex', where: 'codex', wiring: '', action: 'install', can_install: true, url: 'https://example.test/codex', chosen: false, local: false },
    { id: 'mistral-api', label: 'Mistral API', kind: 'api', state: 'not_installed', detail: 'save a key for it in Settings', where: '', wiring: '', action: 'setup', can_install: false, url: 'https://example.test/keys', chosen: false, local: false },
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

test('the panel draws no agent the engine has not reported', async () => {
  const harness = await panel()
  try {
    const { AgentsPanel } = harness.require()

    // A live engine that has not answered yet is a question still being asked,
    // never a machine with nothing on it.
    const waiting = render(React.createElement(AgentsPanel, {}))
    try {
      assert.match(waiting.text, /Reading the market/)
      assert.match(waiting.text, /Reading the harnesses/)
      assert.equal((waiting.html.match(/<li/g) ?? []).length, 0, 'a row was drawn before the engine answered')
    } finally {
      waiting.close()
    }

    // With no engine there is nothing to draw, and the screen says exactly that
    // rather than filling the gap with a list of its own.
    for (const mode of ['demo', 'offline']) {
      harness.setMode(mode)
      const none = render(React.createElement(AgentsPanel, {}))
      try {
        assert.match(none.text, /No engine is connected/)
        assert.doesNotMatch(none.text, /Reading the market/)
        assert.doesNotMatch(none.text, /The market|Connected agents|The protocol|Does it actually run/)
        assert.equal((none.html.match(/<li/g) ?? []).length, 0, `${mode} drew rows with no engine`)
      } finally {
        none.close()
      }
    }

    // While the engine is being looked for, it says so in its own word.
    harness.setMode('checking')
    const checking = render(React.createElement(AgentsPanel, {}))
    try {
      assert.match(checking.text, /Looking for the engine/)
    } finally {
      checking.close()
    }
  } finally {
    await harness.done()
  }
})

test('the market draws the engine rows, its reasons and its one press', async () => {
  const harness = await panel()
  try {
    const { MarketRows } = harness.require()
    const view = render(React.createElement(MarketRows, { doc: MARKET, presses: {}, onInstall() {} }))
    try {
      for (const said of ['Claude Code', 'Codex', 'Mistral API']) {
        assert.ok(view.text.includes(said), `the market dropped ${said}`)
      }
      // The engine's own sentence and the command it looked for, verbatim.
      assert.ok(view.text.includes('npm install -g @openai/codex'))
      assert.ok(view.text.includes('C:/bin/claude.exe'))
      assert.ok(view.text.includes('save a key for it in Settings'))
      // The engine's own word for what is left to press.
      assert.ok(view.text.includes('Next: install'))
      assert.ok(view.text.includes('Next: use'))
      // A keyed agent with no install of its own offers the engine's link, not
      // a press that would 404.
      assert.equal((view.html.match(/<button[^>]*>Install<\/button>/g) ?? []).length, 1)
      assert.ok(view.html.includes('https://example.test/codex'))
      assert.ok(view.html.includes('https://example.test/keys'))
      // The choice is the engine's, and it is marked as such.
      assert.ok(view.text.includes('Default'))
    } finally {
      view.close()
    }

    // Nothing found is reported as nothing found. Not a default list.
    const none = render(React.createElement(MarketRows, { doc: { agents: [], chosen: '' }, presses: {}, onInstall() {} }))
    try {
      assert.match(none.text, /engine reported no way to answer/)
      for (const name of ['Claude Code', 'Codex', 'Mistral API']) assert.ok(!none.text.includes(name))
    } finally {
      none.close()
    }
  } finally {
    await harness.done()
  }
})

test('the targets show each harness, its file, and the protocol on disk', async () => {
  const harness = await panel()
  try {
    const { TargetsRows } = harness.require()
    const view = render(React.createElement(TargetsRows, { doc: TARGETS, presses: {}, onConnect() {}, onSkill() {} }))
    try {
      assert.ok(view.text.includes('kriko'), 'the server name the config is written under is missing')
      assert.ok(view.text.includes('/home/reader/.kriko/knowledge.sqlite'))
      assert.ok(view.text.includes('/home/reader/.claude.json'))
      // The engine's reason, not a paraphrase of it.
      assert.ok(view.text.includes('points at a different store than this window is reading'))
      assert.ok(view.text.includes('Wired to a different store'))
      assert.ok(view.text.includes('The protocol on disk is not the one this build would write'))
      // A harness with nowhere to keep a protocol says so, and is not offered
      // a press that would write nothing.
      assert.ok(view.text.includes('This harness has nowhere to keep the protocol'))
      assert.equal((view.html.match(/>Write the protocol<\/button>/g) ?? []).length, 2)
      assert.equal((view.html.match(/disabled=""/g) ?? []).length, 1)
    } finally {
      view.close()
    }

    const none = render(React.createElement(TargetsRows, { doc: { ...TARGETS, targets: [] }, presses: {}, onConnect() {}, onSkill() {} }))
    try {
      assert.match(none.text, /engine reported no harness/)
    } finally {
      none.close()
    }
  } finally {
    await harness.done()
  }
})

test('a verify that failed repeats the engine, step by step', async () => {
  const harness = await panel()
  try {
    const { VerifyReport } = harness.require()
    const answer = {
      ok: false,
      detail: 'could not start the command: [WinError 2] The system cannot find the file specified',
      steps: [{ id: 'start', state: 'failed' }, { id: 'initialize', state: 'skipped' }, { id: 'tools', state: 'skipped' }],
      log: '$ C:/x/nope --mcp --store C:/x/knowledge.sqlite\nstart: failed',
    }
    const view = render(React.createElement(VerifyReport, { answer }))
    try {
      assert.ok(view.text.includes(answer.detail), 'the engine\'s own reason is not on the screen')
      for (const said of ['start', 'initialize', 'tools', 'failed', 'skipped']) {
        assert.ok(view.text.includes(said), `the step report dropped ${said}`)
      }
      assert.ok(view.text.includes('Show the log'))
    } finally {
      view.close()
    }

    const worked = render(React.createElement(VerifyReport, { answer: { ok: true, server: 'kriko', tools: ['research_brief', 'submit_findings'], steps: [{ id: 'start', state: 'ok' }], log: '$ kriko --mcp' } }))
    try {
      assert.match(worked.text, /kriko answered/)
      assert.match(worked.text, /2 tool\(s\): research_brief, submit_findings/)
    } finally {
      worked.close()
    }
  } finally {
    await harness.done()
  }
})

test('the protocol screen shows what the engine rendered, and says when it rendered nothing', async () => {
  const harness = await panel()
  try {
    const { SkillReport } = harness.require()
    const body = '# Research protocol\n\nAnswer only from a page you have read.'
    const view = render(React.createElement(SkillReport, { doc: { name: 'kriko-research', steps: [{ tool: 'research_brief', input: 'subject', output: 'brief' }], body } }))
    try {
      assert.ok(view.text.includes('kriko-research'))
      assert.ok(view.text.includes('research_brief'))
      assert.ok(view.html.includes(body), 'the rendered protocol is not the engine\'s')
    } finally {
      view.close()
    }

    const empty = render(React.createElement(SkillReport, { doc: { name: 'kriko-research', steps: [], body: '' } }))
    try {
      assert.match(empty.text, /rendered no document/)
    } finally {
      empty.close()
    }
  } finally {
    await harness.done()
  }
})

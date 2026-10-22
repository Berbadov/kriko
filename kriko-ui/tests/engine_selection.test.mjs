// The agent the reader picked is the agent the next question uses.
//
// The report: "selected model is changing on every reply. i have to manually
// click on the agent on every prompt." Two things did that. The composer's pick
// was component state, so leaving the page — which opening a product card from
// chat does — threw it away; and every `/api/prefs` load or key save fired
// AGENTS_CHANGED_EVENT, whose refresh wrote `preferred_harness ?? ''`, so a
// reply that simply did not name one emptied the pick and the composer fell
// back to the first agent in the roster.
//
// The pick is now kept on the engine as well, and an answer that names no agent
// leaves the stored one alone.

import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import { JSDOM } from 'jsdom'
import React from 'react'
import { createRoot } from 'react-dom/client'

const require = createRequire(import.meta.url)
let directory, EngineProvider, useEngine, dom, root
let reply, saved
const api = {
  AGENTS_CHANGED_EVENT: 'kriko:agents-changed',
  inShell: () => true,
  get: (path) => reply(path),
  put: async (path, body) => {
    saved.push([path, body])
    return {}
  },
}
const originalLoad = require('node:module')._load

before(async () => {
  directory = await mkdtemp(join(process.cwd(), '.engine-selection-'))
  const code = await readFile('src/engine/Engine.tsx', 'utf8')
  const built = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText
  const enginePath = join(directory, 'Engine.cjs')
  await writeFile(enginePath, built)
  require('node:module')._load = function (request, parent, isMain) {
    if (request === './api' && parent?.filename === enginePath) return api
    if (request === '@tauri-apps/api/core') return { invoke: async () => ({ state: 'ready' }) }
    return originalLoad.call(this, request, parent, isMain)
  }
  ;({ EngineProvider, useEngine } = require(enginePath))
})

after(async () => {
  if (root) await React.act(async () => root.unmount())
  require('node:module')._load = originalLoad
  dom?.window.close()
  if (directory) await rm(directory, { recursive: true, force: true })
})

async function mountEngine(availability) {
  saved = []
  dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://localhost/' })
  globalThis.window = dom.window
  globalThis.document = dom.window.document
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  dom.window.__TAURI_INTERNALS__ = {}
  dom.window.setInterval = () => 1
  dom.window.clearInterval = () => {}
  reply = async (path) => {
    if (path === '/api/health') return { ok: true }
    if (path === '/api/agent-availability') return availability
    throw new Error(`unexpected request ${path}`)
  }
  let current
  function Probe() {
    current = useEngine()
    return React.createElement('output', null, current.preferred)
  }
  const { act } = React
  root = createRoot(dom.window.document.getElementById('root'))
  await act(async () => {
    root.render(React.createElement(EngineProvider, null, React.createElement(Probe)))
    await new Promise((resolve) => setImmediate(resolve))
  })
  return () => current
}

const ROSTER = [
  { id: 'claude-code', label: 'Claude Code' },
  { id: 'codex', label: 'Codex' },
]

test('the stored agent is what a question starts on', async () => {
  const read = await mountEngine({ harnesses: ROSTER, chosen: { preferred_harness: 'codex' } })
  assert.equal(read().mode, 'live')
  assert.equal(read().preferred, 'codex')
})

test('an answer that names no agent leaves the reader pick alone', async () => {
  const read = await mountEngine({ harnesses: ROSTER, chosen: { preferred_harness: 'codex' } })
  // A panel mounting, or a key being saved: the refresh is unconditional, the
  // empty `chosen` is not an instruction.
  reply = async (path) => {
    if (path === '/api/agent-availability') return { harnesses: ROSTER, chosen: {} }
    throw new Error(`unexpected request ${path}`)
  }
  const { act } = React
  await act(async () => {
    dom.window.dispatchEvent(new dom.window.Event(api.AGENTS_CHANGED_EVENT))
    await new Promise((resolve) => setImmediate(resolve))
  })
  assert.equal(read().preferred, 'codex', 'the pick survived a reply that did not mention it')
})

test('picking an agent for one question keeps it for the next', async () => {
  const read = await mountEngine({ harnesses: ROSTER, chosen: { preferred_harness: 'codex' } })
  const { act } = React
  await act(async () => {
    read().chooseAgent('claude-code')
    await new Promise((resolve) => setImmediate(resolve))
  })
  assert.equal(read().preferred, 'claude-code')
  assert.deepEqual(saved, [['/api/prefs', { preferred_harness: 'claude-code' }]])
})

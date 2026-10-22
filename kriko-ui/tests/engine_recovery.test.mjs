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
let directory, EngineProvider, useEngine, keepTabInside, dom, root
let reply, shell = true, engineStatus = { state: 'ready' }, intervalCallback
const api = {
  AGENTS_CHANGED_EVENT: 'kriko:agents-changed',
  inShell: () => shell,
  get: (path) => reply(path),
}
const originalLoad = require('node:module')._load

before(async () => {
  directory = await mkdtemp(join(process.cwd(), '.engine-recovery-'))
  const compile = async (source, target) => {
    const code = await readFile(source, 'utf8')
    const built = ts.transpileModule(code, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
    }).outputText
    const path = join(directory, target)
    await writeFile(path, built)
    return path
  }
  const enginePath = await compile('src/engine/Engine.tsx', 'Engine.cjs')
  const focusPath = await compile('src/ui/focusTrap.ts', 'focusTrap.cjs')
  require('node:module')._load = function (request, parent, isMain) {
    if (request === './api' && parent?.filename === enginePath) return api
    if (request === '@tauri-apps/api/core') return { invoke: async (command) => {
      assert.equal(command, 'engine_status')
      return engineStatus
    } }
    return originalLoad.call(this, request, parent, isMain)
  }
  ;({ EngineProvider, useEngine } = require(enginePath))
  ;({ keepTabInside } = require(focusPath))
})

after(async () => {
  if (root) await React.act(async () => root.unmount())
  require('node:module')._load = originalLoad
  dom?.window.close()
  if (directory) await rm(directory, { recursive: true, force: true })
})

async function mountEngine(availability) {
  dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://localhost/' })
  globalThis.window = dom.window
  globalThis.document = dom.window.document
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  intervalCallback = undefined
  dom.window.__TAURI_INTERNALS__ = {}
  dom.window.setInterval = (callback) => {
    intervalCallback = callback
    return 1
  }
  dom.window.clearInterval = () => {}
  reply = async (path) => {
    if (path === '/api/health') return { ok: true }
    if (path === '/api/agent-availability') return availability
    throw new Error(`unexpected request ${path}`)
  }
  let current
  function Probe() {
    current = useEngine()
    return React.createElement('output', { 'data-mode': current.mode }, `${current.mode}:${current.agentAvailable}`)
  }
  const { act } = React
  root = createRoot(dom.window.document.getElementById('root'))
  await act(async () => {
    root.render(React.createElement(EngineProvider, null, React.createElement(Probe)))
    await new Promise((resolve) => setImmediate(resolve))
  })
  return () => current
}

test('a live empty agent roster is exposed as unavailable while retaining the fallback label', async () => {
  const read = await mountEngine({ harnesses: [], chosen: {} })
  assert.equal(read().mode, 'live')
  assert.equal(read().agentAvailable, false)
  assert.deepEqual(read().agents, [{ id: '', label: 'Default agent', backend: 'harness' }])
})

test('a failed shell liveness check takes the app offline instead of showing demo data', async () => {
  engineStatus = { state: 'failed', title: 'Engine stopped', detail: 'database closed' }
  const read = await mountEngine({ harnesses: [{ id: 'coding', label: 'Coding agent' }], chosen: {} })
  assert.equal(read().mode, 'live')
  assert.equal(read().agentAvailable, true)
  assert.ok(intervalCallback, 'shell liveness watcher was installed')
  const { act } = React
  await act(async () => {
    intervalCallback()
    await new Promise((resolve) => setImmediate(resolve))
  })
  assert.equal(read().mode, 'offline')
  assert.match(read().problem, /Engine stopped\. database closed/)
})

test('the drawer focus helper wraps Tab in both directions and leaves interior Tab alone', () => {
  const one = new JSDOM('<div id="dialog" tabindex="-1"><button id="first">First</button><button id="middle">Middle</button><button id="last">Last</button></div>')
  const document = one.window.document
  globalThis.window = one.window
  globalThis.document = document
  const dialog = document.getElementById('dialog')
  const first = document.getElementById('first')
  const middle = document.getElementById('middle')
  const last = document.getElementById('last')
  for (const item of [first, middle, last]) Object.defineProperty(item, 'getClientRects', { value: () => [{}] })

  last.focus()
  const forward = new one.window.KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
  keepTabInside(forward, dialog)
  assert.equal(forward.defaultPrevented, true)
  assert.equal(document.activeElement, first)

  first.focus()
  const backward = new one.window.KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true })
  keepTabInside(backward, dialog)
  assert.equal(backward.defaultPrevented, true)
  assert.equal(document.activeElement, last)

  middle.focus()
  const interior = new one.window.KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
  keepTabInside(interior, dialog)
  assert.equal(interior.defaultPrevented, false)
  assert.equal(document.activeElement, middle)
  one.window.close()
})

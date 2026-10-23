// A column whose stored research agent is not on this machine offers the
// choice where the reader is standing.
//
// The observed dead end, on Compare at 1400x1000: all three columns read
// "Selected agent unavailable. Choose an available agent in Settings." while
// the top bar said "Default agent", because `/api/agent-availability` reported
// `preferred_harness: "kriko-agent"` and a roster that did not contain it.
// Sending the reader to Settings is the defect; the choice belongs in the
// column, and it may only offer what the engine listed.

import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'
import React from 'react'
import { createRoot } from 'react-dom/client'

let directory, AgentRecovery, dom, root

const OPTIONS = {
  module: ts.ModuleKind.ESNext,
  jsx: ts.JsxEmit.ReactJSX,
  target: ts.ScriptTarget.ES2022,
  esModuleInterop: true,
}

before(async () => {
  directory = await mkdtemp(join(process.cwd(), '.compare-recovery-'))
  // `Recovery.tsx` reaches its choices through `research.ts`, so both are
  // compiled into one folder and imported whole: the test then exercises the
  // shipped decision, not a copy of it.
  for (const [source, name] of [['src/compare/research.ts', 'research.mjs'],
                                ['src/compare/Recovery.tsx', 'Recovery.mjs']]) {
    const built = ts.transpileModule(await readFile(source, 'utf8'), { compilerOptions: OPTIONS }).outputText
    await writeFile(join(directory, name), built.replace("'./research'", "'./research.mjs'"))
  }
  ;({ AgentRecovery } = await import(pathToFileURL(join(directory, 'Recovery.mjs'))))
})

after(async () => {
  if (root) await React.act(async () => root.unmount())
  dom?.window.close()
  if (directory) await rm(directory, { recursive: true, force: true })
})

async function mount(props) {
  dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://localhost/' })
  globalThis.window = dom.window
  globalThis.document = dom.window.document
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const { act } = React
  const clicks = []
  root = createRoot(dom.window.document.getElementById('root'))
  await act(async () => {
    root.render(React.createElement(AgentRecovery, { ...props, onResearch: (agent) => clicks.push(agent) }))
  })
  const buttons = () => [...dom.window.document.querySelectorAll('button')]
  return {
    clicks,
    text: () => dom.window.document.getElementById('root').textContent,
    labels: () => buttons().map((one) => one.textContent),
    disabled: () => buttons().map((one) => one.disabled),
    press: async (label) => {
      const found = buttons().find((one) => one.textContent === label)
      assert.ok(found, `no button ${label} among ${JSON.stringify(buttons().map((one) => one.textContent))}`)
      await act(async () => { found.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })) })
    },
  }
}

const ROSTER = [
  { id: 'claude-code', label: 'Claude Code', backend: 'harness' },
  { id: 'local', label: 'Local agent', backend: 'local' },
]

test('the choice offered is the engine’s own roster, and never a trip to Settings', async () => {
  const view = await mount({ agents: ROSTER, preferred: 'kriko-agent', available: true })
  assert.deepEqual(view.labels(), ['Research with Claude Code', 'Research with Local agent'])
  assert.match(view.text(), /kriko-agent/, 'the engine’s own id is named back')
  assert.doesNotMatch(view.text(), /Settings/, 'the reader recovers where they stand')
})

test('a press reports the picked agent upward with the engine’s own backend', async () => {
  const view = await mount({ agents: ROSTER, preferred: 'kriko-agent', available: true })
  await view.press('Research with Local agent')
  assert.deepEqual(view.clicks, [ROSTER[1]])
})

test('with no agent listed the press asks the engine to pick, and offers no name', async () => {
  const view = await mount({ agents: [], preferred: 'kriko-agent', available: false })
  assert.deepEqual(view.labels(), ['Let the engine pick'])
  assert.doesNotMatch(view.text(), /Settings/)
  await view.press('Let the engine pick')
  assert.deepEqual(view.clicks, [{ id: '', label: 'Default agent', backend: 'harness' }])
})

test('a running research disables every choice rather than queueing a second run', async () => {
  const view = await mount({ agents: ROSTER, preferred: 'kriko-agent', available: true, busy: true })
  assert.deepEqual([...new Set(view.disabled())], [true])
})

import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import { JSDOM } from 'jsdom'
import React from 'react'
import { createRoot } from 'react-dom/client'

const require = createRequire(import.meta.url)
let directory, useBoard, dom, root

const OPTIONS = {
  module: ts.ModuleKind.CommonJS,
  jsx: ts.JsxEmit.ReactJSX,
  target: ts.ScriptTarget.ES2022,
  esModuleInterop: true,
}

before(async () => {
  directory = await mkdtemp(join(process.cwd(), '.compare-board-'))
  const built = ts.transpileModule(await readFile('src/compare/board.ts', 'utf8'), { compilerOptions: OPTIONS }).outputText
  await writeFile(join(directory, 'board.cjs'), built)
  ;({ useBoard } = require(join(directory, 'board.cjs')))
  dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://localhost/' })
  globalThis.window = dom.window
  globalThis.document = dom.window.document
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
})

after(async () => {
  if (root) await React.act(async () => root.unmount())
  dom?.window.close()
  if (directory) await rm(directory, { recursive: true, force: true })
})

async function mount() {
  const exposed = { current: null }
  const changes = []
  function Harness() {
    const board = useBoard({ onChange: (ids) => changes.push([...ids]) })
    exposed.current = board
    return React.createElement('output', null, board.slots.join(','))
  }
  if (root) await React.act(async () => root.unmount())
  const host = dom.window.document.createElement('div')
  dom.window.document.body.appendChild(host)
  root = createRoot(host)
  await React.act(async () => root.render(React.createElement(Harness)))
  return {
    changes,
    board: () => exposed.current,
    text: () => host.querySelector('output').textContent,
    act: (run) => React.act(async () => run()),
  }
}

test('two research completions in one reading both land, instead of one overwriting the other', async () => {
  const view = await mount()
  await view.act(() => view.board().place(['a', 'b']))
  const completion = view.board().add
  await view.act(() => {
    // Both finish before React renders either result. The old closure would
    // have built each next board from ['a', 'b'] and dropped one.
    assert.equal(completion('quick/job-one'), true)
    assert.equal(completion('quick/job-two'), true)
  })
  assert.equal(view.text(), 'a,b,quick/job-one,quick/job-two')
  assert.deepEqual(view.changes.at(-1), ['a', 'b', 'quick/job-one', 'quick/job-two'])
})

test('an add captured before another column joined still appends to the current board', async () => {
  const view = await mount()
  const oldAdd = view.board().add
  await view.act(() => view.board().place(['a', 'b', 'c']))
  await view.act(() => oldAdd('quick/new'))
  assert.equal(view.text(), 'a,b,c,quick/new')
})

test('a duplicate completion is a no-op and a full board refuses the fifth column', async () => {
  const view = await mount()
  await view.act(() => view.board().place(['a', 'b', 'c', 'quick/one']))
  await view.act(() => {
    assert.equal(view.board().add('quick/one'), true, 'the id is already a column')
    assert.equal(view.board().add('quick/two'), false, 'four is the whole board')
  })
  assert.equal(view.text(), 'a,b,c,quick/one')
  assert.equal(view.changes.length, 0, 'neither the duplicate nor the refusal is a save')
})

test('removing a column frees its place, and a later completion takes it', async () => {
  const view = await mount()
  await view.act(() => view.board().place(['a', 'b', 'c', 'd']))
  await view.act(() => view.board().remove('b'))
  assert.equal(view.text(), 'a,c,d')
  await view.act(() => assert.equal(view.board().add('quick/new'), true))
  assert.equal(view.text(), 'a,c,d,quick/new')
})

import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

let directory, feed, WorkTerminal

const OPTIONS = {
  module: ts.ModuleKind.ESNext,
  jsx: ts.JsxEmit.ReactJSX,
  target: ts.ScriptTarget.ES2022,
  esModuleInterop: true,
}

before(async () => {
  directory = await mkdtemp(join(process.cwd(), '.workfeed-'))
  for (const [source, name] of [['src/ui/workfeed.ts', 'workfeed.mjs'],
                                ['src/ui/WorkTerminal.tsx', 'WorkTerminal.mjs']]) {
    const built = ts.transpileModule(await readFile(source, 'utf8'), { compilerOptions: OPTIONS }).outputText
    await writeFile(join(directory, name), built.replace("'./workfeed'", "'./workfeed.mjs'"))
  }
  feed = await import(pathToFileURL(join(directory, 'workfeed.mjs')))
  ;({ WorkTerminal } = await import(pathToFileURL(join(directory, 'WorkTerminal.mjs'))))
})

after(async () => {
  if (directory) await rm(directory, { recursive: true, force: true })
})

const render = (props) => renderToStaticMarkup(React.createElement(WorkTerminal, props))

test('the terminal draws the job’s own feed, with the host of a page it read', () => {
  const reading = {
    feed: [
      { kind: 'search', text: 'searched “dualsense drift”' },
      { kind: 'source', text: 'fetched https://www.reddit.com/r/PS5/comments/x' },
      { kind: 'finding', text: 'kept 2 claims from the thread' },
    ],
  }
  const lines = feed.workLines(reading)
  assert.deepEqual(lines.map((line) => line.text), reading.feed.map((event) => event.text))
  assert.equal(lines[1].host, 'reddit.com')
  assert.equal(feed.waitReason({ feed: [reading.feed[1]] }), 'Reading reddit.com')
  assert.equal(feed.waitReason(reading), 'Checking what was found', 'the newest line is the reason, not an older one')
})

test('a finished job’s log is read when the feed is gone, and blank lines are dropped', () => {
  const lines = feed.workLines({ log: '\nnew worker started in 2.6 s\nsearched the web; fetched https://a.example/p\n' })
  assert.deepEqual(lines.map((line) => line.text), ['new worker started in 2.6 s', 'searched the web', 'fetched https://a.example/p'])
  assert.equal(lines[2].host, 'a.example')
})

test('the header says the real wait, never a made-up step', () => {
  assert.equal(feed.waitReason({ state: 'queued' }), 'Waiting for a research slot')
  assert.equal(feed.waitReason({ state: 'queued', agent: 'OpenCode' }), 'Waiting for OpenCode')
  assert.equal(feed.waitReason({ state: 'running' }), 'Job starting')
  assert.equal(feed.waitReason({ state: 'running', stage: 'Starting the research…' }), 'Starting the research…')
  assert.equal(feed.waitReason({ state: 'failed', message: 'NoHarness: no CLI on PATH' }), 'NoHarness: no CLI on PATH')
  assert.equal(feed.waitReason({ feed: [{ kind: 'search', text: 'query: dualsense drift' }] }), 'Searching the web')
  assert.equal(feed.waitReason({ state: 'cancelled' }), 'Stopped')
  assert.equal(feed.waitReason({}), 'Starting')
})

test('a job with no feed or log still shows the steps and pages it reported', () => {
  const steps = feed.workLines({ steps: [{ id: 's1', source: 'web_search', label: 'dualsense drift', state: 'running', rows: 0, ms: 0 }] })
  assert.deepEqual(steps.map((line) => line.text), ['dualsense drift'])
  const pages = feed.workLines({ activity: [
    { id: 'a1', kind: 'search', query: 'dualsense drift' },
    { id: 'a2', kind: 'read', title: 'DualSense drift report', url: 'https://reddit.com/r/PS5/x' },
  ] })
  assert.deepEqual(pages.map((line) => line.text), ['dualsense drift', 'https://reddit.com/r/PS5/x'])
  assert.equal(pages[1].host, 'reddit.com')
})

test('one job keeps at most its newest lines, even when the poll returns a long feed', () => {
  const many = Array.from({ length: 100 }, (_, index) => ({ kind: 'note', text: `line ${index}` }))
  const lines = feed.workLines({ feed: many })
  assert.equal(lines.length, feed.WORK_LINES_KEPT)
  assert.equal(lines.at(-1).text, 'line 99')
  assert.equal(feed.WORK_LINES_VISIBLE, 6, 'the panel draws six lines at once')
})

test('the terminal shows the reason, the real lines, and no invented progress', () => {
  const html = render({
    state: 'queued',
    title: 'PS5 gamepad',
    feed: [
      { kind: 'search', text: 'searched the web for ps5 gamepad drift' },
      { kind: 'source', text: 'fetched https://classaction.example/dualsense' },
    ],
  })
  assert.match(html, /PS5 gamepad: research activity/)
  assert.match(html, /role="status"/)
  assert.match(html, /Reading classaction\.example/)
  assert.match(html, /searched the web for ps5 gamepad drift/)
  assert.doesNotMatch(html, /\d+%/, 'the terminal never draws a percentage the engine did not report')
  assert.equal((html.match(/class="wt-line[ "]/g) ?? []).length, 2)
})

test('a job with no feed draws its real stage once, not a fake transcript', () => {
  const html = render({ state: 'queued' })
  assert.match(html, /Waiting for a research slot/)
  assert.equal((html.match(/class="wt-line[ "]/g) ?? []).length, 1)
  assert.match(html, /aria-hidden="true"/)
})

import test from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

/** The Ask screen's own rules: what the procurement strip says, which sources a
 *  answer footnotes, and where the sprites may stand. The strip and the footnotes
 *  are pure functions, so they are run as written; the placement is read from the
 *  stylesheet, as the other layout budgets are. */

const read = async (path) => (await readFile(new URL(`../${path}`, import.meta.url), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '')

let strip
let directory
test.before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'kriko-ask-'))
  const source = await readFile(new URL('../src/chat/strip.ts', import.meta.url), 'utf8')
  const built = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  await writeFile(join(directory, 'strip.mjs'), built)
  strip = await import(pathToFileURL(join(directory, 'strip.mjs')))
})
test.after(async () => rm(directory, { recursive: true, force: true }))

/** A procurement summary with only the counts a test sets. */
const summary = (over = {}) => ({
  estimates: 1, lines: 3, quotedLines: 2, unpricedLines: 0, uncomparable: 0, gross: {},
  expiring: [], expired: [], atRisk: [], ...over,
})

test('the strip draws nothing for a quiet estimate, and nothing outside the live engine', () => {
  assert.deepEqual(strip.stripRows(summary()), [])
  assert.equal(strip.showStrip(summary(), true), false)
  const busy = summary({ unpricedLines: 2 })
  assert.equal(strip.showStrip(busy, false), false, 'the demo engine has no estimates to show')
  assert.equal(strip.showStrip(summary({ lines: 0 }), true), false)
  assert.equal(strip.showStrip(busy, true), true)
})

test('an expired quote and one that is expiring are said in one row, with the verb agreeing', () => {
  const rows = strip.stripRows(summary({ expiring: [{}], expired: [{}] }))
  assert.equal(rows.length, 1)
  assert.equal(rows[0].id, 'expiry')
  assert.equal(rows[0].text, '1 quote expires within 14 days, and 1 has already expired')
  assert.equal(rows[0].tone, 'risk', 'an expired quote is a risk, not a warning')

  const soon = strip.stripRows(summary({ expiring: [{}, {}] }))
  assert.equal(soon[0].text, '2 quotes expire within 14 days')
  assert.equal(soon[0].tone, 'warn')

  const gone = strip.stripRows(summary({ expired: [{}, {}] }))
  assert.equal(gone[0].text, '2 quotes have expired')
})

test('risk is red when any line is red, amber otherwise, and unpriced lines get their own row', () => {
  const rows = strip.stripRows(summary({ atRisk: [{ risk: 'amber' }, { risk: 'red' }], unpricedLines: 1 }))
  assert.deepEqual(rows.map((row) => row.id), ['risk', 'unpriced'])
  assert.equal(rows[0].text, '2 lines at red or amber risk')
  assert.equal(rows[0].tone, 'risk')
  assert.equal(rows[1].text, '1 line has no price')

  const amber = strip.stripRows(summary({ atRisk: [{ risk: 'amber' }] }))
  assert.equal(amber[0].tone, 'warn')
})

test('an answer footnotes the sources it cites, once each, in the order it read them', () => {
  const page = (url, cited) => ({ url, host: new URL(url).host, title: url, read: 'read', cited })
  const notes = strip.footnotesOf([
    page('https://a.example.test/1', true),
    page('https://b.example.test/2', false),
    page('https://a.example.test/1', true),
    page('https://c.example.test/3', true),
  ])
  assert.deepEqual(notes.map((item) => item.url), ['https://a.example.test/1', 'https://c.example.test/3'])
  assert.deepEqual(strip.footnotesOf(undefined), [])
})

test('the sprites stand only on a window 1280px or wider, and never leave the gutters', async () => {
  const css = await read('src/styles/chat.css')
  // Hidden by default, drawn only at 1280px and up, sized from the gutter beside the 760px column.
  const base = /\.shelf \{([^}]*)\}/.exec(css)
  assert.ok(base, 'no base rule for the shelf')
  assert.match(base[1], /display:\s*none/, 'the shelf is drawn on a narrow window')
  const wide = /@media \(min-width: 1280px\) \{\s*\.shelf \{([^}]*)\}/.exec(css)
  assert.ok(wide, 'the shelf has no 1280px rule')
  assert.match(wide[1], /display:\s*block/)
  assert.match(wide[1], /--u:\s*clamp\(24px,\s*calc\(\(\(100vw - 992px\) \/ 2 - 16px\) \/ 3\.6\),\s*64px\)/)
  // The sprites sit behind the content and take no press.
  assert.match(css, /\.shelf-wrap \{[^}]*z-index:\s*0;[^}]*pointer-events:\s*none;/)
})

test('the landing is a narrow screen, and the thread has no index eyebrow to draw', async () => {
  const home = await read('src/screens/Chat.tsx')
  assert.match(home, /className=\{thread \? 'chat-col' : 'chat-col k-screen'\}/)
  assert.match(home, /data-width=\{thread \? undefined : 'narrow'\}/)
  assert.ok(!home.includes('01 / check'), 'the landing still numbers itself')
  assert.ok(!home.includes('02'), 'the recent checks still carry an index')
  assert.match(home, /detail: \{ screen: 'estimate' \}/, 'the strip does not open the Procurement screen')
})

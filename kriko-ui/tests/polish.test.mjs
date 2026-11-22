import test from 'node:test'
import assert from 'node:assert/strict'
import ts from 'typescript'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

/** The desktop's polish rules, and the defects the screenshots showed.
 *
 *  These are behaviour of the interface, not taste: a row whose picture is
 *  missing, a line whose actions stack, a sentence in italics. Each check is
 *  tied to the element that failed on a real screen.
 */

const read = async (path) => (await readFile(new URL(`../${path}`, import.meta.url), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '')

let glyphs
test.before(async () => {
  const directory = await mkdtemp(join(tmpdir(), 'kriko-glyph-'))
  const source = await readFile(new URL('../src/ui/productGlyphs.ts', import.meta.url), 'utf8')
  const built = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  await writeFile(join(directory, 'glyphs.mjs'), built)
  glyphs = await import(pathToFileURL(join(directory, 'glyphs.mjs')))
  test.after(async () => rm(directory, { recursive: true, force: true }))
})

test('a product name leads to one sprite, and a name outside the library gets none', () => {
  assert.equal(glyphs.glyphFor('E-bike T \u00b7 2023'), 'px-ebike')
  assert.equal(glyphs.glyphFor('City bike'), 'px-ebike')
  assert.equal(glyphs.glyphFor('Bisiklet 28"'), 'px-ebike')
  assert.equal(glyphs.glyphFor('Bosch dishwasher'), 'px-dishwasher')
  assert.equal(glyphs.glyphFor('Kettle X200'), 'px-kettle')
  assert.equal(glyphs.glyphFor('Service contract'), null)
})

test('the pixel symbols are defined once at the shell, not only on the home shelf', async () => {
  const app = await read('src/App.tsx')
  assert.ok(app.includes('<PixelSprites />'), 'no screen outside the home has the sprite symbols')
  const home = await read('src/screens/Chat.tsx')
  assert.match(home, /<ProductGlyph name=\{item\.name\}/, 'a recent row has no product picture')
  const compare = await read('src/screens/Compare.tsx')
  assert.match(compare, /<ProductGlyph name=\{check\.name\}/, 'a comparison column has no product picture')
  const queue = await read('src/ui/QueueCard.tsx')
  assert.match(queue, /<ProductGlyph name=\{item\.name\}/, 'a queue row has no product picture')
})

test('a line\'s three actions sit on one row, not stacked by the block icon button', async () => {
  const css = await read('src/styles/estimate.css')
  const rules = [...css.matchAll(/\.estimate-line-actions[^{]*\{([^}]*)\}/g)].map((hit) => hit[1])
  assert.ok(rules.length, 'no rule for the line actions')
  assert.ok(rules.some((body) => /display:\s*flex/.test(body) && /justify-content:\s*flex-end/.test(body)),
    'the line actions are still block-level and stack')
})

test('a recent row draws its picture in the shared icon tile, so every name starts at one x', async () => {
  const home = await read('src/screens/Chat.tsx')
  // A recent check is a list row: the picture (or the letter when no sprite fits) is the icon tile,
  // and the name, the note and the risk count are the row's own parts.
  assert.match(home, /<button type="button" className="k-row recent"/, 'a recent check is not a list row')
  assert.match(home, /<span className="k-row-icon" aria-hidden="true">\s*\{glyphFor\(item\.name\) \? <ProductGlyph name=\{item\.name\}/, 'a recent row has no icon tile for its picture')
  assert.match(home, /<span className="k-row-value">/, 'a recent row has no value for its risks and time')
})

test('the desktop writes its own words upright: no italic phrase in a screen', async () => {
  for (const file of ['src/screens/Prices.tsx', 'src/screens/Estimate.tsx', 'src/screens/Compare.tsx', 'src/screens/Queue.tsx']) {
    const source = await read(file)
    assert.ok(!/<em>/.test(source), `${file} italicises a sentence`)
  }
})

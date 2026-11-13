import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

/**
 * The two faces the window reads in.
 *
 * Inter sets the body one step heavier than before, Chivo Mono sets every
 * title, and the accessibility font in Settings overrides both. The weights
 * live in tokens so a rule names a step, never a number.
 */

const read = async (path) => (await readFile(new URL(`../${path}`, import.meta.url), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '')

const css = await read('src/styles/base.css')
const tokens = await read('src/styles/tokens.css')
const identity = await read('src/styles/identity.css')

function rule(source, selector) {
  const at = source.indexOf(`\n${selector} {`)
  assert.ok(at > -1, `no rule for ${selector}`)
  const open = source.indexOf('{', at)
  return source.slice(open + 1, source.indexOf('}', open))
}

function declaration(source, selector, property) {
  const found = new RegExp(`(?:^|[;{\\s])${property}:\\s*([^;]+);`).exec(rule(source, selector))
  assert.ok(found, `${selector} does not set ${property}`)
  return found[1].trim()
}

test('the body reads in Inter, one step heavier than regular', () => {
  assert.match(tokens, /--font:\s*'Inter Variable'/)
  assert.equal(declaration(css, 'body', 'font-family'), 'var(--font)')
  assert.equal(declaration(css, 'body', 'font-weight'), 'var(--w-regular)')
  assert.match(tokens, /--w-regular:\s*500;/)
  assert.match(tokens, /--w-medium:\s*600;/)
  assert.match(tokens, /--w-semibold:\s*700;/)
})

test('titles read in Chivo Mono, with Inter behind it', () => {
  assert.match(tokens, /--display:\s*'Chivo Mono Variable',\s*'Inter Variable',\s*ui-monospace,\s*monospace;/)
  assert.equal(declaration(css, 'h1,\nh2,\nh3', 'font-family'), 'var(--display)')
  for (const selector of ['.hello h1', '.page-head h1']) {
    assert.equal(declaration(identity, selector, 'font-weight'), 'var(--w-bold)', `${selector} is not the heaviest step`)
  }
})

test('the accessibility font overrides the body and the display face', () => {
  const block = rule(css, ":root[data-font='atkinson']")
  assert.match(block, /--font:\s*'Atkinson Hyperlegible'/)
  assert.match(block, /--display:\s*var\(--set-font\)/)
})

test('code keeps the mono face, which is not the display face', () => {
  assert.match(tokens, /--mono:\s*'Geist Mono Variable'/)
  assert.equal(declaration(css, '.mono', 'font-family'), 'var(--mono)')
})

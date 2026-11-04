import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

/**
 * The reader: "left of the settings panel isn't blurred like the rest."
 *
 * The scrim (the dim and the blur behind a drawer) was given `left: offset + 20`,
 * the drawer's own left edge, so the strip beside the sheet kept a sharp, undimmed
 * picture while the rest of the window was blurred. A pixel check needs a browser,
 * which the gate does not run, so this holds the cause: the scrim covers every edge
 * of the window and the drawer never narrows it.
 */

const css = (await readFile(new URL('../src/styles/shell.css', import.meta.url), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '')
const drawer = await readFile(new URL('../src/ui/Drawer.tsx', import.meta.url), 'utf8')

test('the scrim covers the whole window, and the blur reaches every edge it covers', () => {
  const rule = /\n\.scrim \{([^}]*)\}/.exec(css)
  assert.ok(rule, 'no .scrim rule')
  const body = rule[1]
  assert.match(body, /position:\s*fixed/)
  const covers = /inset:\s*0\s*;/.test(body) || ['top', 'right', 'bottom', 'left'].every((edge) => new RegExp(`${edge}:\\s*0\\s*;`).test(body))
  assert.ok(covers, 'the scrim leaves an edge of the window uncovered')
  assert.match(body, /backdrop-filter:\s*blur\(/)
  assert.match(body, /-webkit-backdrop-filter:\s*blur\(/, 'a WebKit window needs the prefixed blur')
})

test('the drawer does not narrow the scrim to its own edge', () => {
  const tag = /<motion\.div className="scrim"[^>]*>/.exec(drawer)
  assert.ok(tag, 'no scrim element in the drawer')
  assert.doesNotMatch(tag[0], /style=/, 'the scrim takes a style, so something can start it away from the window edge')
})

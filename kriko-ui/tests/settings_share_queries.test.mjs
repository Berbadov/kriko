import test from 'node:test'
import assert from 'node:assert/strict'
import { renderToStaticMarkup } from 'react-dom/server'
import { domOf, h, loadSource, mount, screenStubs } from './settings_support.mjs'

/**
 * "Share my product queries" is one switch in Keys and models, under shared access,
 * off unless the reader turned it on. The words are the feature: a note that stopped
 * saying what is sent, or a switch that came up on, would be a different promise
 * from the one the reader agreed to.
 */

const PARTS = 'src/ui/settings/parts.tsx'

function sharing(chosen) {
  return loadSource(PARTS, screenStubs({ doc: { chosen }, save: async () => {} }))
}

test('the product query switch says what is sent, and starts off', async () => {
  const { SharedAccessGroup } = sharing({})
  const page = domOf(renderToStaticMarkup(h(SharedAccessGroup)))
  const toggle = page.querySelector('[role="switch"][aria-label="Share my product queries"]')
  assert.ok(toggle, 'the sharing section offers the switch')
  assert.equal(toggle.getAttribute('aria-checked'), 'false', 'it starts off')
  assert.equal(toggle.textContent.trim(), 'Off')
  const text = page.body.textContent
  assert.match(text, /the product model you looked up/)
  assert.match(text, /It never sends the listing link, the page title, the time/)
  assert.match(text, /Off by default/)
})

test('a switch already turned on reads as on', async () => {
  const { SharedAccessGroup } = sharing({ share_queries: '1' })
  const toggle = domOf(renderToStaticMarkup(h(SharedAccessGroup))).querySelector('[role="switch"][aria-label="Share my product queries"]')
  assert.equal(toggle.getAttribute('aria-checked'), 'true')
  assert.equal(toggle.textContent.trim(), 'On')
})

test('turning the switch on saves the preference the engine reads', async () => {
  const saves = []
  const { SharedAccessGroup } = loadSource(PARTS, screenStubs({ doc: { chosen: {} }, save: async (patch) => saves.push(patch) }))
  const view = await mount(h(SharedAccessGroup))
  try {
    const toggle = () => view.document.querySelector('[role="switch"][aria-label="Share my product queries"]')
    await view.click(toggle())
    assert.deepEqual(saves, [{ share_queries: '1' }])
  } finally {
    await view.unmount()
  }
})

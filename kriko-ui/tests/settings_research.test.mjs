import test from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import { h, loadSource, mount, unnamedButtons } from './settings_support.mjs'

/**
 * The Research section of Settings: six captioned sections in a fixed order, a
 * plain sentence under every setting, a labelled control on every row, the
 * source kinds as checkable rows with one always on, and every save written to
 * the key the engine has always read. The agent section is tested on its own in
 * agents_surface.test.mjs; here it is a stand-in, so this file reads only what
 * Research draws.
 */

const RESEARCH = 'src/ui/settings/Research.tsx'
const CAPTIONS = ['Agent', 'How much effort', 'Where to look', 'Language and market', 'Findings', 'Classification']

function doc(overrides = {}) {
  return {
    chosen: {
      run_concurrency: '2',
      local_output_language: '',
      local_search_language: 'en',
      market_region: 'auto',
      classification_provider: 'agent',
      chat_product_only: '0',
    },
    effective: { ready: true, reason: '', harness: 'claude-code', harness_ready: true, harness_note: '' },
    harnesses: [],
    unusable: [],
    missing: [],
    source_kinds: [
      { id: 'forums', label: 'Forums' },
      { id: 'reviews', label: 'Reviews' },
      { id: 'news', label: 'News' },
    ],
    research: { sources: 0, kinds: ['forums', 'reviews'], thoroughness: 50, validation_sensitivity: 50 },
    search_providers: [],
    classification_providers: [
      { id: 'agent', label: 'Selected agent', ready: true },
      { id: 'typesafe', label: 'Jev (TypeSafe)', ready: false },
    ],
    market_regions: [
      { id: 'auto', label: 'Automatic' },
      { id: 'GB', label: 'United Kingdom' },
    ],
    ...overrides,
  }
}

/** Research compiled over a stand-in for the agent section, a fixed prefs
 *  document, and a spy for every save. */
function research({ prefs = doc(), problem = '' } = {}) {
  const saves = []
  const { Research } = loadSource(RESEARCH, {
    '../../engine/settings': {
      usePrefsDoc: () => ({ doc: prefs, problem, busy: false, save: async (patch) => saves.push(patch), reload: async () => {} }),
    },
    '../panels/Agents': {
      AgentsSection: () => h('section', { className: 'k-group settings-section' }, h('h3', { className: 'k-caption' }, 'Agent'), h('p', null, 'the agent section')),
    },
    '../../engine/buyer': {
      useBuyerProfile: () => ({ profile: { about: '' }, live: true, saved: false, problem: '', save: async () => {} }),
    },
    '../Icon': { Icon: () => null },
  })
  return { element: h(Research), saves }
}

const captions = (view) => [...view.document.querySelectorAll('h3.k-caption')].map((node) => node.textContent)

/** The row a setting's label names, found by its label text. */
const rowNamed = (view, label) => [...view.document.querySelectorAll('[data-setting]')].find((row) => row.querySelector('[data-setting-label]')?.textContent === label)

/** Set a native select or input the way a reader does, then announce it. */
async function choose(view, node, value) {
  const proto = node.tagName === 'SELECT' ? view.document.defaultView.HTMLSelectElement.prototype : view.document.defaultView.HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
  await React.act(async () => {
    setter.call(node, value)
    node.dispatchEvent(new view.document.defaultView.Event(node.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
  })
}

test('the section has six captions, in the order the reader meets them', async () => {
  const element = research().element
  const view = await mount(element)
  try {
    assert.deepEqual(captions(view), CAPTIONS)
  } finally {
    await view.unmount()
  }
})

test('every setting has a label, one plain sentence, and a named control', async () => {
  const view = await mount(research().element)
  try {
    const rows = [...view.document.querySelectorAll('[data-setting]')]
    assert.ok(rows.length >= 12, `expected every setting to be drawn, found ${rows.length}`)
    for (const row of rows) {
      const label = row.querySelector('[data-setting-label]')?.textContent.trim()
      assert.ok(label, 'a setting has no label')
      const note = row.querySelector('.k-row-note')?.textContent.trim() ?? ''
      assert.ok(note.length > 20, `"${label}" has no sentence under it`)
      assert.ok(note.endsWith('.'), `"${label}" note is not a sentence`)
    }
    assert.deepEqual(unnamedButtons(view.document), [], 'a control has no name')
    for (const field of view.document.querySelectorAll('select, input, textarea')) {
      assert.ok(field.getAttribute('aria-label'), `a ${field.tagName.toLowerCase()} has no name`)
    }
    assert.ok(!view.document.body.textContent.includes('—'), 'an em dash is in the copy')
  } finally {
    await view.unmount()
  }
})

test('the source kinds are checkable rows, and the tour finds them in their section', async () => {
  const view = await mount(research().element)
  try {
    const where = view.document.querySelector('[data-tour="source-kinds"]')
    assert.ok(where, 'the tour target is drawn')
    assert.match(where.querySelector('h3').textContent, /Where to look/)
    const kinds = [...where.querySelectorAll('[data-setting]')].map((row) => row.querySelector('[data-setting-label]').textContent)
    assert.deepEqual(kinds, ['Forums', 'Reviews', 'News'])
    assert.equal(where.querySelector('[role="switch"][aria-label="Forums"]').getAttribute('aria-checked'), 'true')
    assert.equal(where.querySelector('[role="switch"][aria-label="News"]').getAttribute('aria-checked'), 'false')
  } finally {
    await view.unmount()
  }
})

test('the last source kind that is on cannot be turned off', async () => {
  const view = await mount(research({ prefs: doc({ research: { sources: 0, kinds: ['forums'], thoroughness: 50, validation_sensitivity: 50 } }) }).element)
  try {
    const forums = view.document.querySelector('[role="switch"][aria-label="Forums"]')
    assert.equal(forums.disabled, true, 'the only kind on is disabled')
    const reviews = view.document.querySelector('[role="switch"][aria-label="Reviews"]')
    assert.equal(reviews.disabled, false, 'a kind that is off can be turned on')
  } finally {
    await view.unmount()
  }
})

test('turning a source kind off saves the rest of the list', async () => {
  const { element, saves } = research()
  const view = await mount(element)
  try {
    await view.click(view.document.querySelector('[role="switch"][aria-label="Reviews"]'))
    assert.deepEqual(saves, [{ research_source_kinds: 'forums' }])
    await view.click(view.document.querySelector('[role="switch"][aria-label="News"]'))
    assert.deepEqual(saves.at(-1), { research_source_kinds: 'forums,reviews,news' })
  } finally {
    await view.unmount()
  }
})

test('effort saves the keys the engine reads, under the same names as before', async () => {
  const { element, saves } = research()
  const view = await mount(element)
  try {
    await view.click([...rowNamed(view, 'Products at once').querySelectorAll('[role="radio"]')].find((node) => node.textContent === '3'))
    assert.deepEqual(saves.at(-1), { run_concurrency: '3' })

    await choose(view, rowNamed(view, 'Thoroughness').querySelector('input[type="range"]'), '75')
    await React.act(async () => {
      rowNamed(view, 'Thoroughness').querySelector('input[type="range"]').dispatchEvent(new view.document.defaultView.KeyboardEvent('keyup', { bubbles: true }))
    })
    assert.deepEqual(saves.at(-1), { kriko_agent_thoroughness: '75' })

    await choose(view, rowNamed(view, 'Extra sources').querySelector('select'), '10')
    assert.deepEqual(saves.at(-1), { research_sources: '10' })
  } finally {
    await view.unmount()
  }
})

test('language, market and classification each save their own key', async () => {
  const { element, saves } = research()
  const view = await mount(element)
  try {
    await choose(view, view.document.querySelector('select[aria-label="Response language"]'), 'de')
    assert.deepEqual(saves.at(-1), { local_output_language: 'de' })
    await choose(view, view.document.querySelector('select[aria-label="Research language"]'), 'fr')
    assert.deepEqual(saves.at(-1), { local_search_language: 'fr' })
    await choose(view, view.document.querySelector('select[aria-label="Market region"]'), 'GB')
    assert.deepEqual(saves.at(-1), { market_region: 'GB' })
    await choose(view, view.document.querySelector('select[aria-label="Product classification"]'), 'typesafe')
    assert.deepEqual(saves.at(-1), { classification_provider: 'typesafe' })
    const classify = view.document.querySelector('select[aria-label="Product classification"]')
    assert.ok([...classify.options].some((option) => option.textContent === 'Jev (TypeSafe) (no key)'), 'a provider with no key says so')
  } finally {
    await view.unmount()
  }
})

test('chat findings sit here as switches: product-only answers saves its key', async () => {
  const { element, saves } = research()
  const view = await mount(element)
  try {
    const findings = [...view.document.querySelectorAll('section')].find((node) => node.querySelector('h3')?.textContent === 'Findings')
    assert.ok(findings.querySelector('textarea[aria-label="What Chat should remember about you"]'), 'chat memory is drawn under Findings')
    await view.click(findings.querySelector('[role="switch"][aria-label="Product-only answers"]'))
    assert.deepEqual(saves.at(-1), { chat_product_only: '1' })
  } finally {
    await view.unmount()
  }
})

test('the endpoint and the model name are not drawn here: they belong to Keys and models', async () => {
  const view = await mount(research().element)
  try {
    assert.equal(view.document.querySelector('input[aria-label="OpenAI-compatible endpoint"]'), null)
    assert.equal(view.document.querySelector('input[aria-label="Completion model"]'), null)
    assert.ok(!view.document.body.textContent.includes('Endpoint'))
  } finally {
    await view.unmount()
  }
})

test('a problem the save reported is drawn on the screen', async () => {
  const view = await mount(research({ problem: 'The engine did not save that.' }).element)
  try {
    assert.match(view.document.querySelector('.error-note').textContent, /did not save that/)
  } finally {
    await view.unmount()
  }
})

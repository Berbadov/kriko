import test from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { domOf, h, loadSource, mount, screenStubs, unnamedButtons } from './settings_support.mjs'

/**
 * The Settings screen: seven sections in a fixed order, a list on the left that says
 * which one is open, a search that finds a setting in any section, and no
 * explanation hidden in a tooltip. Behaviour is what is asserted here, not the
 * styling of any row.
 */

const SCREEN = 'src/screens/Settings.tsx'
const PAGES = 'src/ui/panels/settingsPages.ts'

const IDS = ['general', 'research', 'keys', 'local', 'connections', 'usage', 'data']
const LABELS = ['General', 'Research', 'Keys and models', 'Local AI', 'Connections', 'Usage and spend', 'Data and updates']

function screen(options, initial) {
  // Research's agent section and Chat's findings reach the engine through their own
  // hooks; the screen test only needs them to draw, so they are stood in for here.
  const { SettingsScreen } = loadSource(SCREEN, {
    ...screenStubs(options),
    '../panels/Agents': { AgentsSection: () => React.createElement('section', { className: 'k-group settings-section' }, React.createElement('h3', { className: 'k-caption' }, 'Agent')) },
    '../../engine/buyer': { useBuyerProfile: () => ({ profile: { about: '' }, live: false, saved: false, problem: '', save() {} }) },
  })
  return h(SettingsScreen, { initial })
}

test('the screen has seven sections, with the ids the shell and the tour use', async () => {
  const pages = loadSource(PAGES)
  assert.deepEqual(pages.SETTINGS_PAGES.map((page) => page.value), IDS)
  assert.deepEqual(pages.SETTINGS_PAGES.map((page) => page.label), LABELS)
  assert.equal(pages.isSettingsPage('usage'), true)
  assert.equal(pages.isSettingsPage('look'), false, 'the retired ids are no longer sections')
  assert.equal(pages.isSettingsPage('about'), false)
})

test('the list names every section and marks the one that is open', async () => {
  const document = domOf(renderToStaticMarkup(screen({}, 'usage')))
  const nav = document.querySelector('nav[aria-label="Settings sections"]')
  assert.ok(nav, 'the sections are a named navigation')
  const items = [...nav.querySelectorAll('button')]
  assert.deepEqual(items.map((item) => item.textContent), LABELS)
  assert.deepEqual(items.filter((item) => item.getAttribute('aria-current') === 'true').map((item) => item.textContent), ['Usage and spend'])
  assert.equal(document.querySelector('.settings-pane-title').textContent, 'Usage and spend')
  // The narrow screen gets the same list as a select, so nothing is lost below 900px.
  const jump = document.querySelector('select[aria-label="Settings section"]')
  assert.deepEqual([...jump.options].map((option) => option.textContent), LABELS)
  assert.equal(jump.value, 'usage')
})

test('with nothing asked for, the screen opens on General', async () => {
  const document = domOf(renderToStaticMarkup(screen({}, undefined)))
  assert.equal(document.querySelector('.settings-pane-title').textContent, 'General')
  const headings = [...document.querySelectorAll('h3.k-caption')].map((node) => node.textContent)
  assert.deepEqual(headings, ['Appearance', 'Findings', 'Help and chat'])
})

test('every section draws with every control named, and nothing waits behind a tooltip', async () => {
  for (const id of IDS) {
    const document = domOf(renderToStaticMarkup(screen({ spent: { days: 7, runs: 3, tokens: 12000, usd: 1.5, unpriced_runs: 1 }, demo: true }, id)))
    assert.deepEqual(unnamedButtons(document), [], `${id} has a control with no name`)
    assert.equal(document.querySelector('[role="tooltip"]'), null, `${id} hides a fact in a tooltip`)
    for (const row of document.querySelectorAll('[data-setting]')) {
      assert.ok(row.querySelector('[data-setting-label]')?.textContent.trim(), `${id} has a setting with no label`)
    }
  }
})

test('the facts the old tooltips held are drawn as words on their page', async () => {
  const usage = domOf(renderToStaticMarkup(screen({ spent: { days: 7, runs: 3, tokens: 12000, usd: 1.5, unpriced_runs: 1 }, demo: true }, 'usage'))).body.textContent
  assert.match(usage, /A cap only warns\. Nothing is blocked\./)
  assert.match(usage, /Example numbers/)
  assert.match(usage, /Partial: 1 run has no price/)
  const keys = domOf(renderToStaticMarkup(screen({}, 'keys'))).body.textContent
  assert.match(keys, /Keys stay on this computer\. The engine never sends one back\./)
  assert.match(keys, /works in this app only/)
  const data = domOf(renderToStaticMarkup(screen({}, 'data'))).body.textContent
  assert.match(data, /Version and updates/)
  assert.match(data, /Only the product model you looked up/)
})

test('a section is drawn as its own page, one at a time', async () => {
  const document = domOf(renderToStaticMarkup(screen({}, 'connections')))
  const headings = [...document.querySelectorAll('h3')].map((node) => node.textContent)
  assert.deepEqual(headings, ['Browser extension and set-up', 'Web search', 'Proxies', 'Chat clients'])
  const research = domOf(renderToStaticMarkup(screen({}, 'research')))
  assert.deepEqual([...research.querySelectorAll('h3.k-caption')].map((node) => node.textContent), ['Agent', 'How much effort', 'Where to look', 'Language and market', 'Findings', 'Classification'])
  assert.ok(research.querySelector('[data-tour="source-kinds"]'), 'the tour target is drawn on Research')
})

test('a section the tour asks for is the one drawn, and the list follows it', async () => {
  const { SettingsScreen } = loadSource(SCREEN, screenStubs({}))
  const { showSettingsPage } = loadSource(PAGES)
  const view = await mount(h(SettingsScreen, {}))
  try {
    // The tour asks for a section while the screen is open, and it moves at once.
    await React.act(async () => showSettingsPage('usage'))
    await view.flush()
    assert.equal(view.document.querySelector('.settings-pane-title').textContent, 'Usage and spend')
    assert.equal(view.document.querySelector('nav button[aria-current="true"]').textContent, 'Usage and spend')
  } finally {
    await view.unmount()
  }
})

test('the list moves the screen to the section it names', async () => {
  const view = await mount(screen({}, 'general'))
  try {
    const find = (text) => [...view.document.querySelectorAll('nav button')].find((node) => node.textContent === text)
    await view.click(find('Connections'))
    assert.equal(view.document.querySelector('.settings-pane-title').textContent, 'Connections')
    assert.equal(find('Connections').getAttribute('aria-current'), 'true')
    assert.equal(find('General').getAttribute('aria-current'), null)
  } finally {
    await view.unmount()
  }
})

test('search finds a setting by its name or its note across every section', async () => {
  const view = await mount(screen({}, 'general'))
  try {
    const box = view.document.querySelector('input[aria-label="Search settings"]')
    assert.ok(box, 'the search field is named')

    // A name in another section: Thoroughness lives on Research.
    await view.type(box, 'thorough')
    let groups = [...view.document.querySelectorAll('.settings-results h2.k-caption')].map((node) => node.textContent)
    assert.deepEqual(groups, ['Research'])
    assert.match(view.document.querySelector('.settings-results').textContent, /Thoroughness/)
    assert.equal(view.document.querySelector('.settings-pane-title'), null, 'the open section gives way to the results')

    // A word from a note matches too, and groups by section.
    await view.type(box, 'a cap only warns')
    groups = [...view.document.querySelectorAll('.settings-results h2.k-caption')].map((node) => node.textContent)
    assert.deepEqual(groups, ['Usage and spend'])
    assert.equal(view.document.querySelectorAll('.settings-results .k-row').length, 2, 'each cap is a match')

    // A word in a name of General finds it there.
    await view.type(box, 'theme')
    groups = [...view.document.querySelectorAll('.settings-results h2.k-caption')].map((node) => node.textContent)
    assert.deepEqual(groups, ['General'])

    // Nothing matches: the screen says so, and offers no row.
    await view.type(box, 'zzqx')
    assert.match(view.document.querySelector('.k-empty').textContent, /No setting matches/)
    assert.equal(view.document.querySelectorAll('.settings-results .k-row').length, 0)

    // Clearing the search brings the open section back.
    await view.type(box, '')
    assert.equal(view.document.querySelector('.settings-pane-title').textContent, 'General')
  } finally {
    await view.unmount()
  }
})

test('a search result opens its section', async () => {
  const view = await mount(screen({}, 'general'))
  try {
    const box = view.document.querySelector('input[aria-label="Search settings"]')
    await view.type(box, 'thorough')
    const result = [...view.document.querySelectorAll('.settings-results .k-row')][0]
    await view.click(result)
    assert.equal(view.document.querySelector('.settings-pane-title').textContent, 'Research')
    assert.equal(view.document.querySelector('input[aria-label="Search settings"]').value, '')
  } finally {
    await view.unmount()
  }
})

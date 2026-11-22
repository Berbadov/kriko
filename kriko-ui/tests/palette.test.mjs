import test from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import { h, loadSource, mount } from './settings_support.mjs'

/**
 * The command palette: what it can reach, how a query finds it, and what running
 * an item does. The pure builder and scorer are compiled for real; the component
 * is mounted in jsdom with its two data hooks stood in for, so the test can see
 * when they run.
 */

const ITEMS = loadSource('src/ui/paletteItems.ts')
const DRAWER = loadSource('src/ui/drawerEvents.ts')
const { act } = React

const RECENT = Array.from({ length: 12 }, (_, k) => ({ id: `lookup-${k}`, name: k === 0 ? 'Kettle 2000' : `Check ${k}`, category: 'Kitchen' }))
const ESTIMATES = [{ estimate_id: 'e1', name: 'Office fleet' }]
const DATA = { recent: RECENT, estimates: ESTIMATES }

const titles = (matches) => matches.map((match) => match.item.title)

function spies() {
  const calls = []
  const seams = {
    navigate: (screen) => calls.push(['navigate', screen]),
    showDrawer: (panel) => calls.push(['showDrawer', panel]),
    showSettingsPage: (page) => calls.push(['showSettingsPage', page]),
    action: (id) => calls.push(['action', id]),
    openProduct: (lookupId) => calls.push(['openProduct', lookupId]),
    openEstimate: (estimateId) => calls.push(['openEstimate', estimateId]),
  }
  return { seams, calls }
}

function runItem(title) {
  const { seams, calls } = spies()
  const item = ITEMS.buildItems(DATA).find((one) => one.title === title)
  assert.ok(item, `there is an item called ${title}`)
  item.run(seams)
  return calls
}

test('a title prefix ranks above a keyword prefix, which ranks above scattered letters', () => {
  const items = [
    { id: 'scattered', group: 'Go to', title: 'Prices', keywords: [] },
    { id: 'keyword', group: 'Go to', title: 'Compare', keywords: ['rice cooker'] },
  ]
  assert.deepEqual(titles(ITEMS.filterItems(items, 'rice')), ['Compare', 'Prices'])

  const prefix = [
    { id: 'keyword', group: 'Go to', title: 'Compare', keywords: ['price'] },
    { id: 'title', group: 'Go to', title: 'Procurement', keywords: [] },
  ]
  assert.deepEqual(titles(ITEMS.filterItems(prefix, 'pr')), ['Procurement', 'Compare'])
})

test('scattered letters match inside one word only, so "pri" does not find "help" and "guide"', () => {
  const items = [
    { id: 'tour', group: 'Actions', title: 'Take the tour', keywords: ['help', 'walkthrough', 'guide'] },
    { id: 'prices', group: 'Go to', title: 'Prices', keywords: [] },
    { id: 'stored', group: 'Settings', title: 'Settings: General', keywords: ['provider'] },
  ]
  assert.deepEqual(titles(ITEMS.filterItems(items, 'pri')), ['Prices', 'Settings: General'], 'provider holds p-r-i inside one word, the tour does not')
})

test('every query word has to match, and a word that matches nowhere drops the item', () => {
  const items = [{ id: 'a', group: 'Go to', title: 'Queue', keywords: ['jobs'] }]
  assert.deepEqual(titles(ITEMS.filterItems(items, 'queue jobs')), ['Queue'])
  assert.deepEqual(titles(ITEMS.filterItems(items, 'queue wine')), [])
})

test('diacritics fold, so "urun" finds "Ürün" and the match is marked on the letter', () => {
  const items = [{ id: 'a', group: 'Recent checks', title: 'Ürün checks', keywords: [] }]
  const [match] = ITEMS.filterItems(items, 'urun')
  assert.ok(match, 'the folded query finds the title')
  assert.deepEqual(match.marks, [0, 1, 2, 3], 'the four letters of the match are marked, the accent included')
  assert.equal(ITEMS.filterItems(items, 'ÜRÜN')[0]?.item.title, 'Ürün checks', 'case folds too')
})

test('equal matches keep the group order, then the order given', () => {
  const items = [
    { id: 'est', group: 'Estimates', title: 'Quote one', keywords: [] },
    { id: 'go', group: 'Go to', title: 'Quote board', keywords: [] },
  ]
  assert.deepEqual(titles(ITEMS.filterItems(items, 'quote')), ['Quote board', 'Quote one'])
})

test('an empty query keeps every item, Go to and Actions first', () => {
  const groups = [...new Set(ITEMS.filterItems(ITEMS.buildItems(DATA), '').map((match) => match.item.group))]
  assert.deepEqual(groups, ['Go to', 'Actions', 'Settings', 'Recent checks', 'Estimates'])
})

test('every item has a unique id and a name a screen reader can say', () => {
  const items = ITEMS.buildItems(DATA)
  assert.equal(new Set(items.map((item) => item.id)).size, items.length)
  for (const item of items) assert.ok(item.title.trim().length > 0, `${item.id} has a title`)
})

test('the places, the Settings sections and the actions are all there', () => {
  const all = ITEMS.buildItems(DATA).map((item) => item.title)
  for (const place of ['Ask', 'Compare', 'Queue', 'History', 'Procurement', 'Prices', 'Catalogs', 'Sites', 'For you', 'Settings']) {
    assert.ok(all.includes(place), `${place} is a place`)
  }
  for (const section of ['General', 'Research', 'Keys and models', 'Connections', 'Usage and spend', 'Data and updates']) {
    assert.ok(all.includes(`Settings: ${section}`), `Settings: ${section} is a section`)
  }
  for (const action of ['New chat', 'Take the tour', 'Check a list of products', 'New estimate']) {
    assert.ok(all.includes(action), `${action} is an action`)
  }
})

test('the keyboard hints are Ctrl+1 to Ctrl+4 for the places in order, and Ctrl+, for Settings', () => {
  const hint = (title) => ITEMS.buildItems(DATA).find((item) => item.title === title)?.hint
  assert.deepEqual(['Ask', 'Compare', 'Prices', 'Procurement', 'Settings'].map(hint), ['Ctrl+1', 'Ctrl+2', 'Ctrl+3', 'Ctrl+4', 'Ctrl+,'])
  assert.equal(hint('Queue'), undefined, 'a place with no shortcut shows none')
})

test('recent checks are capped at eight, and each opens its product', () => {
  const checks = ITEMS.buildItems(DATA).filter((item) => item.group === 'Recent checks')
  assert.equal(checks.length, 8)
  assert.deepEqual(runItem('Kettle 2000'), [['openProduct', 'lookup-0']])
})

test('each place goes through the seam that reaches it', () => {
  assert.deepEqual(runItem('Ask'), [['navigate', 'chat']])
  assert.deepEqual(runItem('Prices'), [['navigate', 'prices']])
  assert.deepEqual(runItem('History'), [['showDrawer', 'history']])
  assert.deepEqual(runItem('Catalogs'), [['showDrawer', 'browse']])
  assert.deepEqual(runItem('Settings'), [['showDrawer', 'settings']])
  assert.equal(DRAWER.routeFor('browse').screen, 'catalogs', 'the panel the palette names lands on the screen it is listed under')
})

test('a Settings section sets its page, then opens Settings', () => {
  assert.deepEqual(runItem('Settings: Research'), [
    ['showSettingsPage', 'research'],
    ['navigate', 'settings'],
  ])
})

test('the four actions go to the shell as palette actions', () => {
  assert.deepEqual(runItem('New chat'), [['action', 'new-chat']])
  assert.deepEqual(runItem('Take the tour'), [['action', 'take-tour']])
  assert.deepEqual(runItem('Check a list of products'), [['action', 'check-a-list']])
  assert.deepEqual(runItem('New estimate'), [['action', 'new-estimate']])
})

test('a saved estimate opens on the Procurement screen with its id', () => {
  assert.deepEqual(runItem('Office fleet'), [
    ['navigate', 'estimate'],
    ['openEstimate', 'e1'],
  ])
})

/* ---- The component, mounted in jsdom ----------------------------------- */

function loadPalette(counter, estimates = ESTIMATES) {
  return loadSource('src/ui/CommandPalette.tsx', {
    '../engine/history': {
      useHistory: () => {
        counter.history += 1
        return { items: RECENT }
      },
    },
    '../engine/estimates': {
      useEstimates: () => {
        counter.estimates += 1
        return { items: estimates }
      },
    },
  })
}

function keyOn(target, init) {
  const win = target.ownerDocument ? target.ownerDocument.defaultView : target
  return act(async () => {
    target.dispatchEvent(new win.KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init }))
  })
}

test('the palette draws nothing and reads no data until it is opened', async () => {
  const counter = { history: 0, estimates: 0 }
  const Palette = loadPalette(counter)
  const view = await mount(h(Palette.CommandPalette))
  try {
    assert.equal(view.document.querySelector('[role="dialog"]'), null)
    assert.equal(counter.history + counter.estimates, 0, 'no hook ran at startup')

    await act(async () => ITEMS.openCommandPalette())
    assert.ok(view.document.querySelector('[role="dialog"]'), 'the button event opens it')
    assert.ok(counter.history > 0 && counter.estimates > 0, 'the data hooks run once it is open')
  } finally {
    await view.unmount()
  }
})

test('Ctrl+Shift+P opens it, and the input is a combobox over a listbox', async () => {
  const Palette = loadPalette({ history: 0, estimates: 0 })
  const view = await mount(h(Palette.CommandPalette))
  try {
    await keyOn(view.document.defaultView, { key: 'P', ctrlKey: true, shiftKey: true })
    const dialog = view.document.querySelector('[role="dialog"]')
    assert.equal(dialog?.getAttribute('aria-modal'), 'true')
    assert.ok(dialog.getAttribute('aria-label'), 'the dialog has a label')
    const input = view.document.querySelector('input[role="combobox"]')
    assert.equal(view.document.activeElement, input, 'the input takes focus')
    assert.equal(input.getAttribute('aria-controls'), view.document.querySelector('[role="listbox"]').id)
    assert.equal(input.getAttribute('aria-expanded'), 'true')
  } finally {
    await view.unmount()
  }
})

test('arrows move the highlight and Enter runs the item under it', async () => {
  const Palette = loadPalette({ history: 0, estimates: 0 })
  const view = await mount(h(Palette.CommandPalette))
  const win = view.document.defaultView
  const navigated = []
  const record = (event) => navigated.push(event.detail)
  win.addEventListener('kriko:navigate', record)
  try {
    await act(async () => ITEMS.openCommandPalette())
    const input = view.document.querySelector('input[role="combobox"]')
    await keyOn(input, { key: 'ArrowDown' })
    await keyOn(input, { key: 'ArrowDown' })
    const selected = view.document.querySelector('[role="option"][aria-selected="true"]')
    assert.equal(selected.getAttribute('aria-label'), 'Queue', 'two arrows down from Ask is Queue')
    assert.equal(input.getAttribute('aria-activedescendant'), selected.id)

    await keyOn(input, { key: 'Enter' })
    assert.deepEqual(navigated, [{ screen: 'queue' }], 'Enter ran Queue')
    assert.equal(view.document.querySelector('[role="dialog"]'), null, 'running an item closes the palette')
  } finally {
    win.removeEventListener('kriko:navigate', record)
    await view.unmount()
  }
})

test('Escape closes the palette and puts focus back where it was', async () => {
  const Palette = loadPalette({ history: 0, estimates: 0 })
  const view = await mount(h(Palette.CommandPalette))
  try {
    const button = view.document.createElement('button')
    button.textContent = 'Open the list'
    view.document.body.append(button)
    await act(async () => button.focus())

    await act(async () => ITEMS.openCommandPalette())
    const input = view.document.querySelector('input[role="combobox"]')
    assert.equal(view.document.activeElement, input)

    await keyOn(input, { key: 'Escape' })
    assert.equal(view.document.querySelector('[role="dialog"]'), null)
    assert.equal(view.document.activeElement, button, 'focus returned to the button')
  } finally {
    await view.unmount()
  }
})

test('typing filters the list, and every option has a name', async () => {
  const Palette = loadPalette({ history: 0, estimates: 0 })
  const view = await mount(h(Palette.CommandPalette))
  try {
    await act(async () => ITEMS.openCommandPalette())
    const input = view.document.querySelector('input[role="combobox"]')
    const setter = Object.getOwnPropertyDescriptor(view.document.defaultView.HTMLInputElement.prototype, 'value').set
    await act(async () => {
      setter.call(input, 'kettle')
      input.dispatchEvent(new view.document.defaultView.Event('input', { bubbles: true }))
    })
    const options = [...view.document.querySelectorAll('[role="option"]')]
    assert.equal(options[0].getAttribute('aria-label'), 'Kettle 2000', 'the check is first')
    for (const option of options) {
      assert.ok(option.getAttribute('aria-label')?.trim(), 'an option with no name is a control a screen reader cannot say')
    }
  } finally {
    await view.unmount()
  }
})

test('the list draws at most fifty rows', async () => {
  const many = Array.from({ length: 80 }, (_, k) => ({ estimate_id: `e${k}`, name: `Estimate ${k}` }))
  const Palette = loadPalette({ history: 0, estimates: 0 }, many)
  const view = await mount(h(Palette.CommandPalette))
  try {
    await act(async () => ITEMS.openCommandPalette())
    assert.equal(view.document.querySelectorAll('[role="option"]').length, 50)
  } finally {
    await view.unmount()
  }
})

import test from 'node:test'
import assert from 'node:assert/strict'
import { renderToStaticMarkup } from 'react-dom/server'
import { domOf, h, loadSource, mount, unnamedButtons } from './settings_support.mjs'

/**
 * A setting is an icon, a label, one sentence under it, a value and one control.
 * Nothing is explained in a tooltip, and every control carries a word. These tests
 * draw the primitives and the three panels that still use the old names, and
 * check that the facts they used to hide are on the screen as words.
 */

const PARTS = 'src/ui/panels/settingsParts.tsx'
/** Every row is a label and a note, with no tooltip anywhere, and every press is named. */
function assertWordsNotTooltips(document, what) {
  assert.equal(document.querySelector('[role="tooltip"]'), null, `${what} hides a fact in a tooltip`)
  assert.deepEqual(unnamedButtons(document), [], `${what} has a control with no name`)
}

test('a setting draws its label, its note as visible words, its value and its state', async () => {
  const parts = loadSource(PARTS)
  const document = domOf(
    renderToStaticMarkup(
      h(parts.Setting, {
        icon: 'swap',
        label: 'Use proxies',
        note: 'Pages are read through the address you give.',
        value: 'Off',
        state: h(parts.State, { tone: 'warn' }, 'Needs an address'),
        control: h('button', { type: 'button' }, 'Turn on'),
      }),
    ),
  )
  const row = document.querySelector('[data-setting]')
  assert.ok(row, 'the setting is a row')
  assert.equal(row.querySelector('[data-setting-label]').textContent, 'Use proxies')
  assert.equal(row.querySelector('.k-row-note').textContent, 'Pages are read through the address you give.')
  assert.match(row.querySelector('.k-row-value').textContent, /Off/)
  assert.equal(row.querySelector('.k-pill').textContent, 'Needs an address')
  assert.equal(row.querySelector('.k-pill').getAttribute('data-tone'), 'warn')
  assertWordsNotTooltips(document, 'a setting')
})

test('a setting with no note draws no empty line under its label', async () => {
  const parts = loadSource(PARTS)
  const document = domOf(renderToStaticMarkup(h(parts.Setting, { label: 'Share', control: h('button', { type: 'button', 'aria-label': 'Share' }) })))
  assert.equal(document.querySelector('.k-row-note'), null)
})

test('a toggle says on or off in words, and is a named switch', async () => {
  const parts = loadSource(PARTS)
  const on = domOf(renderToStaticMarkup(h(parts.Toggle, { on: true, label: 'Reduce motion', onChange() {} }))).querySelector('[role="switch"]')
  assert.equal(on.getAttribute('aria-checked'), 'true')
  assert.equal(on.getAttribute('aria-label'), 'Reduce motion')
  assert.equal(on.textContent, 'On')
  const off = domOf(renderToStaticMarkup(h(parts.Toggle, { on: false, label: 'Reduce motion', onChange() {} }))).querySelector('[role="switch"]')
  assert.equal(off.getAttribute('aria-checked'), 'false')
  assert.equal(off.textContent, 'Off')
})

test('a choice is a radio group of words, with the chosen one marked', async () => {
  const parts = loadSource(PARTS)
  const document = domOf(
    renderToStaticMarkup(
      h(parts.Choice, {
        label: 'Motion',
        value: 'standard',
        options: [
          { value: 'calm', label: 'Calm' },
          { value: 'standard', label: 'Standard' },
          { value: 'vivid', label: 'Vivid' },
        ],
        onChange() {},
      }),
    ),
  )
  const group = document.querySelector('[role="radiogroup"]')
  assert.equal(group.getAttribute('aria-label'), 'Motion')
  const radios = [...group.querySelectorAll('[role="radio"]')]
  assert.deepEqual(radios.map((radio) => radio.textContent), ['Calm', 'Standard', 'Vivid'])
  assert.deepEqual(radios.map((radio) => radio.getAttribute('aria-checked')), ['false', 'true', 'false'])
  assertWordsNotTooltips(document, 'a choice')
})

test('the theme picker offers five palettes by name, each drawn in its own colours', async () => {
  const parts = loadSource(PARTS)
  const options = [
    { value: 'system', label: 'System' },
    { value: 'dark', label: 'Dark' },
    { value: 'gray', label: 'Gray' },
    { value: 'paper', label: 'Paper' },
    { value: 'white', label: 'White' },
  ]
  const document = domOf(renderToStaticMarkup(h(parts.ThemePicker, { label: 'Theme', value: 'paper', options, onChange() {} })))
  const swatches = [...document.querySelectorAll('button.settings-theme')]
  assert.deepEqual(swatches.map((button) => button.textContent), ['System', 'Dark', 'Gray', 'Paper', 'White'])
  assert.deepEqual(swatches.map((button) => button.getAttribute('aria-pressed')), ['false', 'false', 'false', 'true', 'false'])
  // The swatch carries the palette's own ground, so a reader can see what each one is.
  assert.match(swatches[1].querySelector('.settings-swatch').getAttribute('style'), /--sw-ground:#08090d/)
  assert.match(swatches[3].querySelector('.settings-swatch').getAttribute('style'), /--sw-ground:#f4f0e6/)
  assertWordsNotTooltips(document, 'the theme picker')
})

test('a section is a caption over a card, and its note is drawn under the card', async () => {
  const parts = loadSource(PARTS)
  const document = domOf(
    renderToStaticMarkup(
      h(parts.Section, { title: 'Appearance', note: 'System follows this computer.' }, h(parts.Setting, { label: 'Theme', control: h('span', null, 'x') })),
    ),
  )
  assert.equal(document.querySelector('h3.k-caption').textContent, 'Appearance')
  assert.ok(document.querySelector('.k-card.k-list [data-setting]'), 'the rows sit in the card')
  assert.equal(document.querySelector('.settings-note').textContent, 'System follows this computer.')
})

test('the old names still draw, with their facts as words and their presses named', async () => {
  const parts = loadSource(PARTS)
  const document = domOf(
    renderToStaticMarkup(
      h(
        parts.Group,
        { icon: 'key', title: 'Keys', hint: h(parts.Hint, { icon: 'shield', title: 'Keys stay here' }, 'Keys stay on this computer.') },
        h(parts.Row, { icon: 'lock', label: 'Login', state: h(parts.State, { tone: 'ok' }, 'In Keys') }, h(parts.IconButton, { icon: 'retry', label: 'Check the proxies' })),
        h(parts.Row, { actions: true }, h(parts.IconButton, { icon: 'play', label: 'Run' })),
      ),
    ),
  )
  assert.equal(document.querySelector('h3.k-caption').textContent, 'Keys')
  assert.equal(document.querySelector('.settings-note').textContent, 'Keys stay on this computer.')
  assert.match(document.body.textContent, /In Keys/)
  assert.equal(document.querySelector('button[aria-label="Check the proxies"]').textContent, 'Check the proxies')
  assertWordsNotTooltips(document, 'the old names')
})

test('a switch says on or off in words, so no toggle is a bare switch', async () => {
  const controls = loadSource('src/ui/controls.tsx')
  const on = domOf(renderToStaticMarkup(h(controls.Switch, { on: true, label: 'Differences only', onChange() {} }))).querySelector('[role="switch"]')
  assert.equal(on.getAttribute('aria-checked'), 'true')
  assert.equal(on.getAttribute('aria-label'), 'Differences only')
  assert.equal(on.querySelector('.switch-word').textContent, 'On')
  const off = domOf(renderToStaticMarkup(h(controls.Switch, { on: false, label: 'Differences only', onChange() {} }))).querySelector('[role="switch"]')
  assert.equal(off.querySelector('.switch-word').textContent, 'Off')
})

test('the set-up checklist is four steps, each with a state in words and one word press', async () => {
  const panel = loadSource('src/ui/panels/Setup.tsx', {
    '../../engine/api': { get: async () => [], post: async () => ({}) },
    '../../engine/jobs': { followJob: async () => null },
    '../../engine/Engine': { useEngine: () => ({ mode: 'demo' }) },
    '../ExternalLink': { ExternalLink: ({ children, className }) => h('a', { className }, children) },
    '../drawerEvents': { showDrawer() {} },
  })
  const document = domOf(renderToStaticMarkup(h(panel.SetupGroup)))
  assertWordsNotTooltips(document, 'the set-up checklist')
  const rows = [...document.querySelectorAll('[data-setting]')].map((row) => row.querySelector('[data-setting-label]').textContent)
  assert.deepEqual(rows, ['Choose who does the research', 'Add product knowledge', 'Connect your browser', 'Run a first sourced check'])
  // Nothing is verified in a demo, so every step reads To do, in words, not by colour.
  assert.equal([...document.querySelectorAll('[data-setting] .k-pill')].filter((pill) => pill.textContent === 'To do').length, 4)
  assert.match(document.querySelector('.k-group').textContent, /0 of 4 done/)
  // The access code and the checkout install are folded away, not drawn open.
  const folds = [...document.querySelectorAll('details.settings-fold')]
  assert.deepEqual(folds.map((fold) => fold.querySelector('summary').textContent), ['Have an access code from a friend?', 'Installing from a checkout instead'])
  assert.ok(folds.every((fold) => !fold.open))
})

test('web search draws the first provider, the order and each provider as a row with its state in words', async () => {
  const doc = {
    primary: 'a',
    fallback: [],
    automatic: true,
    effective: ['a'],
    providers: [
      { id: 'a', label: 'Alpha', needs_key: false, key_saved: null, ready: true, note: 'Runs on this computer. No key.', health: { calls: 4, recent: 4, last_success: Math.round(Date.now() / 1000) - 60, last_failure: null, last_problem: '', miss_rate: 0 } },
      { id: 'b', label: 'Beta', needs_key: true, key_saved: false, ready: false, note: 'Hosted. Needs a key. Receives only the words searched.', health: { calls: 0, recent: 0, last_success: null, last_failure: null, last_problem: '', miss_rate: null } },
    ],
  }
  const panel = loadSource('src/ui/panels/SearchProviders.tsx', {
    '../../engine/websearch': {
      useSearchProviders: () => ({ doc, problem: '', tested: {}, save() {}, test() {}, reload() {} }),
      providerState: (row, effective) => {
        if (row.needs_key && !row.key_saved) return { text: 'Needs a key', tone: 'warn' }
        if (row.ready && effective.includes(row.id)) return { text: 'Ready', tone: 'ok' }
        return { text: 'Off', tone: 'none' }
      },
    },
  })
  const document = domOf(renderToStaticMarkup(h(panel.SearchProvidersGroup)))
  assertWordsNotTooltips(document, 'web search')
  const text = document.body.textContent
  assert.match(text, /First provider/)
  assert.match(text, /Automatic/)
  assert.match(text, /Ready/)
  assert.match(text, /Needs a key/)
  // The section says in one sentence that hosted providers get the words, and each row says what it is.
  assert.match(text, /A hosted provider receives the words you search\./)
  assert.match(text, /Runs on this computer\. No key\./)
  assert.match(text, /Hosted\. Needs a key\. Receives only the words searched\./)
  assert.ok(document.querySelector('button[aria-label="Test Alpha"]'), 'the test press is named')
  assert.ok([...document.querySelectorAll('button')].some((button) => button.textContent === 'Add a key'), 'a missing key is one word away')
  assert.equal(document.querySelector('.live-dot'), null, 'the live dot is retired: the pill says Ready')
})

test('a provider in the order can be moved, and one not in it can be added', async () => {
  const saves = []
  const row = (id, label) => ({ id, label, needs_key: false, key_saved: null, ready: true, note: `${label} runs here.`, health: { calls: 0, recent: 0, last_success: null, last_failure: null, last_problem: '', miss_rate: null } })
  const doc = {
    primary: 'a',
    fallback: ['b', 'c'],
    automatic: false,
    effective: ['a', 'b', 'c'],
    providers: [row('a', 'Alpha'), row('b', 'Beta'), row('c', 'Gamma'), row('d', 'Delta')],
  }
  const panel = loadSource('src/ui/panels/SearchProviders.tsx', {
    '../../engine/websearch': {
      useSearchProviders: () => ({ doc, problem: '', tested: {}, save: async (patch) => saves.push(patch), test() {}, reload() {} }),
      providerState: () => ({ text: 'Ready', tone: 'ok' }),
    },
  })
  const view = await mount(h(panel.SearchProvidersGroup))
  try {
    const press = (label) => view.document.querySelector(`button[aria-label="${label}"]`)
    // The first in the order has nothing earlier to move to.
    assert.equal(press('Move Beta earlier').disabled, true)
    await view.click(press('Move Gamma earlier'))
    assert.deepEqual(saves.at(-1), { search_fallback: 'c,b' })
    // Delta is in no order: adding it appends it to the end.
    const add = [...view.document.querySelectorAll('button')].filter((button) => button.textContent === 'Add to the order')
    assert.equal(add.length, 1)
    await view.click(add[0])
    assert.deepEqual(saves.at(-1), { search_fallback: 'b,c,d' })
  } finally {
    await view.unmount()
  }
})

test('proxies say who sees the pages in words, list each address with its state, and fold the rest away', async () => {
  const doc = { enabled: true, pool: ['http://a.example:8080', 'http://b.example:8080'], login_saved: false, active: false, learned: null, limits: { tries: 3, retire_seconds: 300, block_memory_seconds: 1800 } }
  const checked = [{ address: 'http://a.example:8080', ok: true, ms: 420, error: '' }]
  const panel = loadSource('src/ui/panels/Proxies.tsx', {
    '../../engine/proxies': {
      useProxies: () => ({ doc, problem: '', checked, save() {}, check() {}, reload() {} }),
      addressState: (address, list) => {
        const row = Array.isArray(list) ? list.find((one) => one.address === address) : undefined
        if (!row) return { text: 'Not checked', tone: 'none' }
        return row.ok ? { text: 'Ready', tone: 'ok' } : { text: 'No answer', tone: 'risk' }
      },
    },
  })
  const document = domOf(renderToStaticMarkup(h(panel.ProxiesGroup)))
  assertWordsNotTooltips(document, 'proxies')
  const text = document.body.textContent
  assert.match(text, /A proxy sees which pages you read, and a site's terms may forbid it\./)
  assert.match(text, /Off by default\./)
  // The list: one row per address, its state in a word.
  const rows = [...document.querySelectorAll('[data-setting]')].map((row) => row.querySelector('[data-setting-label]').textContent)
  assert.ok(rows.includes('http://a.example:8080') && rows.includes('http://b.example:8080'))
  assert.match(text, /Ready/)
  assert.match(text, /Not checked/)
  assert.ok(document.querySelector('button[aria-label="Remove http://b.example:8080"]'), 'each address can be removed by name')
  // The address form has a visible label, so the field is named by words.
  const field = document.querySelector('input[type="text"]')
  assert.match(document.querySelector(`label[for="${field.id}"]`).textContent, /Proxy address/)
  // The long explanation is in a closed fold, not under a row.
  const fold = [...document.querySelectorAll('details.settings-fold')].find((node) => /robots\.txt/.test(node.textContent))
  assert.ok(fold && !fold.open)
})

test('turned on with no address is a state in words, and a new address is added to the list', async () => {
  const saves = []
  const doc = { enabled: true, pool: [], login_saved: false, active: false, learned: null, limits: { tries: 3, retire_seconds: 300, block_memory_seconds: 1800 } }
  const panel = loadSource('src/ui/panels/Proxies.tsx', {
    '../../engine/proxies': { useProxies: () => ({ doc, problem: '', checked: null, save: async (patch) => saves.push(patch), check() {}, reload() {} }), addressState: () => ({ text: 'Not checked', tone: 'none' }) },
  })
  const view = await mount(h(panel.ProxiesGroup))
  try {
    assert.match(view.document.body.textContent, /Needs an address/)
    const field = view.document.querySelector('input[type="text"]')
    await view.type(field, 'http://c.example:8080')
    await view.click(view.document.querySelector('button[type="submit"]'))
    assert.deepEqual(saves.at(-1), { proxy_pool: 'http://c.example:8080' })
  } finally {
    await view.unmount()
  }
})

test('chat clients: one row per app with its state in words, and the word that connects it', async () => {
  const doc = {
    server_name: 'kriko',
    store: '/store',
    command: 'kriko',
    frozen: false,
    url: '',
    clients: [
      { id: 'generic', label: 'Any client', note: 'Add this to the client\'s MCP servers.', snippet: '{}', path: '', writable: false, state: 'shown' },
      { id: 'desktop', label: 'Desktop chat app', note: 'Restart the app after writing.', snippet: '{}', path: '/home/me/mcp.json', writable: true, state: 'absent' },
      { id: 'ide', label: 'IDE chat', note: 'Restart the chat panel after writing.', snippet: '{}', path: '/home/me/ide.json', writable: true, state: 'connected' },
    ],
  }
  const panel = loadSource('src/ui/panels/McpClients.tsx', {
    '../../engine/mcpclients': {
      useMcpClients: () => ({ doc, problem: '', writing: '', write() {} }),
      clientState: (state) => ({ shown: { text: 'By hand', tone: 'none' }, absent: { text: 'Not connected', tone: 'none' }, connected: { text: 'Connected', tone: 'ok' } })[state],
    },
    '../clipboard': { copyText: async () => true },
  })
  const document = domOf(renderToStaticMarkup(h(panel.McpClientsGroup)))
  assertWordsNotTooltips(document, 'chat clients')
  const text = document.body.textContent
  assert.match(text, /Not connected/)
  assert.match(text, /Connected/)
  assert.match(text, /By hand/)
  assert.match(text, /Lookups are free\. A chat answer uses your agent\./)
  // What each app's note says is drawn under its row, in words, not folded away.
  assert.match(text, /Restart the app after writing\./)
  const connect = [...document.querySelectorAll('button')].filter((button) => button.textContent === 'Connect')
  assert.equal(connect.length, 1, 'only the app that is not yet connected offers Connect')
  const connected = [...document.querySelectorAll('button')].find((button) => button.textContent === 'Connected')
  assert.equal(connected.disabled, true)
})

test('connect writes the chosen app and reads the list again', async () => {
  const writes = []
  const doc = {
    server_name: 'kriko',
    store: '/store',
    command: 'kriko',
    frozen: false,
    url: '',
    clients: [{ id: 'desktop', label: 'Desktop chat app', note: 'Restart the app after writing.', snippet: '{}', path: '/home/me/mcp.json', writable: true, state: 'absent' }],
  }
  const panel = loadSource('src/ui/panels/McpClients.tsx', {
    '../../engine/mcpclients': {
      useMcpClients: () => ({ doc, problem: '', writing: '', write: async (id) => writes.push(id) }),
      clientState: () => ({ text: 'Not connected', tone: 'none' }),
    },
    '../clipboard': { copyText: async () => true },
  })
  const view = await mount(h(panel.McpClientsGroup))
  try {
    const connect = [...view.document.querySelectorAll('button')].find((button) => button.textContent === 'Connect')
    await view.click(connect)
    assert.deepEqual(writes, ['desktop'])
  } finally {
    await view.unmount()
  }
})

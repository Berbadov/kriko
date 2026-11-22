import test from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { domOf, h, loadSource, mount, prefsDoc, screenStubs, unnamedButtons } from './settings_support.mjs'

const prefsDocWith = (chosen) => ({ ...prefsDoc, chosen })

/**
 * Keys and models. A key that came from the environment cannot be removed here, a
 * saved one can, and no stored value is ever shown. Sharing says in words what the
 * password can do and how much trial is left. The model fields save when the reader
 * leaves them. The local model has its own section, and one row here points to it.
 */

const PARTS = 'src/ui/settings/parts.tsx'
const KEYS = 'src/ui/settings/Keys.tsx'

/** The settings hooks the parts read, with a test's own keys, sharing or saves. */
function withSettings(options, overrides) {
  return { ...screenStubs(options), '../../engine/settings': { ...screenStubs(options)['../../engine/settings'], ...overrides } }
}

/** The row of a setting, by its label: the one place a reader finds it. */
function settingRow(document, label) {
  return [...document.querySelectorAll('[data-setting]')].find((row) => row.querySelector('[data-setting-label]')?.textContent === label)
}
const valueOf = (document, label) => settingRow(document, label)?.querySelector('.k-row-value')?.textContent.trim()

test('environment keys identify their source and only saved file keys offer removal', async () => {
  const providers = ['environment', 'file'].map((source) => ({ id: source, label: source, source, present: true, hint: '…1234', purpose: 'Research' }))
  const parts = loadSource(PARTS, withSettings({ providers }, { useKeys: () => ({ doc: { providers }, problem: '', tested: {}, set() {}, remove() {}, test() {} }) }))
  const document = domOf(renderToStaticMarkup(h(parts.KeysGroup)))
  assert.equal(valueOf(document, 'environment'), 'Set')
  assert.match(settingRow(document, 'environment').textContent, /environment/, 'the note says where the key comes from')
  assert.equal(document.querySelector('button[aria-label="Remove environment key"]'), null, 'an environment key cannot be removed here')
  assert.equal(document.querySelector('button[aria-label="Remove file key"]').textContent, 'Remove', 'a saved key can be removed')
  assert.ok(document.querySelector('button[aria-label="Test file key"]'), 'a set key can be tested')
  // Every press says its word, and the word is what a reader sees.
  assert.deepEqual(unnamedButtons(document), [])
  assert.match(document.body.textContent, /Keys stay on this computer\. The engine never sends one back\./)
})

test('a key that is not set offers to save one, and nothing to remove', async () => {
  const providers = [{ id: 'mercury', label: 'Mercury', source: '', present: false, hint: '', purpose: 'Research' }]
  const parts = loadSource(PARTS, withSettings({ providers }, { useKeys: () => ({ doc: { providers }, problem: '', tested: {}, set() {}, remove() {}, test() {} }) }))
  const document = domOf(renderToStaticMarkup(h(parts.KeysGroup)))
  assert.equal(valueOf(document, 'Mercury'), 'Not set')
  assert.equal(document.querySelector('button[aria-label="Save Mercury key"]').disabled, true, 'nothing to save until a key is typed')
  assert.equal(document.querySelector('button[aria-label="Remove Mercury key"]'), null)
  assert.equal(document.querySelector('button[aria-label="Test Mercury key"]'), null)
  assert.ok(document.querySelector('input[aria-label="Mercury key"]'), 'a field takes the key')
  assert.deepEqual(unnamedButtons(document), [])
})

test('a typed key is saved to its provider, and show and hide change only the view', async () => {
  const saved = []
  const providers = [{ id: 'deepseek', label: 'DeepSeek', source: '', present: false, hint: '', purpose: 'Searches' }]
  const parts = loadSource(PARTS, withSettings({ providers, setKey: async (id, value) => saved.push([id, value]) }, {}))
  const view = await mount(h(parts.KeysGroup))
  try {
    const field = view.document.querySelector('input[aria-label="DeepSeek key"]')
    assert.equal(field.type, 'password', 'a key is typed hidden')
    await view.type(field, ' sk-test ')
    await view.click(view.document.querySelector('button[aria-label="Show DeepSeek key"]'))
    assert.equal(field.type, 'text', 'Show reveals what is typed')
    await view.click(view.document.querySelector('button[aria-label="Hide DeepSeek key"]'))
    assert.equal(field.type, 'password')
    await view.click(view.document.querySelector('button[aria-label="Save DeepSeek key"]'))
    assert.deepEqual(saved, [['deepseek', ' sk-test ']])
  } finally {
    await view.unmount()
  }
})

test('a saved key can be tested and removed by its own id', async () => {
  const calls = []
  const providers = [{ id: 'tavily', label: 'Tavily', source: 'file', present: true, hint: 'a1b2', purpose: 'Search words' }]
  const parts = loadSource(PARTS, withSettings({ providers, testKey: (id) => calls.push(['test', id]), removeKey: (id) => calls.push(['remove', id]) }, {}))
  const view = await mount(h(parts.KeysGroup))
  try {
    await view.click(view.document.querySelector('button[aria-label="Test Tavily key"]'))
    await view.click(view.document.querySelector('button[aria-label="Remove Tavily key"]'))
    assert.deepEqual(calls, [
      ['test', 'tavily'],
      ['remove', 'tavily'],
    ])
  } finally {
    await view.unmount()
  }
})

test('shared access says what the password can do, and how much trial is left', async () => {
  const status = (over) => ({
    bound: true,
    device: 'dpapi',
    grant: { present: false, label: '', providers: [], state: '' },
    trial: { limit: 10, used: 3, left: 7, available: true },
    providers: ['mercury', 'deepseek'],
    ...over,
  })
  const render = (doc) => {
    const parts = loadSource(PARTS, withSettings({}, { useSharedAccess: () => ({ doc, code: '', unlock() {}, forget() {}, make() {} }) }))
    return domOf(renderToStaticMarkup(h(parts.SharedAccessGroup)))
  }

  const asking = render(status({}))
  // The promise made to a friend, and the one they rely on: this is the sentence that has to stay true.
  assert.match(asking.body.textContent, /works in this app only/)
  assert.equal(valueOf(asking, 'Access'), 'On, free trial')
  assert.equal(valueOf(asking, 'Free trial'), '7 of 10 left')
  // The two steps are named in words, and the access code says what goes in it.
  assert.ok(settingRow(asking, 'Paste the access code'))
  assert.ok(settingRow(asking, 'Paste the password'))
  assert.equal(asking.querySelector('textarea[aria-label="Access code"]').getAttribute('placeholder'), 'Paste the code')
  assert.match(settingRow(asking, 'Paste the password').textContent, /separate message from the code, on purpose/)
  assert.match(asking.body.textContent, /Share your keys/)
  // The password's scope is words under the group, not a padlock to press.
  assert.equal(asking.querySelector('[role="tooltip"]'), null)
  assert.deepEqual(unnamedButtons(asking), [])
  // The friend's page owns up to the risk in one line: who can spend the keys.
  assert.match(asking.body.textContent, /Anyone with both can spend your keys/)

  const holding = render(status({ grant: { present: true, label: 'Ada', providers: ['mercury', 'deepseek'], state: 'shared' } }))
  assert.equal(valueOf(holding, 'Access'), "On, Ada's keys")
  assert.match(holding.body.textContent, /Windows account/)
  assert.match(holding.body.textContent, /Use keys/)
  assert.match(holding.body.textContent, /Forget/)
  // The trial is not what is in use, so its count is not drawn.
  assert.equal(settingRow(holding, 'Free trial'), undefined)

  const spent = render(status({ trial: { limit: 10, used: 10, left: 0, available: false } }))
  assert.equal(valueOf(spent, 'Free trial'), 'Used up, 10 of 10')
  // A used-up trial says what to do next, since the reader is now stuck.
  assert.match(spent.body.textContent, /Paste an access code or add your own keys/)

  // A build with a pepper but no trial bundle: the screen must not invent a count.
  const none = render(status({ trial: { limit: 10, used: 0, left: 10, available: false } }))
  assert.equal(valueOf(none, 'Access'), 'Off, your own keys')
  assert.equal(valueOf(none, 'Free trial'), 'Not in this build')
  assert.doesNotMatch(none.body.textContent, /\d left/)
})

test('a build with no share pepper says so in words, where the code would fail', async () => {
  const parts = loadSource(
    PARTS,
    withSettings(
      {},
      {
        useSharedAccess: () => ({
          doc: { bound: false, device: '', grant: { present: false, label: '', providers: [], state: '' }, trial: { limit: 10, used: 0, left: 10, available: false }, providers: [] },
          code: '',
          unlock() {},
          forget() {},
          make() {},
        }),
      },
    ),
  )
  const text = domOf(renderToStaticMarkup(h(parts.SharedAccessGroup))).body.textContent
  assert.match(text, /This build has no share pepper, so a code made elsewhere will not open here\./)
})

test('the endpoint and the model name save when the reader leaves the field, trimmed', async () => {
  const saves = []
  const parts = loadSource(PARTS, withSettings({ save: async (patch) => saves.push(patch) }, {}))
  const view = await mount(h(parts.ModelGroup))
  const blur = async (node) =>
    React.act(async () => {
      node.dispatchEvent(new view.document.defaultView.FocusEvent('focusout', { bubbles: true }))
      await new Promise((resolveTurn) => setTimeout(resolveTurn, 10))
    })
  try {
    const endpoint = view.document.querySelector('input[aria-label="OpenAI-compatible endpoint"]')
    await view.type(endpoint, 'https://api.example.com/v1/')
    await blur(endpoint)
    assert.deepEqual(saves, [{ llm_base_url: 'https://api.example.com/v1' }], 'a trailing slash is not kept')

    const model = view.document.querySelector('input[aria-label="Completion model"]')
    await view.type(model, '  gpt-test  ')
    await blur(model)
    assert.deepEqual(saves[1], { llm_model: 'gpt-test' })
    assert.match(view.document.body.textContent, /The model the endpoint should answer with\./)
  } finally {
    await view.unmount()
  }
})

test('Keys and models holds one local row that points to Local AI, and asks the computer nothing', async () => {
  const opened = []
  const stubs = withSettings({ doc: { ...prefsDocWith({ local_model: 'gemma4:e2b' }) } }, {})
  stubs['../panels/settingsPages'] = { showSettingsPage: (page) => opened.push(page) }
  stubs['../../engine/local'] = {
    useLocal() {
      throw new Error('Keys and models must not read the local machine')
    },
  }
  const { Keys } = loadSource(KEYS, stubs)
  const view = await mount(h(Keys))
  try {
    assert.equal(valueOf(view.document, 'Local model'), 'gemma4:e2b')
    const press = [...view.document.querySelectorAll('button')].find((node) => node.textContent === 'Open Local AI')
    await view.click(press)
    assert.deepEqual(opened, ['local'])
    assert.equal(view.document.querySelector('input[aria-label="Model name"]'), null, 'no download controls live here any more')
  } finally {
    await view.unmount()
  }
})

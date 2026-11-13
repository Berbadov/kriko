import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import ts from 'typescript'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { JSDOM } from 'jsdom'
import { realSettingsParts, unnamedButtons } from './settings_support.mjs'

const h = React.createElement

const compile = (source) =>
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText

const prefsDoc = {
  chosen: {},
  research: { thoroughness: 50, validation_sensitivity: 50, sources: 0, kinds: ['forums'] },
  source_kinds: [{ id: 'forums' }, { id: 'reviews' }],
  classification_providers: [{ id: 'agent', label: 'Agent', ready: true }],
  market_regions: [{ id: 'auto', label: 'Automatic' }],
}

const sharedDoc = {
  bound: true,
  device: '',
  grant: { present: false, label: '', providers: [], state: '' },
  trial: { limit: 10, used: 0, left: 10, available: false },
  providers: [],
}

const headings = (document) => [...document.querySelectorAll('h3')].map((node) => node.textContent)

test('the settings drawer shows one page at a time, and a requested page is the one drawn', async () => {
  const directory = await mkdtemp(join(process.cwd(), '.settings-pages-'))
  const require = createRequire(import.meta.url)
  const loader = require('node:module')
  const originalLoad = loader._load
  const dom = new JSDOM('')
  const previous = { window: globalThis.window, CustomEvent: globalThis.CustomEvent }
  globalThis.window = dom.window
  globalThis.CustomEvent = dom.window.CustomEvent
  try {
    const pagesFile = join(directory, 'settingsPages.cjs')
    const settingsFile = join(directory, 'Settings.cjs')
    await writeFile(pagesFile, compile(await readFile('src/ui/panels/settingsPages.ts', 'utf8')))
    await writeFile(settingsFile, compile(await readFile('src/ui/panels/Settings.tsx', 'utf8')) + '\nexports.SettingsPanel = SettingsPanel\n')
    const pages = require(pagesFile)

    const stubs = {
      ...(await realSettingsParts(directory)),
      '../../arc/checkbox/checkbox': {
        Checkbox: ({ checked, label }) => h('button', { role: 'checkbox', 'aria-checked': checked, 'aria-label': label }),
      },
      '../../prefs': { usePrefs: () => ({ theme: 'system', setTheme() {}, profile: 'standard', setProfile() {}, reduce: false, setReduce() {} }) },
      '../../engine/caps': {
        CAP_ORDER: ['llm_api'],
        CAP_WORDS: { llm_api: { title: 'Model calls', unit: 'calls', money: false } },
        usedToday: () => null,
        useCaps: () => ({ caps: {}, setCap() {} }),
      },
      '../../engine/appupdate': { useAppUpdate: () => ({ phase: 'idle', checked: false, release: null, problem: '', canInstall: false, check() {}, install() {} }) },
      '../../engine/sensitivity': { useSensitivity: () => ({ sensitivity: 'all', choose: async () => '' }) },
      '../../engine/settings': {
        usePresence: () => ({ presence: null, reload: async () => {} }),
        useAbout: () => ({ version: '0.3.2', folder: '/data' }),
        useKeys: () => ({ doc: { providers: [] }, problem: '', tested: {}, set() {}, remove() {}, test() {} }),
        usePrefsDoc: () => ({ doc: prefsDoc, problem: '', save: async () => {} }),
        useSharedAccess: () => ({ doc: sharedDoc, problem: '', code: '', unlock() {}, forget() {}, make() {} }),
        useSpent: () => null,
      },
      '../../engine/usage': { useUsage: () => ({ meters: null, demo: false }) },
      '../../tour/Tour': { startTour() {} },
      '../controls': {
        Segmented: ({ label, value, options }) =>
          h('div', { role: 'radiogroup', 'aria-label': label }, options.map((option) => h('button', { key: option.value, 'data-on': option.value === value }, option.label))),
        Select: ({ label }) => h('select', { 'aria-label': label }),
        Switch: ({ label }) => h('button', { role: 'switch', 'aria-label': label }),
      },
      '../drawerEvents': { showDrawer() {} },
      './McpClients': { McpClientsGroup: () => h('section', { className: 'panel-group' }, h('h3', null, 'Use Kriko in another chat')) },
      './Proxies': { ProxiesGroup: () => h('section', { className: 'panel-group' }, h('h3', null, 'Proxies')) },
      './SearchProviders': { SearchProvidersGroup: () => h('section', { className: 'panel-group' }, h('h3', null, 'Web search')) },
    }
    loader._load = function (request, parent, isMain) {
      if (parent?.filename === settingsFile && request.startsWith('.')) {
        if (request === './settingsPages') return pages
        if (!(request in stubs)) throw new Error(`settings test has no stub for ${request}`)
        return stubs[request]
      }
      return originalLoad.call(this, request, parent, isMain)
    }
    const { SettingsPanel } = require(settingsFile)

    const render = (requested) => {
      if (requested) pages.showSettingsPage(requested)
      return new JSDOM(renderToStaticMarkup(h(SettingsPanel))).window.document
    }

    const tabs = (document) => [...document.querySelectorAll('[role="radiogroup"][aria-label="Settings page"] button')].map((node) => node.textContent)
    assert.deepEqual(tabs(render()), ['Look', 'Research', 'Keys', 'Connections', 'Usage', 'About'])

    // Version and updates are their own page, not a group at the foot of Usage.
    assert.ok(!headings(render('usage')).includes('Version and updates'))
    assert.ok(headings(render('about')).includes('Version and updates'))

    // With nothing requested, the drawer opens on Look and holds only its own groups.
    const look = render()
    assert.deepEqual(headings(look), ['Look', 'Findings', 'Chat'])
    assert.equal(look.querySelector('[data-tour="source-kinds"]'), null)

    // The tour's "Where to look" step asks for Research, and the target is there.
    const research = render('research')
    assert.deepEqual(headings(research), ['Effort', 'Region', 'Model'])
    const target = research.querySelector('[data-tour="source-kinds"]')
    assert.ok(target, 'the tour target is drawn on the Research page')
    assert.equal(target.closest('section').querySelector('h3').textContent, 'Effort')

    // A request is spent once: the next opening is back on Look.
    assert.deepEqual(headings(render()), ['Look', 'Findings', 'Chat'])

    assert.deepEqual(headings(render('keys')), ['Keys', 'Sharing'])
    assert.deepEqual(headings(render('connections')), ['Setup', 'Web search', 'Proxies', 'Use Kriko in another chat'])
    assert.deepEqual(headings(render('usage')), ['Caps'])

    // A row is an icon, a name and one control: no grey sub-line under any
    // label, on any page, and every icon-only control carries its name.
    for (const name of ['look', 'research', 'keys', 'connections', 'usage', 'about']) {
      const page = render(name)
      assert.equal(page.querySelector('.setting small'), null, `${name} keeps a sub-line under a setting`)
      assert.deepEqual(unnamedButtons(page), [], `${name} has an icon-only control with no name`)
      for (const row of page.querySelectorAll('.setting:not(.actions)')) {
        assert.ok(row.querySelector('.row-icon'), `${name} has a row with no icon: ${row.textContent}`)
      }
    }
    // Where research costs money, a coin says so and the words are its description.
    const coin = render('research').querySelector('.hint')
    assert.match(coin.querySelector('.hint-pop').textContent, /more search calls/)
    assert.equal(coin.querySelector('button').getAttribute('aria-describedby'), coin.querySelector('.hint-pop').id)
  } finally {
    loader._load = originalLoad
    globalThis.window = previous.window
    globalThis.CustomEvent = previous.CustomEvent
    dom.window.close()
    await rm(directory, { recursive: true, force: true })
  }
})

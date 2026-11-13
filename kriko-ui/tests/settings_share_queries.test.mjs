import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import ts from 'typescript'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { JSDOM } from 'jsdom'
import { realSettingsParts } from './settings_support.mjs'

const h = React.createElement

/**
 * "Share my product queries" is one checkbox on the About page, off unless the
 * reader ticked it, in the contract's own words. The words are the feature: a
 * help text that stopped saying what is sent, or a control that came up ticked,
 * would be a different promise from the one the reader agreed to.
 */

const compile = (source) =>
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText

async function loadAbout(checked) {
  const directory = await mkdtemp(join(process.cwd(), '.settings-share-'))
  const require = createRequire(import.meta.url)
  const loader = require('node:module')
  const originalLoad = loader._load
  const dom = new JSDOM('')
  const previous = { window: globalThis.window, CustomEvent: globalThis.CustomEvent }
  globalThis.window = dom.window
  globalThis.CustomEvent = dom.window.CustomEvent
  const pagesFile = join(directory, 'settingsPages.cjs')
  const settingsFile = join(directory, 'Settings.cjs')
  await writeFile(pagesFile, compile(await readFile('src/ui/panels/settingsPages.ts', 'utf8')))
  await writeFile(settingsFile, compile(await readFile('src/ui/panels/Settings.tsx', 'utf8')) + '\nexports.AboutPage = AboutPage\n')
  const pages = require(pagesFile)
  const stubs = {
    ...(await realSettingsParts(directory)),
    '../../arc/checkbox/checkbox': {
      Checkbox: ({ checked: on, label, description }) =>
        h('div', null, h('button', { role: 'checkbox', 'aria-checked': on, 'aria-label': label }), h('label', null, label), h('span', null, description)),
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
      useAbout: () => ({ version: '0.3.13', folder: '/data' }),
      useKeys: () => ({ doc: { providers: [] }, problem: '', tested: {}, set() {}, remove() {}, test() {} }),
      usePrefsDoc: () => ({ doc: { chosen: checked ? { share_queries: '1' } : {} }, problem: '', save: async () => {} }),
      useSharedAccess: () => ({ doc: null, problem: '', code: '', unlock() {}, forget() {}, make() {} }),
      useSpent: () => null,
    },
    '../../engine/usage': { useUsage: () => ({ meters: null, demo: false }) },
    '../../tour/Tour': { startTour() {} },
    '../controls': {
      Segmented: ({ label }) => h('div', { role: 'radiogroup', 'aria-label': label }),
      Select: ({ label }) => h('select', { 'aria-label': label }),
      Switch: ({ label }) => h('button', { role: 'switch', 'aria-label': label }),
    },
    '../drawerEvents': { showDrawer() {} },
    './McpClients': { McpClientsGroup: () => null },
    './Proxies': { ProxiesGroup: () => null },
    './SearchProviders': { SearchProvidersGroup: () => null },
  }
  loader._load = function (request, parent, isMain) {
    if (parent?.filename === settingsFile && request.startsWith('.')) {
      if (request === './settingsPages') return pages
      if (!(request in stubs)) throw new Error(`settings test has no stub for ${request}`)
      return stubs[request]
    }
    return originalLoad.call(this, request, parent, isMain)
  }
  const { AboutPage } = require(settingsFile)
  const page = new JSDOM(renderToStaticMarkup(h(AboutPage))).window.document
  return {
    page,
    done: async () => {
      loader._load = originalLoad
      globalThis.window = previous.window
      globalThis.CustomEvent = previous.CustomEvent
      dom.window.close()
      await rm(directory, { recursive: true, force: true })
    },
  }
}

test('the product query checkbox says what is sent, and starts off', async () => {
  const { page, done } = await loadAbout(false)
  try {
    const box = page.querySelector('[role="checkbox"]')
    assert.ok(box, 'the About page offers the checkbox')
    assert.equal(box.getAttribute('aria-checked'), 'false', 'it starts off')
    assert.equal(box.getAttribute('aria-label'), 'Share my product queries')
    const text = page.body.textContent
    assert.match(text, /the product model you looked up/)
    assert.match(text, /never sends the listing link, the page title, the time/)
    assert.match(text, /Off by default/)
  } finally {
    await done()
  }
})

test('a ticked box reads as on', async () => {
  const { page, done } = await loadAbout(true)
  try {
    assert.equal(page.querySelector('[role="checkbox"]').getAttribute('aria-checked'), 'true')
  } finally {
    await done()
  }
})

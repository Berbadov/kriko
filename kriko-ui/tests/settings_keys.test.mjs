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

test('environment keys identify their source and only saved file keys offer removal', async () => {
  const directory = await mkdtemp(join(process.cwd(), '.settings-keys-'))
  const require = createRequire(import.meta.url)
  const loader = require('node:module')
  const originalLoad = loader._load
  const compiled = join(directory, 'Settings.cjs')
  const parts = await realSettingsParts(directory)
  const providers = ['environment', 'file'].map((source) => ({
    id: source, label: source, source, present: true, hint: '…1234', purpose: 'Research',
  }))
  try {
    const source = await readFile('src/ui/panels/Settings.tsx', 'utf8')
    const code = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    }).outputText
    await writeFile(compiled, code + '\nexports.KeysGroup = KeysGroup;\n')
    loader._load = function (request, parent, isMain) {
      if (parent?.filename === compiled && request.startsWith('.')) {
        if (request === '../../engine/settings') return {
          useKeys: () => ({ doc: { providers }, tested: {}, set() {}, remove() {}, test() {} }),
        }
        if (request in parts) return parts[request]
        return {}
      }
      return originalLoad.call(this, request, parent, isMain)
    }
    const { KeysGroup } = require(compiled)
    const dom = new JSDOM(renderToStaticMarkup(React.createElement(KeysGroup)))
    try {
      const rows = dom.window.document.querySelectorAll('li.key')
      const names = (row) => [...row.querySelectorAll('button')].map((button) => button.getAttribute('aria-label'))
      assert.match(rows[0].textContent, /from the environment/)
      assert.ok(!names(rows[0]).some((name) => /^Remove/.test(name)))
      assert.ok(names(rows[1]).some((name) => /^Remove/.test(name)))
      // A key that is set shows a shut padlock, and every press is named.
      assert.equal(rows[1].querySelector('.ico-lock').getAttribute('data-locked'), 'true')
      assert.deepEqual(unnamedButtons(dom.window.document), [])
    } finally {
      dom.window.close()
    }
  } finally {
    loader._load = originalLoad
    await rm(directory, { recursive: true, force: true })
  }
})

test('shared access says what the password can do, and how much trial is left', async () => {
  const directory = await mkdtemp(join(process.cwd(), '.settings-shared-'))
  const require = createRequire(import.meta.url)
  const loader = require('node:module')
  const originalLoad = loader._load
  const compiled = join(directory, 'Settings.cjs')
  const status = (over) => ({
    bound: true,
    device: 'dpapi',
    grant: { present: false, label: '', providers: [], state: '' },
    trial: { limit: 10, used: 3, left: 7, available: true },
    providers: ['mercury', 'deepseek'],
    ...over,
  })
  const parts = await realSettingsParts(directory)
  const render = async (doc) => {
    loader._load = function (request, parent, isMain) {
      if (parent?.filename === compiled && request.startsWith('.')) {
        if (request === '../../engine/settings') {
          return { useSharedAccess: () => ({ doc, code: '', unlock() {}, forget() {}, make() {} }) }
        }
        if (request in parts) return parts[request]
        return {}
      }
      return originalLoad.call(this, request, parent, isMain)
    }
    const { SharedAccessGroup } = (() => {
      // A fresh module per render: the compiled file holds its stub from the
      // first `require`, so the second status would otherwise be the first.
      delete require.cache[require.resolve(compiled)]
      return require(compiled)
    })()
    const dom = new JSDOM(renderToStaticMarkup(React.createElement(SharedAccessGroup)))
    return { dom, text: dom.window.document.body.textContent }
  }

  try {
    const source = await readFile('src/ui/panels/Settings.tsx', 'utf8')
    const code = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    }).outputText
    await writeFile(compiled, code + '\nexports.SharedAccessGroup = SharedAccessGroup;\n')

    const asking = await render(status({}))
    try {
      // The promise made to a friend, and the one they are relying on: this is
      // the sentence that has to stay true.
      assert.match(asking.text, /works in this app only/)
      assert.match(asking.text, /Sharing\s*On, free trial/)
      assert.match(asking.text, /Free trial\s*7 of 10 left/)
      assert.match(asking.text, /Access code/)
      assert.match(asking.text, /Share your keys/)
      // What the password does is the description of a padlock, reachable by keyboard.
      const lock = asking.dom.window.document.querySelector('button[aria-label="Password scope"]')
      assert.ok(lock, 'the password note is a padlock with a name')
      assert.match(asking.dom.window.document.getElementById(lock.getAttribute('aria-describedby')).textContent, /works in this app only/)
      assert.deepEqual(unnamedButtons(asking.dom.window.document), [])
      // The friend's page owns up to the risk in one line: who can spend the keys.
      assert.match(asking.text, /Anyone with both can spend your keys/)
      // The access code field says what goes in it by its placeholder, not a line under it.
      assert.equal(asking.dom.window.document.querySelector('textarea[aria-label="Access code"]').getAttribute('placeholder'), 'Paste the code')
    } finally {
      asking.dom.window.close()
    }

    const holding = await render(status({
      grant: { present: true, label: 'Ada', providers: ['mercury', 'deepseek'], state: 'shared' },
    }))
    try {
      assert.match(holding.text, /Sharing\s*On, Ada's keys/)
      assert.match(holding.text, /Windows account/)
      // One password field, one Save, one Remove: a second code can replace the
      // one in use without a hidden "forget first" step.
      assert.match(holding.text, /Use keys/)
      assert.match(holding.text, /Forget/)
      // The trial is not what is in use, so its count is not drawn.
      assert.doesNotMatch(holding.text, /Free trial/)
    } finally {
      holding.dom.window.close()
    }

    const spent = await render(status({ trial: { limit: 10, used: 10, left: 0, available: false } }))
    try {
      assert.match(spent.text, /Free trial.*Used up, 10 of 10/)
      // A used-up trial says what to do next, since the reader is now stuck.
      assert.match(spent.text, /Paste an access code or add your own keys/)
    } finally {
      spent.dom.window.close()
    }

    // A build carrying a pepper but no trial bundle: the engine reports no
    // trial, and the screen must not invent a count for one.
    const none = await render(status({
      trial: { limit: 10, used: 0, left: 10, available: false },
    }))
    try {
      assert.match(none.text, /Sharing\s*Off, your own keys/)
      assert.match(none.text, /Free trial\s*Not in this build/)
      assert.doesNotMatch(none.text, /\d left/)
    } finally {
      none.dom.window.close()
    }
  } finally {
    loader._load = originalLoad
    await rm(directory, { recursive: true, force: true })
  }
})

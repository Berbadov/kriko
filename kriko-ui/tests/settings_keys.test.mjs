import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import ts from 'typescript'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { JSDOM } from 'jsdom'

test('environment keys identify their source and only saved file keys offer removal', async () => {
  const directory = await mkdtemp(join(process.cwd(), '.settings-keys-'))
  const require = createRequire(import.meta.url)
  const loader = require('node:module')
  const originalLoad = loader._load
  const compiled = join(directory, 'Settings.cjs')
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
        return {}
      }
      return originalLoad.call(this, request, parent, isMain)
    }
    const { KeysGroup } = require(compiled)
    const dom = new JSDOM(renderToStaticMarkup(React.createElement(KeysGroup)))
    try {
      const rows = dom.window.document.querySelectorAll('li.key')
      assert.match(rows[0].textContent, /from the environment/)
      assert.ok(![...rows[0].querySelectorAll('button')].some((button) => button.textContent === 'Remove'))
      assert.ok([...rows[1].querySelectorAll('button')].some((button) => button.textContent === 'Remove'))
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
  const render = async (doc) => {
    loader._load = function (request, parent, isMain) {
      if (parent?.filename === compiled && request.startsWith('.')) {
        if (request === '../../engine/settings') {
          return { useSharedAccess: () => ({ doc, code: '', unlock() {}, forget() {}, make() {} }) }
        }
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
      assert.match(asking.text, /7 of 10 Kriko Agent questions left/)
      assert.match(asking.text, /Paste the access code and the password/)
      assert.match(asking.text, /Sharing your own keys with a friend/)
    } finally {
      asking.dom.window.close()
    }

    const holding = await render(status({
      grant: { present: true, label: 'Ada', providers: ['mercury', 'deepseek'], state: 'shared' },
    }))
    try {
      assert.match(holding.text, /Ada's keys/)
      assert.match(holding.text, /bound to this Windows account/)
      assert.match(holding.text, /Forget them/)
    } finally {
      holding.dom.window.close()
    }

    const spent = await render(status({ trial: { limit: 10, used: 10, left: 0, available: false } }))
    try {
      assert.match(spent.text, /trial on this computer is used up \(10 of 10 questions\)/)
    } finally {
      spent.dom.window.close()
    }
  } finally {
    loader._load = originalLoad
    await rm(directory, { recursive: true, force: true })
  }
})

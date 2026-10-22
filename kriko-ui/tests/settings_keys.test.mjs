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

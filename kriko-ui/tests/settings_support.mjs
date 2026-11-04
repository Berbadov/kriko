import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import ts from 'typescript'

/** Compile one TSX source to CommonJS, the way the settings tests load a panel. */
export const compile = (source) =>
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText

/** The pieces every settings group draws with (icons, rows, hints), compiled for
 *  real, so a test sees the markup a reader gets rather than a stub of it. Keyed
 *  by the import text a panel uses. */
export async function realSettingsParts(directory) {
  const require = createRequire(import.meta.url)
  const icon = join(directory, 'Icon.cjs')
  const parts = join(directory, 'settingsParts.cjs')
  await writeFile(icon, compile(await readFile('src/ui/Icon.tsx', 'utf8')))
  await writeFile(parts, compile(await readFile('src/ui/panels/settingsParts.tsx', 'utf8')).replace('require("../Icon")', 'require("./Icon.cjs")'))
  const pages = join(directory, 'settingsPages.cjs')
  await writeFile(pages, compile(await readFile('src/ui/panels/settingsPages.ts', 'utf8')))
  return { '../Icon': require(icon), './settingsParts': require(parts), './settingsPages': require(pages) }
}

/** An icon-only control has to carry its name: a button with no text and no
 *  aria-label is a control a screen reader cannot say. */
export function unnamedButtons(document) {
  return [...document.querySelectorAll('button, [role="radio"], [role="checkbox"], [role="switch"]')]
    .filter((node) => !node.textContent.trim() && !node.getAttribute('aria-label'))
    .map((node) => node.outerHTML.slice(0, 90))
}

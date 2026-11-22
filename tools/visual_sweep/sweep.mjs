// Drives the real desktop UI and fails on what a unit test cannot see: a title
// that fell back to a serif, a menu that runs off the window, two sets of window
// buttons, a page that scrolls sideways, a screen that logs an error.
//
//   node tools/visual_sweep/sweep.mjs --cdp http://127.0.0.1:9222 --out <folder>
//   node tools/visual_sweep/sweep.mjs --url http://localhost:5173 --out <folder>
//
// --cdp   the packaged window (start it with WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=
//         --remote-debugging-port=9222 and KRIKO_VERIFY=1 so it is not folded into
//         a Kriko the reader already has open). Window buttons are then expected.
// --url   the built or dev UI in a browser, with an engine behind it. No window
//         buttons are expected.
// --ask "question"   also asks one real question and a follow-up (needs a ready agent)
// --reconnect <pid>  kills that engine process, checks the offline screen, presses
//                    Reconnect and expects the window to come back (packaged only)
// --quick            home, picker, every screen and Settings in one palette, one size
//
// Playwright is not a dependency of the repo: it is found in this checkout, then
// in the global npm folder.

import { createRequire } from 'node:module'
import { execFileSync, execSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const require = createRequire(import.meta.url)
function loadPlaywright() {
  for (const where of [undefined, join(execSync('npm root -g', { encoding: 'utf8' }).trim(), 'playwright')]) {
    try { return where ? require(where) : require('playwright') } catch { /* try the next place */ }
  }
  throw new Error('playwright is not installed here or globally (npm i -g playwright)')
}

const args = process.argv.slice(2)
const flag = (name) => args.includes(`--${name}`)
const value = (name) => (args.includes(`--${name}`) ? args[args.indexOf(`--${name}`) + 1] : undefined)
const out = value('out') ?? join(process.cwd(), 'sweep-out')
const quick = flag('quick')
mkdirSync(out, { recursive: true })

const { chromium } = loadPlaywright()
const results = []
const consoleProblems = []
let shot = 0

const SCREENS = ['Ask', 'Compare', 'Queue', 'History', 'Procurement', 'Prices', 'Catalogs', 'Sites', 'For you']
const PALETTES = ['dark', 'gray', 'paper', 'white']
const SIZES = { small: { width: 1280, height: 720 }, large: { width: 2560, height: 1440 } }

function record(state, check, ok, detail = '') {
  results.push({ state, check, ok, detail })
  if (!ok) console.log(`  FAIL [${state}] ${check} ${detail}`)
}

const browser = value('cdp')
  ? await chromium.connectOverCDP(value('cdp'))
  : await chromium.launch({ channel: process.env.SWEEP_CHANNEL || 'chrome' }).catch(() => chromium.launch())
const context = browser.contexts()[0] ?? (await browser.newContext())
const page = context.pages()[0] ?? (await context.newPage())
const inWindow = Boolean(value('cdp'))
if (!inWindow) await page.goto(value('url') ?? 'http://localhost:5173')

page.on('console', (message) => { if (message.type() === 'error') consoleProblems.push(message.text().slice(0, 300)) })
page.on('pageerror', (error) => consoleProblems.push(`uncaught: ${String(error).slice(0, 300)}`))

const cdp = await context.newCDPSession(page)
await cdp.send('DOM.enable')
await cdp.send('CSS.enable')

async function resize(size) {
  await page.setViewportSize(size)
  await page.waitForTimeout(300)
}

async function setPalette(name) {
  await page.evaluate((theme) => localStorage.setItem('kriko.theme', theme), name)
  await page.reload()
  await live()
}

let toured = false

async function live() {
  await page.waitForSelector('.lrail', { timeout: 90000 })
  await page.evaluate(() => document.fonts.ready)
  const skip = page.getByRole('button', { name: 'Skip' })
  if (await skip.isVisible({ timeout: 1500 }).catch(() => false)) {
    if (!toured) {
      toured = true
      await snap('first-start tour')
    }
    await skip.click()
    await page.waitForTimeout(400)
  }
}

/** What the page cannot say about itself: which font was actually painted. */
async function paintedFonts(selector) {
  const { root } = await cdp.send('DOM.getDocument', { depth: 0 })
  const { nodeIds } = await cdp.send('DOM.querySelectorAll', { nodeId: root.nodeId, selector })
  const seen = []
  for (const nodeId of nodeIds.slice(0, 6)) {
    const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId })
    seen.push(...fonts.map((font) => ({ family: font.familyName, custom: font.isCustomFont, glyphs: font.glyphCount })))
  }
  return seen
}

async function audit(state) {
  await page.evaluate(() => document.fonts.ready)
  const found = await page.evaluate(() => {
    const vw = innerWidth
    const vh = innerHeight
    const visible = (el) => {
      const rect = el.getBoundingClientRect()
      const style = getComputedStyle(el)
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity) > 0.05
    }
    const overlays = [...document.querySelectorAll('[role=listbox],[role=menu],[role=dialog],[role=alertdialog],[role=tooltip],dialog[open],.menu,.popover,.modal,.sheet')]
      .filter(visible)
      .map((el) => {
        const r = el.getBoundingClientRect()
        const top = document.elementFromPoint(Math.min(vw - 1, Math.max(0, r.left + r.width / 2)), Math.min(vh - 1, Math.max(0, r.top + 6)))
        return {
          name: `${el.tagName.toLowerCase()}.${String(el.className).split(' ')[0]}[${el.getAttribute('role') ?? ''}]`,
          outside: r.left < -1 || r.top < -1 || r.right > vw + 1 || r.bottom > vh + 1,
          rect: [r.left, r.top, r.right, r.bottom].map(Math.round),
          covered: !(top && (el === top || el.contains(top))),
        }
      })
    const ruler = document.createElement('canvas').getContext('2d')
    const cut = [...document.querySelectorAll('select, button, .k-btn')].filter(visible).filter((el) => {
      if (el.tagName === 'SELECT') {
        const style = getComputedStyle(el)
        ruler.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
        const label = el.selectedOptions[0]?.textContent ?? ''
        return ruler.measureText(label).width > el.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) + 1
      }
      return el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflow !== 'visible'
    }).map((el) => (el.textContent || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40))
    const empty = [...document.querySelectorAll('button, a.k-btn')].filter(visible).filter((el) => !el.textContent.trim() && !el.querySelector('svg, img, canvas, i') && !el.getAttribute('aria-label') && !el.getAttribute('title')).map((el) => `${el.tagName.toLowerCase()}.${String(el.className).split(' ')[0]}`)
    const stacks = new Map()
    for (const el of document.querySelectorAll('body *')) {
      if (!visible(el) || !el.childNodes.length || ![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue
      const stack = getComputedStyle(el).fontFamily
      stacks.set(stack, (stacks.get(stack) ?? 0) + 1)
    }
    const declared = new Set([...document.fonts].map((f) => f.family.replace(/["']/g, '')))
    const unresolved = []
    for (const stack of stacks.keys()) {
      const first = stack.split(',')[0].trim().replace(/["']/g, '')
      const generic = /^(serif|sans-serif|monospace|system-ui|ui-monospace|ui-sans-serif|ui-serif|cursive|fantasy|inherit)$/i.test(first)
      if (!generic && !declared.has(first)) unresolved.push(first)
    }
    return {
      overlays,
      cut,
      empty,
      unresolved,
      controls: [...document.querySelectorAll('button[aria-label="Minimise"]')].filter(visible).length,
      bars: [...document.querySelectorAll('.titlebar')].filter(visible).length,
      sideways: document.documentElement.scrollWidth > vw + 1 || document.body.scrollWidth > vw + 1,
      titles: [...document.querySelectorAll('h1')].filter(visible).length,
    }
  })
  record(state, 'one set of window buttons', inWindow ? found.controls === 1 && found.bars === 1 : found.controls === 0, `buttons=${found.controls} bars=${found.bars}`)
  record(state, 'no sideways scroll', !found.sideways)
  record(state, 'no empty button is drawn', found.empty.length === 0, found.empty.join(', '))
  record(state, 'no choice or button text is cut off', found.cut.length === 0, found.cut.join(' | '))
  for (const overlay of found.overlays) {
    record(state, `${overlay.name} stays in the window`, !overlay.outside, `rect=${overlay.rect}`)
    record(state, `${overlay.name} is not under another layer`, !overlay.covered)
  }
  record(state, 'every font in use resolves to a loaded face', found.unresolved.length === 0, found.unresolved.join(', '))
  if (found.titles) {
    const titleFonts = await paintedFonts('h1')
    const bad = titleFonts.filter((font) => !(font.custom && /Chivo Mono|Atkinson/.test(font.family)))
    record(state, 'titles paint in Chivo Mono (or the accessibility face)', titleFonts.length > 0 && bad.length === 0, bad.map((f) => f.family).join(', '))
  }
  const bodyFonts = await paintedFonts('.lrail-label, main p, .page-head p')
  const badBody = bodyFonts.filter((font) => !(font.custom && /Inter|Atkinson/.test(font.family)))
  record(state, 'reading text paints in Inter', badBody.length === 0, badBody.map((f) => f.family).join(', '))
}

async function snap(name, check = true) {
  const file = `${String(++shot).padStart(2, '0')}-${name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.png`
  await page.screenshot({ path: join(out, file) })
  if (check) await audit(name)
}

const rail = (label) => page.locator('.lrail-nav button', { hasText: new RegExp(`^\\s*${label}`) }).first()

async function visit(label) {
  await rail(label).click()
  await page.waitForTimeout(450)
}

async function openPicker(name) {
  const pill = page.locator('.composer-agent').first()
  if (!(await pill.count())) return
  await pill.click()
  await page.waitForSelector('[role=listbox]', { timeout: 3000 })
  await page.waitForTimeout(150)
  const options = await page.locator('[role=listbox] [role=option]').count()
  const opened = await page.evaluate(() => `${document.activeElement?.tagName}[${document.activeElement?.getAttribute('role')}] hasFocus=${document.hasFocus()}`)
  record(name, 'picker takes focus when it opens', opened.includes('[option]'), `active=${opened}`)
  await snap(`${name} agent picker open`)
  await page.keyboard.press('ArrowDown')
  const moved = await page.evaluate(() => document.activeElement?.getAttribute('role'))
  record(name, 'picker takes the arrow keys', options < 2 || moved === 'option', `options=${options}`)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(250)
  record(name, 'Escape closes the picker', (await page.locator('[role=listbox]').count()) === 0)
}

async function settings() {
  await page.locator('.lrail-foot button, .lrail button', { hasText: /Settings/ }).last().click()
  await page.waitForSelector('.settings-nav')
  const sections = await page.locator('.settings-nav button').allTextContents()
  for (const section of sections) {
    await page.locator('.settings-nav button', { hasText: section.trim() }).first().click()
    await page.waitForLoadState('networkidle').catch(() => undefined)
    await page.waitForFunction(() => (document.querySelector('.settings-pane')?.textContent ?? '').trim().length > 40, null, { timeout: 8000 }).catch(() => undefined)
    await page.waitForTimeout(400)
    await snap(`Settings ${section.trim()}`)
  }
  const search = page.locator('input[type=search], input[placeholder*="Search" i]').first()
  if (await search.count()) {
    await search.fill('model')
    await page.waitForTimeout(350)
    await snap('Settings search')
    await search.fill('')
  }
}

/** A catalog's product, two of them side by side, and an estimate: the screens that need data. */
async function withData(name) {
  await visit('Catalogs')
  const open = page.getByRole('button', { name: 'Open' }).first()
  if (!(await open.count())) return record(name, 'a catalog is installed to walk', false, 'no Open button on Catalogs')
  await open.click()
  await page.waitForTimeout(900)
  await snap(`${name} catalog products`)
  const names = ['MacBook Air M2', 'ThinkPad T14']
  for (const product of names) {
    await page.getByText(product).first().click()
    const compareButton = page.getByRole('button', { name: /^(Add to compare|Compare)$/ }).first()
    await compareButton.waitFor({ timeout: 8000 })
    await page.waitForTimeout(700)
    await snap(`${name} product ${product}`)
    if ((await compareButton.textContent())?.trim() === 'Add to compare') await compareButton.click()
    await page.waitForTimeout(400)
    if (product === names[0]) {
      await page.getByRole('button', { name: 'Add to estimate' }).first().click().catch(() => undefined)
      await page.waitForTimeout(500)
      await snap(`${name} add to estimate`)
      await page.keyboard.press('Escape')
    }
    await visit('Catalogs')
    await page.getByRole('button', { name: 'Open' }).first().click()
    await page.waitForTimeout(700)
  }
  await visit('Compare')
  await page.waitForTimeout(900)
  await snap(`${name} compare two products`)
  await visit('Procurement')
  await page.waitForTimeout(600)
  await snap(`${name} procurement with an estimate`)
}

async function overlays(name) {
  for (const trigger of ['Usage', 'Queue', 'More']) {
    const button = page.locator('.strip button', { hasText: trigger }).first()
    if (!(await button.count())) continue
    await button.click().catch(() => undefined)
    await page.waitForTimeout(300)
    await audit(`${name} after ${trigger}`)
    await page.keyboard.press('Escape')
  }
}

async function finished() {
  await page.waitForSelector('button.send.is-running', { timeout: 30000 }).catch(() => undefined)
  await page.waitForFunction(() => !document.querySelector('button.send.is-running'), null, { timeout: 15 * 60 * 1000 })
  await page.waitForTimeout(800)
}

async function ask(question) {
  await visit('Ask')
  const box = page.locator('.composer-field').first()
  await box.fill(question)
  await page.locator('button.send').first().click()
  await page.waitForSelector('.composer-field', { timeout: 5000 })
  await finished()
  await snap('Ask answered')
  await page.locator('.composer-field').first().fill('Which of those is the most serious?')
  await page.locator('button.send').first().click()
  await finished()
  await snap('Ask follow-up answered')
}

async function reconnect(pid) {
  execFileSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' })
  await page.getByText('Kriko could not connect').waitFor({ timeout: 60000 })
  await snap('Engine down')
  const started = Date.now()
  await page.getByRole('button', { name: 'Reconnect' }).click()
  const back = await page.waitForSelector('.lrail', { timeout: 90000 }).then(() => true).catch(() => false)
  record('Reconnect', 'the window comes back after one press', back, `${Math.round((Date.now() - started) / 1000)} s`)
  if (back) await snap('Reconnected')
}

try {
  await live()
  const palettes = quick ? ['dark'] : PALETTES
  for (const [sizeName, size] of Object.entries(flag('only-reconnect') || flag('only-ask') ? {} : quick ? { small: SIZES.small } : SIZES)) {
    await resize(size)
    for (const palette of palettes) {
      if (sizeName === 'large' && palette !== 'dark' && palette !== 'paper') continue
      await setPalette(palette)
      const tag = `${palette} ${sizeName}`
      await snap(`${tag} home`)
      await openPicker(`${tag} home`)
      const everything = palette === 'dark' && sizeName === 'small'
      for (const label of everything ? SCREENS.slice(1) : ['History', 'Catalogs']) {
        await visit(label)
        await snap(`${tag} ${label}`)
      }
      if (everything) {
        await visit('Ask')
        await overlays(tag)
        await withData(tag).catch((error) => record(tag, 'the data screens could be walked', false, String(error).slice(0, 200)))
      }
      if (everything || palette === 'paper') await settings()
    }
  }
  await resize(SIZES.small)
  if (value('ask')) await ask(value('ask'))
  if (value('reconnect')) await reconnect(value('reconnect'))
} catch (error) {
  record('sweep', 'ran to the end', false, String(error).slice(0, 400))
  await page.screenshot({ path: join(out, 'zz-failure.png') }).catch(() => undefined)
}

const unexpected = consoleProblems.filter((text) => !/favicon|ERR_CONNECTION_REFUSED|Failed to load resource.*(404|0)/i.test(text))
record('console', 'no uncaught errors or console errors', unexpected.length === 0, unexpected.slice(0, 3).join(' | '))

const failed = results.filter((row) => !row.ok)
writeFileSync(join(out, 'sweep-results.json'), JSON.stringify({ at: new Date().toISOString(), checks: results.length, failed: failed.length, results }, null, 1))
console.log(`${results.length} checks, ${failed.length} failed, ${shot} screenshots in ${out}`)
await browser.close().catch(() => undefined)
process.exit(failed.length ? 1 : 0)

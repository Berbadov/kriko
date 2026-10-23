import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

/**
 * The desktop layout's budgets, read from the stylesheets themselves.
 *
 * These are the five defects a reader photographed. The numbers here are not
 * taste: each one is a height the CSS produces, and the point of asserting it is
 * that a later edit has to move the number on purpose rather than put the space
 * back by accident.
 */

const read = async (path) => (await readFile(new URL(`../${path}`, import.meta.url), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '')

/** The declarations of one rule, found by its exact selector and first match. */
function rule(css, selector) {
  const at = css.indexOf(`\n${selector} {`)
  assert.ok(at > -1, `no rule for ${selector}`)
  const open = css.indexOf('{', at)
  const close = css.indexOf('}', open)
  assert.ok(close > open, `unterminated rule for ${selector}`)
  return css.slice(open + 1, close)
}

function declaration(css, selector, property) {
  const found = new RegExp(`(?:^|[;{\\s])${property}:\\s*([^;]+);`).exec(rule(css, selector))
  assert.ok(found, `${selector} does not set ${property}`)
  return found[1].trim()
}

const px = (value) => {
  const found = /^(-?[\d.]+)px$/.exec(value.trim())
  assert.ok(found, `not a pixel value: ${value}`)
  return Number(found[1])
}

/** A unitless number, such as a line-height. */
const num = (value) => {
  const found = /^-?[\d.]+$/.exec(value.trim())
  assert.ok(found, `not a number: ${value}`)
  return Number(found[0])
}

/** `padding: 3px` and `border: 1px solid x` are held in the same property. */
const lead = (value) => px(value.trim().split(/\s+/)[0])

test('the window buttons ride in the top bar, so no band is spent above it', async () => {
  const css = await read('src/styles/shell.css')
  const pad = px(declaration(css, ':root', '--app-pad'))
  const bar = px(declaration(css, ':root', '--topbar-h'))
  const caption = px(declaration(css, ':root', '--caption-w'))
  const button = px(declaration(css, '.titlebar-btn', 'width'))

  // The reserve is exactly the three window buttons: change one width and this
  // fails rather than letting a control sit under the closing X.
  assert.equal(caption, button * 3, 'the caption reserve is not the three window buttons')

  // The strip is inside the bar's row, not a band above it.
  assert.equal(declaration(css, '.titlebar', 'top'), 'var(--app-pad)')
  assert.equal(declaration(css, '.titlebar', 'height'), 'var(--topbar-h)')
  assert.equal(declaration(css, '.topbar', 'height'), 'var(--topbar-h)')

  // One gutter and one row. Measured on the reader's screen: the title bar (28)
  // plus the frame (6) plus the bar (42) came to 76px, and 93 device pixels at
  // 125% scaling.
  assert.ok(pad + bar <= 48, `the top chrome is ${pad + bar}px; the reader saw 76px`)

  // The page gives up no band, and the drawer opens below the row rather than
  // under the window's own strip.
  assert.ok(!/\[data-titlebar\][^{]*#root/.test(css), 'the page still reserves a title-bar band')
  assert.match(declaration(css, ':root', '--drawer-top'), /--topbar-h/)
  assert.match(declaration(css, '.drawer', 'top'), /--drawer-top/)
})

test('the pill of places is the bar it sits in, and leaves the window buttons clear', async () => {
  const css = await read('src/styles/shell.css')
  const bar = px(declaration(css, ':root', '--topbar-h'))
  const tab = px(declaration(css, '.topbar-tab', 'height'))
  const navPad = px(declaration(css, '.topbar-nav', 'padding'))
  const navEdge = lead(declaration(css, '.topbar-nav', 'border'))

  // Before: a 48px pill centred in a 42px row, with its lower 6px outside it.
  assert.equal(tab + (navPad + navEdge) * 2, bar, 'the pill of places overflows its row')

  // The room for the window buttons comes out of the right column's padding, so
  // the tabs stay centred on the window.
  assert.match(
    declaration(css, ':root[data-titlebar] .topbar-right', 'padding-right'),
    /--caption-w/,
    'the window buttons are not kept clear of the status cluster',
  )
})

test('the drawer scrolls a named body, and its head is never over that body', async () => {
  const css = await read('src/styles/shell.css')
  const drawer = await read('src/ui/Drawer.tsx')

  // Before: `.drawer > div:last-child` — one extra element in the drawer and the
  // scroll was gone, leaving `.drawer { overflow: hidden }` to clip the last card.
  assert.ok(!/\.drawer > div:last-child/.test(css), 'the scroll region is still found by position')
  const body = rule(css, '.drawer-body')
  assert.match(body, /overflow-y:\s*auto/)
  assert.match(body, /min-height:\s*0/)
  assert.match(body, /flex:\s*1;/)
  assert.match(drawer, /className="drawer-body"/, 'the scroll region carries no name')

  // The drawer is a column, so the body's `flex: 1` is a height it can scroll in.
  assert.match(rule(css, '.drawer'), /display:\s*flex/)
  assert.match(rule(css, '.drawer'), /flex-direction:\s*column/)

  // The head ends above the body: a sticky head over a scroller is what hides the
  // first card of a panel, and the drawer does not scroll for it to stick to.
  assert.ok(!/position:\s*sticky/.test(rule(css, '.drawer-head')), 'the head lies over the body')
  assert.equal(declaration(css, '.drawer-head', 'flex'), 'none')
})

test('a long note wraps inside its card and never squeezes the control beside it', async () => {
  const css = await read('src/styles/panels.css')
  const text = rule(css, '.setting > span:first-child')

  // Before, nothing in `.setting` said which of the two gives way, so a note
  // wider than the room left by the switch ran out of the card. `1 1 auto`
  // rather than `1`: a stacked setting lays the same span out in a column, where
  // a zero flex basis would be a height.
  assert.match(text, /flex:\s*1 1 auto/)
  assert.match(text, /min-width:\s*0/)
  assert.match(rule(css, '.setting > :last-child'), /flex:\s*none/)
  assert.match(rule(css, '.setting > span:first-child small'), /overflow-wrap:\s*anywhere/)

  // Nothing about a setting may cap its own height: the note decides how tall the
  // card is, and the reader gets the whole sentence at any drawer width.
  const setting = rule(css, '.setting.product-only-setting')
  for (const cap of ['height:', 'max-height:', 'overflow: hidden', 'line-clamp']) {
    assert.ok(!setting.includes(cap), `.setting must not cap its height with ${cap}`)
  }
  assert.match(setting, /align-items:\s*flex-start/)
})

test('the settings gear is a square, at a size the reader can find', async () => {
  const css = await read('src/styles/shell.css')
  const base = rule(await read('src/styles/base.css'), '.icon')
  const topbar = await read('src/ui/TopBar.tsx')

  const w = px(declaration(css, '.topbar-settings .icon', 'width'))
  const h = px(declaration(css, '.topbar-settings .icon', 'height'))
  assert.equal(w, h, 'a gear with two sizes is the squash the reader saw')
  assert.ok(w >= 20, `the gear is ${w}px; the base icon's 18px is where it was unreadable`)
  assert.equal(declaration(css, '.topbar-settings .icon', 'stroke-width'), '1.75')

  // The base icon is square too, so losing the override cannot squash the gear —
  // only shrink it, which this number would catch.
  assert.match(base, /width:\s*18px/)
  assert.match(base, /height:\s*18px/)

  // It is a labelled button, so the icon and the word sit on one line.
  assert.match(topbar, /<Icon name="gear" size=\{21\} \/>/)
  assert.match(topbar, /<span className="topbar-label">Settings<\/span>/)
})

test('the tour card is kept inside the window, whatever its size', async () => {
  const tour = await read('src/tour/Tour.tsx')
  const place = tour.slice(tour.indexOf('function place('), tour.indexOf('export function Tour'))

  // The card the reader named "More" is anchored beside the top bar's More
  // button. `h - 260` and `w - CARD_W - 16` are the room a card needs; in a
  // window smaller than that they are negative, and the card was placed at a
  // negative top or left — over the window's own edge.
  assert.match(tour, /const inside = \(value: number, room: number\) => Math\.max\(16, Math\.min\(value, room\)\)/)
  assert.equal([...place.matchAll(/(?:top|left): inside\(/g)].length, 4, 'a placement still bypasses the clamp')
  assert.ok(!/(?:top|left): Math\.min\(/.test(place), 'a placement can still land past the window edge')
})

test('a product card and a source row each give a line back', async () => {
  const chat = await read('src/styles/chat.css')
  const rail = await read('src/styles/rail.css')

  // The product card: two tight lines beside the presses.
  assert.equal(declaration(chat, '.product-card', 'padding'), '6px 10px')
  assert.equal(px(declaration(chat, '.product-card span', 'font-size')), 11.5)
  assert.equal(num(declaration(chat, '.product-card strong', 'line-height')), 1.35)
  assert.equal(px(declaration(chat, '.product-card .card-actions .btn', 'height')), 28)
  assert.equal(declaration(chat, '.product-card .card-actions', 'gap'), '6px')

  // 14px name and 11.5px note, one line each at 1.35, a 1px gap, and the padding.
  const card = Math.ceil(14 * 1.35 + 1 + 11.5 * 1.35 + 12)
  assert.ok(card <= 48, `a product card is ${card}px; it was 57px`)

  // A source row: words and the link side by side, not stacked. The words keep
  // every field — name, host, tier and how it was read — and the link its own.
  assert.match(rule(rail, '.cr-item'), /flex-wrap:\s*wrap/)
  assert.match(rule(rail, '.cr-item'), /align-items:\s*center/)
  assert.match(rule(rail, '.cr-main'), /flex:\s*1 1 auto/)
  assert.equal(declaration(rail, '.cr-main', 'padding'), '7px 10px')
  const row = Math.ceil(7 + 13.5 * 1.35 + 2 + 11.5 * 1.5 + 7)
  assert.ok(row <= 56, `a source row is ${row}px; it was 91px with the link on its own line`)
  assert.equal(declaration(rail, '.cr-actions', 'padding'), '0 9px 0 0')

  // The sources under a claim: the chip is the row, and the gaps are chip-sized.
  assert.equal(declaration(rail, '.claim-sources', 'gap'), '4px')
  assert.equal(declaration(rail, '.claim-chip', 'padding'), '3px 9px 3px 6px')
  const chip = Math.ceil(3 + 12 + 3 + 2)
  assert.ok(chip <= 20, `a source chip is ${chip}px; it was 22px`)

  // Every field of the card behind a chip stays: the quote, the standing, the
  // site, the kind of page, the link and the close.
  const claim = await read('src/ui/ClaimChip.tsx')
  for (const field of ['claim-card-head', 'blockquote', 'claim-card-meta', 'claim-card-acts', 'Open the page']) {
    assert.ok(claim.includes(field), `the claim card lost ${field}`)
  }
})

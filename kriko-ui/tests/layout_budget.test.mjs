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

test('the strip is the only band above the page, and the window buttons ride in it', async () => {
  const css = await read('src/styles/shell.css')
  const strip = px(declaration(css, ':root', '--strip-h'))
  const button = px(declaration(css, '.titlebar-btn', 'width'))

  // The strip is the slim row across the column: 40px, the same height as the
  // window buttons that ride in it, so no band is spent above the page.
  assert.equal(strip, 40, 'the strip is not the 40px row the shell was drawn for')
  assert.equal(declaration(css, '.strip', 'height'), 'var(--strip-h)')
  assert.equal(declaration(css, '.titlebar', 'height'), 'var(--strip-h)')
  assert.equal(button, 46, 'a window button is no longer the 46px the caption was measured for')

  // The buttons are in flow at the strip's right end, not fixed over the page,
  // so they can never sit on a control or take a press from it.
  assert.ok(!/position:\s*fixed/.test(rule(css, '.titlebar')), 'the window buttons are fixed over the page')
  assert.equal(declaration(css, '.strip', 'border-bottom').split(/\s+/).pop(), 'var(--edge)')

  // The row gives up its end padding when the system bar is not drawn, so the
  // closing X is flush with the window's edge and nothing sits under it.
  assert.match(css, /:root\[data-titlebar\] \.strip \{\s*padding-right: 0;/)

  // The page is the stage: no inset border, no radius, filling the column.
  const stage = rule(css, '.stage')
  assert.ok(!/border:/.test(stage), 'the stage still draws its own inset border')
  assert.ok(!/border-radius/.test(stage), 'the stage still rounds its own corners')
  assert.match(rule(css, '.shell-main'), /background:\s*var\(--ground\)/)
})

test('the rail is a labelled column of 232px that collapses to icons under 900px', async () => {
  const css = await read('src/styles/rail.css')
  const shell = await read('src/styles/shell.css')

  assert.equal(px(declaration(shell, ':root', '--rail-open')), 232, 'the rail is not the 232px it was drawn at')
  assert.equal(declaration(css, '.lrail', 'width'), 'var(--rail-open)')
  assert.equal(declaration(css, '.lrail', 'background'), 'var(--sheet)')
  assert.match(rule(css, '.lrail'), /border-right:\s*1px solid var\(--edge\)/)

  // Under 900px of window the rail is the icon column and the words leave the
  // sight line, but stay in the page for the screen reader.
  const collapsed = /@media \(max-width: 899px\) \{([\s\S]*?)\n\}\n/.exec(css)
  assert.ok(collapsed, 'the rail has no collapse under 900px')
  assert.match(collapsed[1], /width:\s*var\(--rail-shut\)/)
  assert.match(collapsed[1], /\.lrail-label \{[\s\S]*?clip: rect\(0 0 0 0\)/, 'the words are removed from the accessible name when collapsed')
})

test('a rail row is 40px, the active row is marked, and New chat is the only brand fill', async () => {
  const css = await read('src/styles/rail.css')
  const rail = await read('src/ui/Rail.tsx')

  assert.equal(px(declaration(css, '.lrail-item', 'height')), 40)
  assert.equal(declaration(css, '.lrail-item[data-on=\'true\']', 'background'), 'var(--select-strong)')
  assert.match(rule(css, '.lrail-item[data-on=\'true\']::before'), /width:\s*2px/)
  assert.equal(declaration(css, '.lrail-item[data-on=\'true\']::before', 'background'), 'var(--brand)')

  // The one filled brand control in the rail is New chat; the update dot is not a fill.
  assert.equal(declaration(css, '.lrail-new', 'background'), 'var(--brand)')
  assert.notEqual(declaration(css, '.lrail-dot', 'background'), 'var(--brand)')

  // Every row says a word, not an icon alone.
  for (const label of ['Ask', 'Compare', 'Queue', 'History', 'Procurement', 'Prices', 'Catalogs', 'Sites', 'For you', 'Settings']) {
    assert.ok(rail.includes(`>${label}<`) || rail.includes(`label: '${label}'`), `the rail has no word for ${label}`)
  }
})

test('a panel page scrolls in the page, and nothing is left to clip it', async () => {
  const css = await read('src/styles/shell.css')
  const panel = await read('src/ui/PanelPage.tsx')

  // The page scrolls; the stage only holds it. No drawer or scrim remains to cut a card.
  assert.match(rule(css, '.page'), /overflow:\s*auto/)
  assert.match(rule(css, '.stage'), /overflow:\s*hidden/)
  assert.ok(!/\.drawer\b/.test(css), 'a drawer rule is still in the shell')
  assert.ok(!/\.scrim\b/.test(css), 'a scrim rule is still in the shell')

  // The title is a screen title, in the screen's own heading.
  assert.match(panel, /className="k-screen panel-page"/)
  assert.match(panel, /className="k-head"/)
  assert.match(panel, /className="k-title"/)
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

test('the settings row is a labelled rail item, a word beside its icon', async () => {
  const rail = await read('src/ui/Rail.tsx')
  const css = await read('src/styles/rail.css')

  // Settings sits at the foot of the rail with its word, and its icon is the
  // rail's standard size, so the two read as one line.
  assert.match(rail, /<Icon name="gear" size=\{18\} \/>/)
  assert.match(rail, /<span className="lrail-label">Settings<\/span>/)
  assert.match(rule(css, '.lrail-foot'), /border-top:\s*1px solid var\(--edge\)/)
  assert.equal(px(declaration(css, '.lrail-item', 'height')), 40)
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

test('a finding keeps one neutral divider and its evidence tip cannot widen the page', async () => {
  const identity = await read('src/styles/identity.css')
  const rail = await read('src/styles/rail.css')

  // The badge carries the severity. A per-severity rule turned a product page
  // into a ruler of dashes, and a full-width amber bar spent the attention
  // budget on the row it had already marked.
  assert.ok(!/\.risk-list > li:has\(\.level/.test(identity), 'a finding divider still varies with severity')

  // The evidence tip used to open to the right and extend the scroll box by
  // 19px at 760; the next scrollIntoView moved every line half a word off the
  // left edge. It opens left from its mark instead.
  assert.match(rule(rail, '.risk-title .ev-tip'), /right:\s*0/)
  assert.match(rule(rail, '.risk-title .ev-tip'), /left:\s*auto/)
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

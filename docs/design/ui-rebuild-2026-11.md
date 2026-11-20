# UI rebuild — The dossier, November 2026

This is the shared brief for the desktop app, the phone app, the website and the
browser extension. Each surface adapts it to its own stack. The goal is a
recognisably Kriko interface, not four skins that happen to share a hex value.

## What Kriko is

A local-first knowledge engine for manufactured products. A reader names one
thing they might buy and Kriko answers one question: *what is known to go wrong
with this specific one*, with the page and the quote behind every finding.

The interface is closer to a field dossier than to a chat product. Its subject
matter is evidence: sources, dates, certainty, cost, and the difference between
what a listing claims and what owners report. That is where the visual language
should come from.

## The idea

**The dossier.** Paper, ink, ruled entries, a margin for evidence. The interface
should read like a well-kept case file: dense where facts are dense, quiet
everywhere else, and never decorated for its own sake.

Three devices carry it:

1. **The evidence gutter.** Findings are ruled rows, not floating cards. A
   narrow left gutter holds the severity mark and the source count; the finding
   itself sits on the page like a line in a ledger. The rule under the row
   repeats the severity by shape, not only by colour.
2. **The case number.** Metadata is set in the body face, one step heavier: dates, counts, source hosts,
   run ids, model names. The figures are tabular. It is the texture that says "instrument", and it keeps
   prose and evidence visually separate.
3. **The index rule.** Section headings are separated by a hairline that runs
   the width of the content, with a small tabular index at the left. No all-caps
   eyebrows, no centred section titles.

Everything else stays plain: one main colour, flat surfaces, no gradients used as
decoration, no glass used as decoration, no drop shadows on resting surfaces.

## Tokens

Use these values, adapted to each surface's token file. Light is paper; dark is
paper after dark. The main colour is navy on light and sky on dark.

### Light

| token | value | use |
|---|---|---|
| ground | `#F5F5F3` | page |
| sheet | `#FFFFFF` | panels, cards |
| soft | `#ECECE8` | page wash, quiet blocks |
| inset | `#F0F0EC` | insets, wells |
| ink | `#101418` | body and headings |
| ink-2 | `#3C454F` | secondary |
| ink-3 | `#5F6A75` | tertiary, metadata |
| edge | `rgba(16,20,24,.10)` | hairlines |
| edge-strong | `rgba(16,20,24,.22)` | active rules |
| edge-control | `#7E838B` | an input's 3:1 boundary |
| brand | `#0B1020` | primary press, active marks, pixels |
| link | `#1F3A63` | links and sources |
| attention | `#FF8A1F` | a status that needs the eye |
| positive | `#0B6B4F` | price down, "No reports" |

### Dark

| token | value | use |
|---|---|---|
| ground | `#0E0F11` | page |
| sheet | `#15171A` | panels, cards |
| soft | `#17191C` | page wash, quiet blocks |
| raise | `#1C1F23` | raised blocks, menus |
| ink | `#EDEDEA` | body and headings |
| ink-2 | `#A8ABB1` | secondary |
| ink-3 | `#9A9DA4` | tertiary, metadata |
| edge | `rgba(237,237,234,.10)` | hairlines |
| edge-strong | `rgba(237,237,234,.22)` | active rules |
| edge-control | `#666A70` | an input's 3:1 boundary |
| brand | `#5AA9F7` | primary press, active marks, pixels |
| link | `#5AA9F7` | links and sources |
| attention | `#FF8A1F` | a status that needs the eye |
| positive | `#5FD3A0` | price down, "No reports" |

Amber is a budget, not a scale. It appears only on a Recalled or Serious
status, the outline of "Known issues", a price that rose, an unread count and
the focus ring. It does not fill a primary press, a selected row, a card, a
chip or a heading. A selected row is a neutral grey tint. Green belongs to a
price that fell and to "No reports", never to an action or a chart.

### Shape and type

- Radii: `8px` small, `10px` controls and inputs, `12px` cards, `16px` sheets,
  `999px` presses and badges. Pixel art stays `0`.
- Type: Newsreader sets the titles, upright; Inter sets the body and labels;
  the system monospace is for code and logs only. A Newsreader title is weight
  `600`, tracking `-0.02em`, line-height `1.05`. Body `14-16px/1.55`, max
  measure `68ch`. Labels are sentence case, never tracked capitals.
- Numbers that can be compared use tabular figures.
- One surface texture only: a 24px hairline grid at 4% in empty and hero areas.
  No gradient mesh, no glow, no noise over text.
- A card rests on a hairline. A floating menu, popover or sheet may carry one
  shadow; nothing else does.
### Motion

One moment per screen. The evidence rule draws across a finding as it enters
(180ms, `cubic-bezier(.22,1,.36,1)`); everything else changes in place. Hover
and press are 120–160ms. `prefers-reduced-motion` removes the draw and the
movement, not the state.

## Rules for every surface

- Keep every existing feature, route, API call and piece of state.
- Keep user-visible copy unless it is generic or clichéd. Never add a sub-line
  under a heading, never use an em dash in site copy, never invent testimonials.
- Keep the existing test-visible labels, aria names and DOM hooks. Adapt tests
  only where they pin an obsolete presentation value.
- Newsreader is bundled with the product; do not fetch a face from a network.
- Keyboard focus must stay visible. Contrast must pass the project's existing
  thresholds (body 7:1, secondary 4.5:1 on its surface).
- Mobile: nothing below 13pt, running text at least 16pt, settings at least
  14pt. Touch targets at least 44pt.
- Prefer editing tokens and the shared stylesheet/theme over rewriting screens.
  Restructure only where the layout itself is the problem.

## Per surface

### Desktop (`kriko-ui`)

- The rail is an index: destinations with a count or state, a 2px brand
  marker on the active row, hairline dividers instead of group headings.
- The top bar is a 44px instrument strip, not a floating chrome bar.
- The home screen is a check desk: one question, a compact mode control, and
  recent checks as ruled ledger rows.
- A product is a dossier: ruled findings in an evidence gutter, sources as
  numbered footnotes, cost and insight blocks as ruled sections. No card grid.
- The composer is an inset field on the page, not a floating pill.

### Phone (`kriko-mobile-app`)

- Same tokens in all four palettes; keep the band as the identity device.
- Soft corners, ruled finding rows, tabular metadata, quieter chrome.
- The landing screen is a single question over the grid texture.
- Sheets use the same hairline hierarchy; no stacked shadows.
- Sync the native overlay's palette only where it is a constant already.

### Website (`kriko-website`)

- The home page is a dossier cover: headline, three actions, and a specimen
  evidence sheet built from real-looking findings. The desktop and phone
  pictures stay, but sit in ruled frames rather than floating cards.
- Replace uppercase tracked labels with sentence-case index labels.
- Known-problem pages: the finding rule and the evidence gutter become the
  page's structure. Keep the generated pages and their renderer in step.
- Keep the copy tests green: no sub-line under a heading, no em dash, three
  hero actions, the picture hooks the tests name.

### Extension (`extension`)

- The panel is a compact dossier page: one finding per ruled row, source hosts
  in the body face, the severity rule visible.
- The hover card is a single tear-off strip: product, one leading finding,
  source count. No nested cards.
- Options follows the same tokens and row rhythm as desktop settings.

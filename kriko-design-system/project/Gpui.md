# GPUI

The app is moving to GPUI. `gpui/theme.rs` is the whole look in one file, written against gpui 0.2.2 and compile-checked with `cargo check` together with `gpui/example.rs`. It was not run on a display, so check the visuals against the Pages group before trusting a detail.

## Restyle, do not rebuild

Keep every view, model and action the app already has. Change only how things are painted, in this order, and stop after any step with a working build:

1. Add `theme.rs`, register the three fonts at startup with `register_fonts`, and replace colour and spacing literals with the constants.
2. Rebuild the sidebar from `nav_item`, the group labels and the brand block (see Sidebar).
3. Wrap each tab in the hero: `hero(sky, height)` with the tab name as a 96px `Barlow Condensed` title and one lead line, then the existing content below it.
4. Swap controls one kind at a time: `key`, `plate`, `switch`, `tag`, `meter`, `agent_tile`.
5. Go tab by tab: Home, Run, Agents, Activity, Browse, Compare, History, Overview, Sites, Benchmark, Local LLM, Browser extension, Settings, About. Each draft in the Pages group lists what it is built from.

## What GPUI cannot paint

Checked against the gpui 0.2.2 source. The system is drawn around these limits, so do not work around them.

| CSS idea | In GPUI | What the drafts do |
| --- | --- | --- |
| `backdrop-filter: blur` | no per-element blur; only a whole-window `Blurred` appearance, not on every platform | frost is a translucent pale fill (`FROST`) over the dithered sky image, which is already soft |
| inset box-shadow | `BoxShadow` has colour, offset, blur and spread, no inset | a well is the darker `WELL` fill plus a 1px `HAIRLINE` border |
| text-shadow, filters, blend modes | not available | none used; buttons are flat fills |
| CSS `@keyframes` | none; animate with `with_animation` or by re-rendering on a timer | LED boot, scan and blink are state changes on a timer; honour reduced motion by not starting them |
| sprite sheets, `background-image` | `img()` as an absolutely positioned child | the hero is `img(sky).absolute().size_full()` with `ObjectFit::Cover` |

## From the drafts to GPUI

| Draft | GPUI |
| --- | --- |
| `.k-key` | `key(id, label)`: solid `brand` fill, `.hover(...)` to `brand-hover`, `.active(...)` to `brand-low` |
| `.k-plate` | `plate(id, label)`: flat `BEZEL_LO` fill, 1px `BEZEL_EDGE` border, `.hover(...)` to `BEZEL_HI`, `.active(...)` to `WELL` |
| `.k-led` matrix | `led_matrix(rows, colour, dot, gap)`: a flex grid of small rounded divs, lit ones get a zero-offset glow shadow |
| `.k-tag` | `tag(state, label)`: glyph and word, always both |
| `.k-meter` | `meter(value, segments)`: a `well()` holding segment divs |
| `.k-switch` | `switch(id, on)`: track `well`, knob gradient, knob is placed with `justify_end` when on |
| `.k-agent` | `agent_tile(letter_rows, icon)`: 40px `well`; pass the official icon path when supplied |
| `.k-hero` | `hero(sky, height)` |
| `.k-frost` | `frost()` |
| `.k-card` | `card()` |

## Sidebar

All four groups use one label style (11px `JetBrains Mono` capitals, `DIM`, with a chevron), never a boxed header. Every item has an icon, including Local LLM. The current item is a recessed well with `ICE` text, no side bar. A count that needs you is a small `BRAND` square with white text (Activity); a plain count is mono `DIM` text (Browse 760). The brand block is a flat `BRAND` rectangle with the white wordmark and "local product knowledge" in mono.

## Working agents rail

Every screen is three columns: sidebar 248px, main `flex_1` with `min_w_0`, rail 320px with `HAIRLINE` on its left edge and `SURFACE_1` fill. A working-agent card is a `glass` card: `agent_tile`, name and mono task line, a `tag` and the claims added, a `meter`, and the SQLite file it writes to in `DIM` mono. A card in NEEDS YOU uses the `key` gradient and holds one `plate` action. Below 1100px wide hide the rail rather than squeezing the main column.

## The tabs

| Tab | Hero | Built from | Adds beyond a reskin, confirm against the current build |
| --- | --- | --- | --- |
| Home | hero, with `frost` check box | totals cards, callout, table | frost check box, one waiting-run callout |
| Run | dim | phase stepper, rows-written card, decision card, feed | stepper with live phase in `BRAND`, per-table SQLite writes, decision card |
| History | dim | search, table, agent tile stack | tile stack, claims written per run |
| Compare | dim | text tabs, attribute table, callout | trust tag per cell, DIFFERS marker, no winner |
| Browser extension | dim | numbered steps, pairing code, switches | pairing code block |
| Overview | dim | schema chain, packs with switches, support bar, gaps, empty state | schema chain with row counts, coverage gaps |
| Browse | dim | table tabs, mono filter, row drawer | table tabs, key-value row drawer |
| Sites | dim | add field, table with claims per site | claims-from-site count |
| Activity | dim | needs-you callout, write feed | callout mirrors the nav badge, "wrote N claims" rows |
| Agents | dim | table plus detail card | detail card |
| Benchmark | dim | wide run plate, LED bars | extraction metrics per agent, previous runs |
| Local LLM | wide, with `frost` test box | model list with meters, memory, switches | frost test box |
| Settings | dim | grouped rows | Store group (location, compact, export), danger group alone |
| About | hero, with the wordmark | key-value rows | none |

## State and trust words

Process: LIVE or READING, NEEDS YOU, QUEUED, DONE, BLOCKED. Claim trust: BACKED, DISPUTED, NO EVIDENCE. Every one is a word with a glyph; never a colour alone. Trust describes the evidence behind a claim. The app produces knowledge and never recommends, rates, ranks or highlights a best product, so there is no verdict type, no winner styling and no confidence figure about a product.

## Fonts and images

Register `Barlow Condensed` (600, 700), `DM Sans` (400, 600) and `JetBrains Mono` (400, 600) as `.ttf` files with `register_fonts`. Ship the sky PNGs from `assets/Sky` with the app. Agent icons come from the vendors' official files in `assets/Agents` and are drawn with `img()` at 24px; there are none yet, so the LED monogram shows.

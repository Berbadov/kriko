# Kriko for GPUI

The desktop app, rebuilt on the Kriko design system with GPUI 0.2.2, from the
three reference screens (Activity, History, Settings). The browser extension
stays TypeScript and is untouched by this crate; the desktop window is Rust
and GPUI only.

Run it:

```
cargo run --release
```

Everything it draws — the three fonts, the nav icons, the dithered sky images,
the wordmark — is embedded in the binary with `include_bytes!`, so the exe
runs from any working directory with no asset paths to install.

## Layout

- `src/theme.rs` — the whole look: colour tokens, shadows, and the small
  builders (key, plate, well, LED matrix, tag, verdict, meter, switch, agent
  tile, hero, frost, input, keycap, badge, titlebar). Written against only
  the primitives GPUI has: fills, gradients, 1px borders, outer shadows,
  images, SVG alpha masks. No backdrop blur, no inset shadows, no text-shadow.
- `src/dock.rs` — the live actions bar: the needs-you requests with their
  answering keys, the working-now lanes, the feed, and the reply field.
- `src/app.rs` — the shell: the sidebar (brand block, nav groups, the
  needs-you badge on Activity), the hero with the page head, keyboard
  actions, and the text fields.
- `src/data.rs` — the sample data (nav, checks, feed, agents, knowledge,
  sites, packs, models, benchmarks). Screens read everything from here.
- `src/screens/*` — one file per tab, each a function over the shared
  `Kriko` state; every change goes through `cx.listener`, so the app
  re-renders from one place.

## The window and the dock

The system titlebar is gone (`appears_transparent`); the app draws its own
merged strip: the mark, the app name and the current crumb drag the window,
and minimize / restore / close sit on the right as Kriko-style wells. The
restore icon flips to the maximize icon with the window state.

The live actions dock is the right-hand bar, on every tab (the LIVE ON/OFF
toggle in the titlebar collapses it): needs-you requests each carry their
answer key (Sign in, Allow, Approve), the working lanes show live meters,
and the reply field at the bottom posts straight into the feed.

## The screens

The three reference screens are built one-to-one:

| Screen | What is on it |
| --- | --- |
| Activity | the needs-you callout (tag, two lines, "Open agents" key), the filter input, the TODAY feed (time, text, kind tag per row) |
| History | search input with the verdict/pack filter plates, the checks table (check, verdict chip, confidence meter, agent tiles, took, when), pagination with Previous/Next |
| Settings | 2x2 glass cards: General and Shortcuts left, Privacy and Danger zone right; switches, `~/.kriko` chip, ctrl+N/K/B keycaps, the two-step erase |

The rest of the rail follows the same system: Home (totals, waiting callout,
latest checks, frost start box on the hero), Run (phase stepper, agent lanes,
decision card, feed), Browser extension (steps, pairing code, switches),
Overview (totals, packs with switches, support, gaps), Browse (table plus the
evidence drawer), Sites (add field, trust grades), Benchmark (wide run plate,
LED bars), About.

Compare and Local LLM are the workbenches, and carry the most:

- **Compare** — named drafts (new / save / delete), four pick-a-check slots,
  the answer slab said from the lined-up columns, the specifications and the
  known risks cell by cell (DIFFERS chips, BACKED/DISPUTED trust icons,
  MINOR/SERIOUS/CRITICAL severity chips, one detail row open at a time), a
  drawing board over the shortlist (pen strokes and pinned notes stored as
  fractions, so a mark stays on its column through a resize; undo, clear,
  close), and follow-up questions: type one or press a suggestion, and the
  agent answers while you keep reading (the answer arrives on a timer, the
  way a real agent run would).
- **Local LLM** — the server card (address, search service, the LLM picker,
  the wait timeout), the model table with parameters, quantization, context
  window, VRAM fit status and tok/s meters, the tuning card (temperature,
  max tokens, GPU layers, auto unload, CPU fallback), the GPU memory card,
  and the one-tap model test that runs a grounding pass and reports what it
  proved.
- **Agents** — the table carries last-seen and run counts; the detail card
  carries the MCP port chip, latency, the allowed-in-run switch, per-tool
  permissions (read pages, take part in Run, answer questions) and a
  reconnect key.

Setting `KRIKO_VERIFY=compare|risks|local|agents` seeds one page's state at
startup (tab, board with strokes and a note, open sections, finished test)
so it can be captured without driving the mouse on a busy desktop.

## Motion

The design system's four animations all run, and Reduce motion (Settings)
freezes every one of them:

- **Boot** — live tags' LED dots wake with the staggered k-boot flicker.
- **Blink** — needs-you tags pulse; a live meter's leading segment pulses
  while a run is in flight.
- **The switch knob** slides through the --ease-mech overshoot; flipping it
  remounts the knob and the slide replays from the other side.
- **The segmented thumb** slides the same way when a view is picked.

GPUI has no keyframes, so each animation rides `with_animation` on an element
whose id carries the state it depends on — change the state, the element
remounts, the animation replays. The overshoot is applied inside the
animator (an easing function must stay within 0.0..=1.0 or the dev build's
assert fires).

## Installers

One command builds everything a user can install:

```
powershell -ExecutionPolicy Bypass -File package.ps1
```

Under `builds/` it leaves:

- `kriko-0.11.0-x86_64.msi` — the installer: Start-menu and desktop
  shortcuts, the Kriko icon, a PATH entry, upgrade-aware (a newer MSI
  refuses to downgrade over itself).
- `kriko-0.11.0-win64-portable.zip` — the single exe; everything it draws
  (fonts, icons, sky images) is embedded, so it runs from anywhere.

The MSI step needs the WiX 3 toolset (`candle`/`light`). If it is not on
PATH, pass its folder: `.\package.ps1 -WixBin C:\path	o\wix314`. The
exe carries the brand icon via `build.rs` (winresource), so the taskbar and
shortcuts show the mark without any extra files.

The icon (`assets/kriko.ico`) is the white K mark on the flat brand blue
`#1f4fff`, on a smooth rounded square - no sharp corners - at every size
from 16 to 256 px. It is the one file the exe and the installer both read,
so replacing it and re-running `package.ps1` updates the taskbar, the
shortcuts and Add/Remove Programs in one go.

## Interactions

- Every nav item switches tabs; Home's "Start check" goes to Run, Activity's
  "Open agents" to Agents, the callouts lead where they promise.
- The text fields take focus on click, type, backspace, and blink a caret;
  Reduce motion (Settings) stops the blink.
- History's search and filters narrow the rows live; the plates cycle
  verdict and pack; pagination pages through the matches.
- The switches toggle real state (packs, models, agents, privacy).
- Ctrl+N / Ctrl+K / Ctrl+B are bound app-wide, matching the Shortcuts card.
- The danger zone asks twice, then shows what was removed and links to
  Browse to rebuild.

## Fonts and images

`assets/fonts` holds Barlow Condensed 600/700, DM Sans 400/600 and JetBrains
Mono 400/600 — the three faces of the design — registered at startup by
`theme::register_fonts` under app-scoped family names (`Kriko Display`,
`Kriko Sans`, `Kriko Mono`). The scoped names matter: a machine
with, say, a system "Barlow" installed would otherwise shadow the embedded
face. The hero sky is the dithered band (`sky-dim`, `sky-hero`, `sky-wide`,
loaded through `Resource::Embedded`, never through a path or URI) over a
matching gradient in `theme::hero`, so the fades into the titlebar above
and the content below stay smooth; nav icons are 24x24 stroke SVGs tinted
by `text_color` at 18px.

A stderr logger is installed at startup because GPUI reports asset and font
failures through the `log` crate; without a logger those failures are silent
(and they were: two shipped that way and were only found by logging).

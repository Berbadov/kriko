> TL;DR (archived 2026-09-25): Design (2026-09-14, unimplemented, B113) for extension↔app
harmony: audit finds visual convergence already happened by copy (app default theme *is* the
extension look; 2 shared token names of 66; severity inks identical, fills differ; one real
algorithmic split: `claims`→`risks` rename). Fix in 4 phases: subtract (delete dead CSS,
rename), generated single-owner palette with staleness gate, derived severity in both, document
legitimate differences. Components/runtime sharing explicitly rejected.

# Extension and app as one system — design

**Status:** design, nothing implemented. Filed as backlog **B113**. **Date:** 2026-09-14. **Prompted by:** *"Harmony and compatibility between the web extension and the app. Both visually and algorithmically. This is very important."*

## 1. What is actually true today

Pre-read assumption (two drifted design systems needing reconciliation) is **wrong**, and reality changes the build:

### The visual convergence already happened — by copy

`ui/src/styles/themes/panel.css`: *ported from `extension/hover_lite/hover_lite.css` (the **live** stylesheet); `extension/colors_and_type.css` is a cream/lemon system nothing loads, and the lemonade theme was built from it by mistake.* The app default *is* the extension look. Done once, with nothing keeping it done.

### The two files share two token names out of sixty-six

App 38 tokens, extension 28; only `--accent`, `--font-mono` in both — one palette, two names.

### The translation between them exists — in a comment

`panel.css` annotates every grey with the extension's name (`--n-0: #0a0b0d; /* --bg-base */`, …); all ten map, all ten values still agree pair-by-pair. **Not divergence to repair but a fork that hasn't drifted**, mapping held in an unread comment — the repo's recurring failure (stale `SIBLING_CODE_FAMILIES`, `_MAKE_MAP`, site words in `extension/`, now the palette): hand-maintained correspondence, correct on the day written. Build the mechanism **now, while agreement makes the change a provable no-op**.

### Severity: same intent, two derivations

Inks identical (`#f0565b`, `#e2933f`, `#46b48c`); app fills hand-mixed opaque (`--high-soft: #2a1719`), extension derived (`rgba(240,86,91,0.10)` + `0.30` border). Extension wins (a fourth severity costs one value vs three hand-mixes); app also lacks any border token — a real visual gap, not naming.

### The one genuine algorithmic divergence: `claims` become `risks`

`extension/background.js:595` renames at its boundary; every downstream line (`risk.severity`, badge counts) speaks the new word. Zero gain; shared components would translate forever; "risk" bug reports need a mental hop to the `claims` table (B119 carries it). The algorithmic half of the ask is one word.

### What is *correctly* divergent, and must stay so

`local_panel` (damage silhouette, equipment list) — reader's own page data that **never reaches the engine** (absent from `/api/analyze` on purpose; the engine must not gain a damage-silhouette schema). Don't "harmonise" it away; *say* it in the panel instead of moving data.

## 2. What the problem actually is

1. One palette, two vocabularies, no keeping-mechanism (correct today, uncaught tomorrow). 2. Hand-mixed vs derived severity (fill can disagree while inks agree). 3. One row, two names (`claims`/`risks`). 4. Dead 172-line `colors_and_type.css` still in tree (unloaded, not in `SHIPPED`, already misled one theme effort). Everything else is already shared (engine, store, adapters, `local_panel` contract).

## 3. Principles for the fix

Shared thing = data with one owner (adapters, `local_panel`, pack vocab precedent) | person-maintained correspondence = pending bug (agreement must be *made* + failure on drift) | committed output + staleness gate is the running pattern (`src/app/web/static/` + `tools/gate.sh` — generated tokens inherit the discipline free) | extension gains no build step (static files Chrome loads; generation in-repo, output committed, like the frontend bundle) | no pack vocabulary in either client (both tests stay).

## 4. Proposal

Four shippable-alone phases, each leaving the tree better:

### Phase 0 — subtract (no mechanism yet)

Delete `extension/colors_and_type.css`; rename extension `risks`→`claims` (`background.js` + consumers + naming tests) before anything shares code.

### Phase 1 — one palette, generated

Comment becomes mechanism: `panel.css` is **source** (app default theme, already carries the mapping; themes are picked in the app — meaningless in a content script). Generator (`tools/tokens.py` or a `ui` build step) reads it, emits the extension's `:host` block under its alias names from an explicit `n-0 → bg-base` table **living in the generator, not a comment**; committed between markers (or `@import`ed generated file — settle on shadow-root survivability when writing). `tools/gate.sh` gains regenerate + `git diff --exit-code`. **First run must be no-diff** (values agree today) — the one-time proof the mapping transcribed correctly.

### Phase 2 — severity derived, in both

Extension's shape wins: one ink per severity, surface/border via `color-mix()`/alpha. App gains its missing border token (visual improvement + structural fix).

### Phase 3 — say what is legitimately different

App's lookup view carries a line: the extension shows damage/equipment blocks read from the listing page that never reach the engine — comparison teaches the rule instead of suggesting a bug.

## 5. Deliberately not doing

No shared components (Svelte-in-content-script = framework bundle per matched page + per-site CSP fights; ~1,200 lines CSS + template strings is the right size) | no runtime token serving (palette changes with the repo = committed artefact; runtime fetch buys unstyled-panel flash for nothing; `local_panel` is served because it's *pack* data) | no `local_panel`-in-engine (G6 violation in UX clothing) | no more copying (the copy is the disease).

## 6. The one open decision

**Which side owns the palette.** Design says app (themes chosen there; mapping already there). Counter: extension stylesheet is the *live*, reader-visible original. Either way the generator changes one line — settle cheaply before Phase 1.

## 7. Relationship to the other filed ideas

**B115** (agents author adapters) builds on this (panel contract — pack data vs palette vs client-owned — must settle first). **B119** (glossary) pins `claims` the moment Phase 0's rename lands. **B114** (Web Store) is distribution-orthogonal (generated tokens committed either way).

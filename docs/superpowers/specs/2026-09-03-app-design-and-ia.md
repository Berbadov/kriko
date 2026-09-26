> TL;DR (archived 2026-09-25): Design (2026-09-03) turning the rewritten frontend into a
product, frontend-only (every feature verified against existing endpoints): tokenised design
system (4 stylesheets + colour-literal guard), verb-grouped nav rail, editorial verdict report
+ print, staged describe-it form (`humanize`), first-run Welcome, client-side compare.
Phases 0–6; no Python diff, no ranking change, no webfonts/prices.

# The app as a product — design system, information architecture, and four features

**Date:** 2026-09-03 · **Branch:** `feat/knowledge-engine-pivot` (or cut from it) · **Baseline:** v0.2.5 — `2026-09-01` phases 0–5 landed, installers build, success path unconfirmed by a reader (B52) · **Goal alignment:** G6 + *web-first minimal slice*

## Problem

The 2026-09-01 rewrite fixed operability, not product — reproducing one level up its own named anti-pattern ("every capability a tab, none a workflow"). In `ui/` as-shipped: flat capability-shaped nav (buyer 1 tab, author 7 undifferentiated); buyer flow = one page with `<hr/>` (link-paste and ~15 hostile `snake_case` inputs, equal weight); report = 86 lines of `div.card` (no verdict, no summary, no print exit; raw `relevance 0.2700` in author mode); no first run (empty store B52 — knowledge engine that knows nothing); `Dashboard` (5 counts + History-duplicate activity table, answers nothing); stylesheet without scales (501-line `app.css`, 11 flat colours, duplicate `.row`/`.badge`, 2 hardcoded hexes breaking light mode, no elevation/focus/motion); `History` links dropping `mode`.

## What is worth keeping

Four load-bearing properties: (1) **pack-agnostic DOM** (runtime identity-keys/vocabulary forms; `test_ui_contains_no_pack_vocabulary` greps `ui/src/**/*.{ts,svelte}` — prettier labels that hardcode keys fail it); (2) **mode as projection** (`mode.ts`, no mode-carrying requests — redesign leans in, no parallel structure); (3) **long work is a row** (`follow()` SSE-with-fallback reused verbatim for onboarding); (4) **classes as primitive** (no wrapper components — stays; Decision 2).

## Non-goals

No new endpoints, **no Python diff** (`src/kriko/` diff = misread); no ranking/claim-selection change (B36 untouched — the verdict makes weak selection *more* visible, honestly, and that is not a licence to fix it); no cost/repair estimates (`Claim` has no price field — inventing one is fabrication); no webfonts (offline local-first; editorial via measure/leading/hierarchy on system stack); no mobile; no auth/hosting/signing (unchanged).

## Decisions

### Decision 1 — every feature is frontend-only, and that is verified, not hoped

Each feature checked against `ui/src/lib/api.ts`: first run (`status/packUpdates/updatePacks/installPack/follow`), verdict+print (derived from rendered `LookupResult` + stylesheet), describe-it (`packs/kinds/identityKeys/vocabulary/subjects/subject/lookup`), compare (`history/getLookup` ×2) — all exist. Lands in `ui/` + committed `src/app/web/static/`; pytest keeps invariants green.

### Decision 2 — components only where there is logic; classes stay the primitive

No `<Button>/<Field>/<Card>/<Badge>` wrappers (indirection over the consistent class idiom; prop/CSS drift surface). New components own state/branching only: `Sidebar`, `NavGroup`, `Verdict`, `EmptyState`, `Describe`, `Welcome`, `Compare`.

### Decision 3 — one stylesheet becomes four, with real scales

`tokens.css` (neutral ramp `--n-0…9`, one accent, 3 severities, spacing `--s-1…7` = 4–48, type 12–28 + line-heights, radii, focus, motion) / `base.css` (reset, body, headings, links, `:focus-visible`, reduced-motion) / `components.css` (existing idiom deduplicated) / `print.css` (report as paper). Both themes derive from the ramp (light mode stops forgetting severities); stray hexes tokenised; `.row`/`.badge` unified. The ramp is the mechanism: next panel already has a value (no literals).

### Decision 4 — the shell is a grouped rail, and the groups are verbs

`CHECK` (New check · History · Compare) / `KNOWLEDGE` (Overview · Subjects · Coverage · Health) / `SYSTEM` (Packs · Runs). Buyer sees CHECK only; author all three. `authorOnly` explained-switch preserved. Moves: `Dashboard`→`Overview` control room (store counts, open gaps, running jobs, pending updates, weakest teaser — each linking onward; activity table dropped as History-duplicate; test = "answers what to work on"); `Health` SYSTEM→KNOWLEDGE (claim quality, not machine); `History` promoted to destination (keeps contextual rail; `toHash`→`hashWith({mode})` bug fix); `Browse`→`Subjects` (thing, not gesture).

### Decision 5 — the report is the one editorial surface

Shell = instrument (dense, quiet, tabular numerals); report = document (read + printed). `Verdict.svelte`: one plain sentence, severity bar, counts (`n risks · m serious · k handled`), the honest `confidenceNote`/`emptyReason` lines, **Print this**. Cards: severity left-rule, ~68ch measure, "Ask the seller" as distinct block, author extras behind per-card disclosure (no more `relevance 0.2700` over advice). `print.css`: rail/controls hidden, all `<details>` expanded (evidence included — the handover's reason), subject/date/confidence header, black on white.

### Decision 6 — the describe-it path is staged, and its labels are a string transform

Replaces below-`<hr/>`: (1) pack+kind (auto-skipped when single — the common cars-only case); (2) search known subjects (pick fills identity from `subject(id)`, collapses to chip + *change*); (3) only still-empty required identity keys, then optional context. Labels via generic `humanize(key)` (underscores→spaces + capitalise) in `lib/fields.ts` — a transform over API-supplied values, not a vocabulary table (invariant stays green; unit-tested key-free). Missing-required behaviour kept. Author "page fields" disclosure moves below (debugging affordance, not a step).

### Decision 7 — first run is a route, gated on an empty store

`Welcome.svelte` at `#/welcome`; `App.svelte` navigates once when `status().packs === 0` on default route. States empty store plainly; offers index (`packUpdates` → `updatePacks` via `follow()`, failure visible); index-unreachable ⇒ reason + local `.kpack` picker; dismissible ("later" — an unleavable first-run is a trap). Closes B52 via the index-offer route, not bundled `cars.kpack` (binary bloat + knowledge pinned to release cadence vs CLAUDE.md's two clocks).

### Decision 8 — compare is client-side, over two stored lookups

`Compare.svelte` at `#/compare/:idA/:idB` (or pickers from `history()`): two columns aligned by `claimKey`, rows marked A/B/both with per-side severity; one-sided rows first (the interesting ones). No endpoint (two `getLookup`s + arithmetic). Entries: History-row affordance + report "compare with…".

## Architecture

`ui/src/`: `styles/{tokens,base,components,print}.css` NEW (`app.css` DELETED); `lib/shell/{Sidebar,NavGroup}.svelte`, `Verdict/EmptyState/Describe/fields(+humanize)/History/Report/ClaimCard` (severity rule, author disclosure); `routes/{Welcome,Compare,Overview} + Subjects` (Browse/Dashboard DELETED/RENAMED); `App.svelte` (rail, workspace, first-run gate, routes); rebuilt committed bundle. Deps unchanged (`ui/`→`app/` over HTTP; no Python touched).

## Implementation phases

Bundle rebuilt + both suites green per phase (local obligation — `ci.yml` paused to `workflow_dispatch`; `desktop.yml` rebuilds rather than compares). **0** design system (split, ramp, tokenise strays, dedupe, focus/motion, both themes × every screen; visual change only where broken). **1** shell (rail, groups, mode in footer, Overview/Subjects, regrouped Health, History route, hash fix; renamed tests, not silent deletes). **2** report (Verdict, cards, print, measure; verdict cases: zero/all-low/mixed+handled/NOT_MATCHED/identified-empty). **3** Check (`Describe`, `humanize`+test, link hero, disclosure moved). **4** first run (Welcome, `packs===0` gate, unreachable fallback, dismissal — all three tested). **5** compare (component, pickers, entry points, one-sided alignment test). **6** close-out (bundle, pytest, ARCHITECTURE reading map, CLAUDE.md table, B52 marked, `done.md` with date+commit).

## Testing

Vitest per phase (new components; renamed routes get renamed tests; `report`/`fields` cases above) | pytest pre-push (`.venv/bin/python -m pytest -q`; `test_ui_contains_no_pack_vocabulary` — Decision 6 is the risk — + `test_no_hand_written_frontend_survives`) | stale-bundle check hand-run (`gh workflow run ci.yml`; Phase 6 before tag) | reader test (installer someone can double-click, per app-first phase — Phase 6 ends tagged, not merged).

## Risks

Verdict spotlights weak selection ("3 serious" over generic warning-lights reads worse than a flat list — correct; B36 exists; verdict quotes coverage+method beside counts, never bare numbers) | `humanize` one grep from invariant failure (unit test asserts key-free + why-comment) | Phase 0 touches every screen (all nine destinations opened in both themes before done).

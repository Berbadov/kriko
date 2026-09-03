# The app as a product — design system, information architecture, and four features

**Date:** 2026-09-03
**Branch:** `feat/knowledge-engine-pivot` (or a branch cut from it)
**Baseline:** v0.2.5 — phases 0–5 of `2026-09-01-standalone-app-ui-design.md` all landed;
installers build; the success path is still unconfirmed by a reader (B52)
**Goal alignment:** G6, and its *web-first minimal slice* constraint — every operation
operable and inspectable from the app, with a visible result, error and durable status

## Problem

The 2026-09-01 rewrite replaced a 443-line `app.js` with a router, typed client, job
rows and a mode projection. It fixed operability. It did not make a product, and the
shape it shipped reproduces — one level up — the anti-pattern that spec itself named:
*"every backend capability has a tab, and none of them is a workflow."*

Concretely, in `ui/` as of this spec:

- **The nav is flat and capability-shaped.** Buyer mode is one tab. Author mode is seven
  undifferentiated tabs — `Check, Dashboard, Browse, Coverage, Jobs, Health, Packs` —
  with no grouping to say which of them is *using* knowledge, which is *growing* it, and
  which is the machine. Nine destinations in a single row teaches the reader nothing
  about what the app is.
- **The buyer's flow is one page with an `<hr />` in the middle.** `Check.svelte` puts
  paste-a-link above the rule and, below it, a heading reading "No link? Describe it
  instead" followed by roughly fifteen bare text inputs labelled with raw pack keys in
  `snake_case`. The primary path and the fallback carry equal visual weight, and the
  fallback is hostile.
- **The report — the thing the whole engine exists to produce — is 86 lines rendering a
  stack of `div.card`.** There is no verdict, no summary a reader can act on in one
  glance, and no exit: nothing to print or carry to a seller. In author mode a raw
  `relevance 0.2700` sits above the advice.
- **There is no first run.** A fresh install has an empty store (B52). The app answers
  nothing until the reader finds *Packs → Check for updates* on their own. The first
  impression of a knowledge engine is that it knows nothing.
- **`Dashboard` earns nothing.** Five counts and a "recent analysis activity" table that
  duplicates History. It is the author's landing page and it does not answer "what
  should I work on".
- **The stylesheet has no scales.** `ui/src/app.css` is 501 lines, eleven colour
  variables and no spacing or type scale. `.row` and `.badge` are each defined twice.
  Two colours are hardcoded outside the theme (`#e5e5e5` in `.history`, `#b3261e` in
  `tr.concern`), so light mode has holes. Nothing expresses elevation, focus or motion.
- **`History.svelte` links with bare `toHash`**, dropping the `mode` query — a reader in
  author mode who clicks a recent result is silently returned to buyer mode.

## What is worth keeping

Four properties are load-bearing and this work preserves all of them.

1. **Pack-agnosticism reaches into the DOM.** Forms are built from
   `/api/identity-keys/{pack_id}` and `/api/packs/{pack_id}/vocabulary` at runtime, and
   `test_ui_contains_no_pack_vocabulary` (`src/app/pipeline/tests/test_repo_invariants.py`)
   greps `ui/src/**/*.{ts,svelte}` for pack vocabulary. Any redesign that "just writes
   nicer labels" fails that test and breaks G6 at the HTTP boundary.
2. **Mode is a projection, not a second API.** `mode.ts` renders one payload two ways; no
   request carries a mode and no endpoint branches on one. The redesign leans harder on
   this rather than inventing parallel structure.
3. **Long work is a row.** `follow()` in `jobs.ts` gives SSE-with-polling-fallback over a
   durable job row. Onboarding reuses it verbatim.
4. **CSS classes are the primitive.** The codebase styles by class, not by wrapper
   component. That stays; see Decision 2.

## Non-goals

- **No new endpoints and no Python diff.** Every feature below is served by an endpoint
  that already exists (see Decision 1). A diff to `src/kriko/` is a sign something went
  wrong.
- **No change to ranking or claim selection.** B36 and the product principle's open work
  are untouched. This spec makes weak selection *more* visible, not less — that is the
  point of a verdict, and it is not a licence to fix selection here.
- **No cost or repair-price estimate.** `Claim` carries no price field and neither does
  the payload; a verdict that invented one would be a fabrication. The verdict is built
  from severity counts, match method, coverage and the reader's own handled marks.
- **No webfonts.** This is an offline local-first desktop app. A `fonts.googleapis.com`
  stylesheet renders the app unstyled with no network. "Editorial" comes from measure,
  leading and hierarchy on the system stack.
- **No mobile layout.** Desktop and desktop-sized browser only, as before.
- **No auth, no remote hosting, no signing.** Unchanged from the 2026-09-01 non-goals.

## Decisions

### Decision 1 — every feature is frontend-only, and that is verified, not hoped

Each of the four features was checked against `ui/src/lib/api.ts` before being accepted
into scope:

| Feature | Endpoints it needs | Already exist |
|---|---|---|
| First run | `status()` → `packs === 0`; `packUpdates()`; `updatePacks()`; `installPack(file)`; `follow(job_id)` | yes |
| Report verdict + print | none — derived from the `LookupResult` already rendered; print is a stylesheet | yes |
| Progressive describe-it | `packs()`, `kinds()`, `identityKeys()`, `vocabulary()`, `subjects(q)`, `subject(id)`, `lookup()` | yes |
| Compare two checks | `history()`, `getLookup(id)` × 2 | yes |

Consequence: the whole of this work lands in `ui/` plus the committed build output under
`src/app/web/static/`. No layer is crossed, no import is added, and the pytest suite's
role is to keep the invariants green rather than to cover new behaviour.

### Decision 2 — components only where there is logic; classes stay the primitive

The temptation in a design-system pass is a primitive library — `<Button>`, `<Field>`,
`<Card>`, `<Badge>`. It is rejected. Those wrappers would add indirection and earn
nothing over the class-based styling the codebase already uses consistently, and every
one of them is a place for a prop to drift from the CSS.

New components are created only where there is state or branching to own:
`Sidebar.svelte`, `NavGroup.svelte`, `Verdict.svelte`, `EmptyState.svelte`,
`Describe.svelte`, `Welcome.svelte`, `Compare.svelte`.

### Decision 3 — one stylesheet becomes four, with real scales

`ui/src/app.css` is replaced by `ui/src/styles/`:

| File | Owns |
|---|---|
| `tokens.css` | neutral ramp `--n-0…--n-9`, one accent, three severity colours, spacing `--s-1…--s-7` (4, 8, 12, 16, 24, 32, 48), type scale (12/13/15/17/21/28 with paired line-heights), radii, focus ring, motion durations |
| `base.css` | reset, `body`, headings, links, `:focus-visible`, `prefers-reduced-motion` |
| `components.css` | button, field, card, badge, table, state, stat classes — the existing idiom, deduplicated |
| `print.css` | the report as a page handed to a seller |

Both themes derive from the same ramp, so light mode stops being an afterthought that
forgets `--high`/`--medium`/`--low`. The two hardcoded hexes become tokens. The
duplicate `.row` and `.badge` rules collapse to one each.

The neutral ramp is the mechanism, not a preference: today's eleven flat variables are
why a new surface has no defined background and someone reaches for a literal. A ramp
means the next panel already has a value to use.

### Decision 4 — the shell is a grouped rail, and the groups are verbs

```
CHECK          New check · History · Compare
KNOWLEDGE      Overview · Subjects · Coverage · Health
SYSTEM         Packs · Runs
```

Buyer mode renders the `CHECK` group only. Author mode renders all three. The existing
`authorOnly` explanation in `App.svelte` — an author view reached by a buyer is
*explained* and the switch offered, never blank — is preserved as-is; a grouped rail
does not change that a link can be pasted.

Three deliberate moves inside the grouping:

- **`Dashboard` becomes `Overview`, and becomes a control room.** Store counts, open gap
  count, running jobs, packs with an update waiting, and a weakest-claims teaser — each
  linking into its own section. Its current "recent analysis activity" table is dropped
  because `History` already is that list, better. The test for this page is whether it
  answers "what should I work on"; five counts did not.
- **`Health` moves from SYSTEM into KNOWLEDGE.** It is about claim quality, not about the
  machine.
- **`History` is promoted from a sidebar-only panel to a destination**, and keeps its
  contextual rail on `check` and `result` where a past answer is relevant. Its links move
  from `toHash` to `hashWith({ mode })`, fixing the dropped-mode bug.

`Browse` is renamed `Subjects` — it is a subject list, and "browse" names a gesture
rather than a thing.

### Decision 5 — the report is the one editorial surface

The shell is an instrument: dense, quiet, tabular numerals, restrained motion. The report
is a document, because it is the only screen a reader *reads* rather than operates, and
the only one they print.

`Verdict.svelte` sits above the claims and carries, in this order: one plain sentence of
what was found; a severity distribution bar; the counts (`n known risks · m serious · k
handled`); the honesty line that `confidenceNote()` and `emptyReason()` in `report.ts`
already write well; and the primary action, **Print this**.

The claim card gains severity as a left rule, body text at a ~68ch measure with looser
leading than the shell, and "Ask the seller" as a visually distinct block rather than a
grey paragraph. Author extras move from an always-on `meta` line into a per-card
disclosure, so author mode stops putting `relevance 0.2700` above the advice.

`print.css` hides the rail and every control, expands all `<details>` — sources included,
since evidence is the reason to hand the page over — prints subject, date and match
confidence in a header, and renders black on white.

### Decision 6 — the describe-it path is staged, and its labels are a string transform

`Describe.svelte` replaces the region below the `<hr />`:

1. **Pack and kind**, auto-skipped when there is one of each. That is the common case on
   an install with only `cars` enabled, and skipping it removes two selects from the
   reader's first view.
2. **Search a subject the packs already know.** Picking one fills identity from
   `subject(id)` and collapses the step to a chip with *change*.
3. **Only the still-empty required identity keys**, then optional context terms.

Labels are produced by a generic `humanize(key)` — `key.replace(/_/g, " ")` plus a
leading capital. This is a string transform over a value the API supplied, not a
vocabulary table, so `test_ui_contains_no_pack_vocabulary` stays green while the reader
stops reading `snake_case` in a form. `humanize` lives in `ui/src/lib/fields.ts` beside
`collect` and is unit-tested there.

The existing missing-required behaviour (submit disabled, the missing list shown inline)
is kept — it is already correct.

Author mode's "Page fields, as scraped" disclosure moves below the staged form, where it
belongs: it is a debugging affordance, not a step.

### Decision 7 — first run is a route, gated on an empty store

`Welcome.svelte` at `#/welcome`. `App.svelte` reads `status()` on boot and, when
`packs === 0` and the route is the default, navigates there once.

The screen states plainly that the app ships with no knowledge and offers the index:
`packUpdates()` lists what is available, one button starts `updatePacks()`, and the job
is followed with `follow()` so progress and failure are both visible. When the index is
unreachable it says why and offers the local `.kpack` picker (`installPack`). It is
dismissible — "I'll do this later" — because a first-run screen that cannot be left is a
trap, and the reader may be offline on purpose.

This closes B52's *"first run is still an empty store"* bullet by the second of the two
routes that item names — "make the first launch offer the index by itself" — rather than
by bundling `cars.kpack` into the installer, which would grow the binary and pin
knowledge to a release cadence that CLAUDE.md explicitly separates ("two update clocks,
and neither waits for the other").

### Decision 8 — compare is client-side, over two stored lookups

`Compare.svelte` at `#/compare/:idA/:idB`, and at `#/compare` with two pickers fed from
`history()`. Two columns; claims aligned by `claimKey(claim)`; each row marked present in
A, in B, or both, with its severity per side. Entry points: a compare affordance on a
History row, and *compare with…* on a report.

No endpoint is added because none is needed — two `getLookup` calls and the alignment is
arithmetic. Claims that exist on one side only are the interesting rows and sort first.

## Architecture

```
ui/src/
  styles/
    tokens.css            NEW  — ramps and scales (Decision 3)
    base.css              NEW
    components.css        NEW
    print.css             NEW  — the report as paper (Decision 5)
  app.css                 DELETED — split into the four above
  lib/
    shell/Sidebar.svelte  NEW  — the grouped rail (Decision 4)
    shell/NavGroup.svelte NEW
    Verdict.svelte        NEW  — the report's top line (Decision 5)
    EmptyState.svelte     NEW  — replaces scattered `p.state.empty`
    Describe.svelte       NEW  — the staged form (Decision 6)
    fields.ts             + humanize()
    History.svelte        mode-preserving links; usable as panel and as page
    Report.svelte         hosts Verdict; reading measure
    ClaimCard.svelte      severity rule; author extras behind a disclosure
  routes/
    Welcome.svelte        NEW  (Decision 7)
    Compare.svelte        NEW  (Decision 8)
    Overview.svelte       NEW  — replaces Dashboard.svelte (Decision 4)
    Subjects.svelte       RENAMED from Browse.svelte
    Dashboard.svelte      DELETED
    Browse.svelte         DELETED
  App.svelte              rail + workspace; first-run gate; route table
src/app/web/static/       rebuilt bundle, committed
```

Dependencies are unchanged. `ui/` talks to `app/` over HTTP and imports no Python; the
fan in CLAUDE.md is untouched; no Python file is edited by this work.

## Implementation phases

Each phase ends with both suites green and the bundle rebuilt, and during the app-first
phase that is a *local* obligation rather than a CI one. `ci.yml` — which holds both
`npm --prefix ui test` and the stale-bundle check — is paused to `workflow_dispatch`
until a Windows install opens, and `desktop.yml` rebuilds the bundle itself rather than
comparing it, so neither workflow will catch a stale `src/app/web/static/` on a push.
`npm --prefix ui run build` and its committed output are therefore part of every phase,
not a follow-up, and `pytest` runs locally before every push per CLAUDE.md.

**Phase 0 — the design system.** Split `app.css` into `styles/`, add the ramp and the
spacing/type scales, tokenise the two stray hexes, deduplicate `.row` and `.badge`, add
`:focus-visible` and `prefers-reduced-motion`, verify light and dark parity across every
existing screen. No IA change; visual change only where it was already broken.

**Phase 1 — the shell.** `Sidebar` + `NavGroup`, the three groups, the mode switch moved
to the rail footer, `Dashboard` → `Overview` as a control room, `Browse` → `Subjects`,
`Health` regrouped, `History` promoted to a route, and the `toHash` → `hashWith` fix.
`Dashboard.test.ts` and `Browse.test.ts` are replaced by `Overview.test.ts` and
`Subjects.test.ts`, not deleted silently.

**Phase 2 — the report.** `Verdict`, the claim-card rework, `print.css`, the reading
measure. `report.test.ts` grows verdict cases: zero claims, all-low, mixed with
`handled`, `NOT_MATCHED`, and identified-but-empty.

**Phase 3 — Check.** `Describe.svelte`, `humanize` in `fields.ts` with its unit test, the
hero treatment for paste-a-link, the author page-fields disclosure moved below.

**Phase 4 — first run.** `Welcome.svelte`, the `status().packs === 0` gate, the
index-unreachable fallback, the dismissal. Test covers all three: index available, index
unreachable, dismissed.

**Phase 5 — compare.** `Compare.svelte`, the two-picker entry, the History and report
entry points, the alignment tested against claims present on one side only.

**Phase 6 — close out.** Rebuild and commit the bundle, run the full pytest suite, update
`docs/ARCHITECTURE.md`'s reading map and the documentation table in `CLAUDE.md`, mark the
B52 first-run bullet done in `backlog.md`, and record the work in `done.md` with date and
commit.

## Testing

- **Vitest, per phase.** Every new component gets a test file; the two renamed routes get
  renamed tests. `report.test.ts` and `fields.test.ts` grow the cases listed above.
- **Pytest, before every push** — `.venv/bin/python -m pytest -q`, per the app-first phase
  in CLAUDE.md. The invariants that matter here and must stay green:
  `test_ui_contains_no_pack_vocabulary` (Decision 6 is the risky one) and
  `test_no_hand_written_frontend_survives`.
- **The stale-bundle comparison is hand-run for now.** It lives in the paused `ci.yml`;
  a `gh workflow run ci.yml` at the end of a phase is the cheapest way to confirm the
  committed bundle matches the source, and Phase 6 must do it before the tag.
- **The reader, at the end.** Per the app-first phase, a fix that is not in an installer
  someone can double-click is not a fix. Phase 6 ends with a tagged build, not a merged
  branch.

## Risks

- **The verdict makes weak claim selection obvious.** A prominent "3 serious" over three
  generic warning-light claims reads worse than the same three in a flat list. This is
  correct behaviour and the reason B36 exists; the mitigation is that the verdict quotes
  coverage and match method honestly beside the count, never a bare number.
- **`humanize` is one grep away from failing the invariant.** The transform is safe; a
  future "just special-case this one key" edit is not. The unit test for `humanize`
  asserts it holds no key names, and the function carries a comment saying why.
- **Phase 0 touches every screen.** A ramp swap can regress a surface nobody opens. The
  phase is not done until every one of the nine destinations has been opened in both
  themes.

# Kriko — working notes for Claude

Kriko is a local-first, open knowledge engine for manufactured products. It answers
"what is known to go wrong with *this specific one*" from installed knowledge **packs**,
and ships with `cars` as pack #1 (used cars on Sahibinden, via a Chrome extension).

The engine knows nothing about cars. Adding a product category is a data change — a new
pack directory — never an engine change. That is goal **G6** and every principle below
exists to keep it true. See `docs/USAGE.md` (operation), `docs/INTERNALS.md`
(architecture), `docs/historical/pipeline_postmortem.md` (early knowledge-pipeline
history, pre-pivot — historical only).

## TEMPORARY — the app-first phase *(2026-09-01, delete when it ends)*

Until a Windows install opens, runs an analysis, and the reader says so, the
loop is the *app*, not the suite.

**Half of this ended 2026-09-08, and was undone on 2026-09-13.** `ci.yml` was
un-paused for 1.0.0 because the audit found four reported defects that every
automated gate passed — and the answer to that is more gates running more
often. That reasoning still holds. What did not hold is the runner: this
account has no Actions minutes, so from the day it was un-paused **every CI
run failed in under fifteen seconds without ever being allocated one** — no
logs, no steps, a red tick on a commit nothing had tested. On `main` too. A
gate that is always red is not a gate; it is a thing people learn to scroll
past, which is worse than having none.

So `ci.yml` is deleted and its three jobs live in `tools/gate.sh`, verbatim,
run locally. Restoring the workflow is a `git revert` plus a billing change,
in that order — and worth doing the day either is possible, because the
audit's finding has not been answered, only relocated.

The other half stands, and it is the half with the reader in it: the phase
ends when an install they can double-click opens and works, and that has not
happened yet. Rules 1, 3 and 4 below are unchanged. Rule 2 is now about
`desktop.yml` rather than `ci.yml`.

The gate moved, it did not disappear:

1. **Run the gate locally before every push.** `tools/gate.sh` — pytest, both
   JS suites, types, and the stale-bundle check. A workflow that cannot run is
   not permission to push a broken tree; it is the reason the gate is yours.
2. **Don't block on a CI run.** Push, tag, and keep working; read the run when
   it lands. `gh run watch` in the foreground is the habit being cut.
3. **`desktop.yml` is untouched and untrimmed** — on tags, on hand-dispatch,
   and on packaging PRs. It is the only written record of how an installer is
   built, and its smoke steps are the checks that would have caught v0.2.4. Do
   not trim them for speed. It cannot get a runner either, which is why every
   installer since 0.5.0 was built by hand on the Windows host; that is a
   billing problem, not a reason to cut the recipe.
4. **Ship to the reader, not to the branch.** A fix that is not in an installer
   they can double-click is not a fix yet.

**Ending this phase** = the reader confirms a double-clicked install opens and
runs an analysis, then delete this section. `ci.yml` was restored (2026-09-08)
and then deleted (2026-09-13), once it was clear it had never once executed;
its checks are `tools/gate.sh` now. Nothing else was changed to get here.

## Task tracking

Open work lives in `backlog.md` (prioritized, with goals G1–G5 and evidence); finished
items move to `done.md` with date + commit. Check the backlog before starting work and
keep both files current — they are the single source of truth for project status.

## Product principle — what Kriko surfaces (READ THIS BEFORE TOUCHING CLAIM SELECTION)

**Where this lives now:** each pack states its own bar, in `packs/<name>/research/principle.md`
— the cars version below, and a very different one for `packs/drill/`. The engine enforces
*ranking*, never *taste*; what counts as worth surfacing is a property of the category, so
it ships as pack data. The cars principle is reproduced here because it is still the one
almost every session works against.

Kriko's value is **the config- and mileage-specific known risks a buyer cannot cheaply get
from the standard pre-purchase inspection** — what to worry about for *this* specific car,
*before* they even book the expert. Everything we show should clear that bar.

**Surface a claim when it is:**
- **Specific to this variant/config** — engine code, gearbox type (e.g. dual-clutch/automated
  manual vs torque-converter), fuel, market. Not advice that applies to any car.
- **Predictable from the listing data** (mileage, year, transmission, fuel) *without*
  inspecting the car — a known weak point or failure pattern the odometer/age implies.
- **Maintenance-interval / "unless recently done"** — items due by a km or time interval (cam
  belt, major service, clutch/wear parts on high mileage). If the listing gives no evidence the
  work was done, **the omission itself is the signal** — flag it as "due unless the ad/seller
  proves otherwise".
- **High-consequence or expensive** — structural/known-weak-point failures and costly systems
  (emissions hardware, dual-clutch/mechatronics, turbo, timing components), not cosmetic or
  trivial.

**Do NOT surface (low value — drop or heavily downrank):**
- Generic dashboard-warning-light items ("ABS light", "ESP fault") or anything true of all cars.
- Anything the standard pre-purchase mechanic inspection already catches as routine — fluid
  levels/leaks, brake-pad wear, injector bench tests, compression. Buyers already pay an expert
  for these; repeating them is noise, not signal.

The test for any candidate claim: *"Would a buyer learn this from a normal pre-purchase
inspection anyway?"* If yes, it's low value. *"Is it specific to this car's
engine/gearbox/mileage and predictable from the ad?"* If yes, it's what we exist to show.

> Status: the extraction/gating pipeline currently keeps whatever sources mention (including
> generic warning-light items), so live output does **not** yet fully reflect this principle.
> Aligning it — mileage-gated claims, explicit maintenance-interval/"not mentioned in ad"
> claims, and an "inspection already covers this" filter — is open work. Honour this principle
> in any claim-selection change.

## Scalability principle — no hardcoded car data (READ THIS BEFORE ADDING A MAKE/MODEL/CODE LIST)

Kriko must generalize to thousands of cars, not the handful onboarded today. Hardcoding
specific makes, models, engine codes, or gearbox codes as Python constants is a
**scalability bug, not a shortcut** — every hardcoded list is a manual edit someone has
to remember to make for every new car, and history here shows that edit gets forgotten
(`SIBLING_CODE_FAMILIES` going stale was Flaw 1 in `docs/design_flaws.md`; `normalize.py`'s
`_MAKE_MAP`/`_MODEL_MAP` were the same failure mode).

**Before adding a fixed list of car-specific values, ask:** can this be *derived* from the
catalog (`packs/cars/data/**/*.yaml`) instead of hand-enumerated? `catalog_code_manufacturers()`
in `packs/cars/pipeline/stoplists.py` is the reference pattern — it reads manufacturer-per-code
straight off the part YAMLs, so a new part is covered the moment its stub exists, with no
separate registration step to forget.

**Exception:** small, genuinely closed vocabularies (fuel types, transmission
technologies, a handful of spelling/abbreviation aliases) are fine as constants — this
rule is about data that grows with car *coverage*, not fixed engineering categories.

**Since the pivot there is a stronger form of this rule**, and it applies to the engine
rather than the catalog: `kriko/` may not contain a car-shaped *anything*, derived or
not. No `make`, no `engine_code`, no `fuel`. Identity keys, attribute names and gate
vocabulary are pack-declared rows. `src/kriko/tests/test_core_is_domain_free.py` walks
kriko/'s AST looking for car vocabulary in executable positions.

**And it applies to the client, which is where it hid longest.** `extension/`
is the one part of the tree no Python AST gate can read, and until 2026-09-10
it held the site's own Turkish words — damage-state names, part-name regexes,
alert thresholds — for the two blocks the panel renders from the reader's page
rather than from the engine's answer. That was `_MAKE_MAP` again, one language
further out. The words now come off the adapter's `local_panel` block, which
the client already fetches, and
`test_the_extension_speaks_no_sites_own_language` in
`src/app/pipeline/tests/test_repo_invariants.py` fails the suite on any
non-ASCII *word* in `extension/`. A lone non-ASCII character between
delimiters is a character fold — the closed-vocabulary exception above — and
stays legal; a word is vocabulary and does not.

Onboarding a new car model must never require a manual Python dict/list edit in
`packs/cars/pipeline/stoplists.py` or anywhere else — only new YAML data under `packs/cars/data/`,
ideally pipeline-generated rather than hand-authored (see `docs/USAGE.md`'s onboarding
steps). Onboarding a whole new *category* must never require an edit to `kriko/` at all.

## Generalization principle — systemic fixes only, no per-model patches

The catalog must scale to thousands of models, so **per-model fixes do not exist**:
no per-model research runs, no per-model YAML audits, no per-model spot-checks, no
one-off patches that only touch one car's row. Every fix ships as the *mechanism*
that catches the same class of problem for every current and future car. When a
problem shows up on one car, ask **"how would we catch this automatically for every
car, and how will it be fixed without a person?"** — and ship that, or cancel the
feature (see the automation principle).

The mechanism should be catalog-derived or log-derived (validation, coverage report,
telemetry, auto-remediation), never another hand-enumerated list and never a manual
step — see the scalability and automation principles below. When a per-model problem
is found, it is a *test case* for the mechanism, not a fix target. Tracked as backlog
B19 (auto-remediation loop); B2/B3's manual steps were cancelled there 2026-08-03.

## Automation principle — no human in the data path (READ THIS BEFORE ADDING A REVIEW/SIGN-OFF STEP)

Kriko runs unattended. Extraction and scraping never wait for human verification,
spot-checks, or sign-off — neither per datum nor per model. Where a value cannot be
derived automatically (from the ledger, the catalog pipeline, or a deterministic
rule), the system **fails open**: emit no claim, surface the gap in the coverage
report, and log a signal that feeds an automated pass. A manual step that "someone
should review" is a bug, not a process — the backlog's HUMAN DECISION #6/#7 were
retired this way 2026-08-03 (B17 dropped, B11 derives-or-fails-open).

One-time *policy* decisions are the only allowed human decisions — source
licensing/ToS (backlog B18, HUMAN DECISION #5), market coverage, source retirement —
never per-car or per-datum review. When a per-model problem appears, fix it with a
mechanism that runs for all models (generalization principle) or cancel the feature;
never add a human verification step to the pipeline.

## Layering principle — dependencies flow one way (READ THIS BEFORE ADDING AN IMPORT ACROSS PACKAGES)

Kriko is five packages — four Python, plus the frontend — and since the pivot
the dependencies form a fan, not a column. Each may import from what it points at, never the other way:

```
tauri/     the desktop shell — Rust, ~180 lines, owns the sidecar's lifetime
   |       and nothing else. No engine logic in Rust, ever (enforced by
   |       test_the_shell_holds_no_engine_logic).
   v
ui/        the frontend — Svelte + Vite source, built into src/app/web/static/.
           Talks to app/ over HTTP; imports no Python. Holds no pack
           vocabulary (enforced by test_repo_invariants.py).
   |
   v
app/       interfaces — cli, web dashboard, mcp server, operator TUI
           (`app/tui/`, a second client on the same HTTP API — no webview).
   |
   v
kriko/      the engine — pack store, generic lookup, ranking, research
   ^        interface. Imports NONE of the others. Knows no category.
   |
packs/      one directory per product category: data, vocabulary, trust
   |        tiers, builder, and that category's own coverage report.
   |        This is the thing a third party authors.
   v
packs/cars/pipeline/  evidence ledger + grounded extraction — turns sources into
            claims a pack can ship.

app/pipeline/        pipeline drivers — ledger_run, remediate, panel, process.
            May import packs/cars/pipeline/ and packs/. Nothing imports app/pipeline/.
```

**`kriko/` importing anything on this list is the one unforgivable violation.**
It is the load-bearing invariant of G6: the moment the engine knows what a car
is, adding a category stops being a data-only change and nobody notices until
someone attempts a second category. A pack is consumed *through the store*,
never imported. If a core module wants something from a pack, the pack should
be supplying it as a row.

**A deferred import (one written inside a function body) that points *upward* is
the smell.** It means someone hit `ImportError: partially initialized module` and
pushed the import down to runtime rather than fixing the layering. Before
2026-08-21 there were 11 of them, all pointing from `packs/cars/pipeline/` into the
now-deleted `backend/`, because `backend/tools/` held operator tooling the
pipeline needed. A deferred import pointing *downward* is fine — that is a
startup-cost decision.

The following layering checks must return nothing (tests excluded — an end-to-end test may span layers):

```bash
grep -rnE "^[[:space:]]*(from|import) (backend|app|packs|knowledge)" --include='*.py' src/kriko/  | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) (backend|app|packs)"           --include='*.py' packs/cars/pipeline/  | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) (app|app.pipeline)"                         --include='*.py' packs/      | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) backend"                    --include='*.py' src/app/   | grep -v /pipeline/ | grep -v /tests/
```

All four are enforced mechanically in `src/app/pipeline/tests/test_repo_invariants.py`, which
also ratchets the deleted `backend/` shut.

`ui/` is source, `src/app/web/static/` is committed build output. Rebuild with
`npm --prefix ui run build` and commit both; CI fails on a stale bundle. `ui/src/`
may not name a pack's identity keys — forms are built from
`/api/identity-keys/{pack_id}` and `/api/packs/{pack_id}/vocabulary` at runtime,
and `test_ui_contains_no_pack_vocabulary` enforces it.

**Long work is a row, not a request.** Research and pack builds run through
`app/web/jobs.py` (single worker, cooperative cancel) with their state in
`app.sqlite`'s `jobs` table and their handlers in `app/web/tasks.py`. A
`POST` returns a job id immediately; the log, the result and the failure all
outlive the request and the process — a row still `running` at startup is
marked `interrupted`, never left spinning. Both handlers go through the same
acceptance path MCP uses (`app/findings.py`): a claim's provenance must not
depend on which door it came in.

**The desktop shell is a supervisor, not a second engine.** `src/app/sidecar.py`
binds an OS-chosen port and prints `KRIKO_PORT <n>` as its first line of
stdout — the child picks the port because a parent that finds a free one has
already lost it by the time the child binds. `tauri/` reads that line, polls
`/api/health`, and only then shows the window; on failure it renders the
captured stderr, because a blank window is a bug. **Nothing outlives *Quit*
— but the window is not Quit.** Closing it hides it and leaves the engine
serving, because the extension talks to `EXTENSION_PORT` precisely when the
reader is on a listing page rather than in the app; a tray icon (Open, Quit)
is what ends the process, and on Windows the kill is a *tree* kill —
PyInstaller onefile re-execs, so the pid we spawned is a bootloader and its
child is what holds the image. The sidecar also ends itself when its stdin closes
(`--exit-with-parent`), which is the only belt that covers a crashed shell. An
orphan does not merely hold the store's WAL lock: on Windows it keeps its own
`.exe` mapped, and the next *installer* fails with "Error opening file for
writing: kriko-sidecar.exe" — and since the engine now survives the window,
`tauri/src-tauri/installer.nsh` is the normal path rather than a fallback: it
stops `Kriko.exe` first (whose exit closes the sidecar's stdin, the designed
way out) and `kriko-sidecar.exe` second.
The sidecar serves two sockets, the announced one and the fixed
`EXTENSION_PORT`, because a browser extension cannot be told a random port.
Pytest guards keep all of this honest without building the crate: the
handshake string and the flag must match on both sides, the extension's
hardcoded port must match the server's constant, every failure path in
`start_engine` must reach `emit_failure` (a window created hidden cannot show
an error it was only *returned*), the NSIS hook must kill the binary Tauri
actually ships, and engine vocabulary in Rust fails the suite.

**A guard that reads source can only prove a string is present.** Every one of
those is a text assertion, and on 2026-09-10 all twelve tray tests passed on a
`main.rs` that could not be parsed — three adjacent string literals with no
`concat!`, shipped in B83 and found by the first `cargo` that ever read it,
nine minutes into a hand build. `test_the_shell_is_valid_rust.py` closes the
cheap half: `rustc` on each file alone reports syntax errors before it resolves
an `extern crate`, so a parse error is an `error:` with no code while an
unresolved name is an `error[E0432]`, and the gate needs neither the crate's
dependencies nor `webkit2gtk`. It skips where there is no `rustc`, never
passes. Type errors still need the real Windows build. See
`tauri/README.md`.

**Two SQLite files, on purpose.** `~/.kriko/knowledge.sqlite` is the engine's
store; `~/.kriko/app.sqlite` (`app/web/state.py`) is the interface's own history
and settings. Interface state never goes in the engine's schema: uninstalling a
pack must not drop your history, and a history row must not affect a pack's
`content_digest`. `/api/health` reports both paths.

**Two update clocks, and neither waits for the other.** Knowledge changes
weekly; the binary rarely. Packs update through the engine — `kriko/pack/
updates.py` decides (it parses an index and compares version + `content_digest`,
refusing a republished version exactly as `packstore.install` does) and
`app/packsource.py` fetches, because the engine owns no socket. The app updates
itself through Tauri's minisign-signed updater, configured at build time by
`packaging/configure_updater.py` so a tree with no signing key still builds.
Checking is a request; installing is a job.

**And the installer carries the first-party packs**, because until 0.7.1 it
carried none: a fresh install opened onto an empty engine, and — worse — a
defect whose fix lives in a pack's *rows* could not be delivered by any release
at all. `app/bundledpacks.py` seeds at startup under three rules (missing gets
installed; newer gets installed and older never does; a failure here is never
why the app will not start), reading each artifact's identity out of the
`.kpack`'s own `packs` row rather than from its file name. Which packs the build
carries is discovered from `packs/*/pack.toml` by
`packaging/build_packs.py`, so a third one ships by existing.

If a module needs something from the layer above, it is in the wrong layer — move
the module, don't add the import. New pipeline drivers belong in `app/pipeline/`; new
interfaces in `app/`; anything category-specific in `packs/<category>/`. See
`docs/INTERNALS.md` for the diagram and
`docs/superpowers/specs/2026-08-21-codebase-organisation-design.md` for the
original reasoning.

## Documentation map

| Doc | What it's for | Status |
|-----|---------------|--------|
| `README.md` | Project overview, quickstart, supported cars | current |
| `packs/<name>/README.md` | What that pack covers, and its own product principle | current |
| `CLAUDE.md` | Principles + working rules for Claude sessions | current |
| `CONTRIBUTING.md` | Branches, commits, test gates, what CI checks | current |
| `backlog.md` / `done.md` | Task tracking — single source of truth for status | current |
| `docs/ARCHITECTURE.md` | Reading map — where to start, what each package owns | current |
| `docs/USAGE.md` | Operating the stack + growing the knowledge base | current |
| `docs/INTERNALS.md` | Mechanism-level architecture reference | current (verify details against code) |
| `docs/PACK_CONTRACT.md` | What a pack must contain, and what it may | current |
| `docs/superpowers/specs/2026-09-01-standalone-app-ui-design.md` | The UI rewrite + Tauri packaging design; phases 0–5 | current — all phases landed; installers unbuilt (B52) |
| `docs/superpowers/specs/2026-09-03-app-design-and-ia.md` | The app design system, IA and four features | current |
| `docs/superpowers/specs/2026-09-09-research-agenda-design.md` | B82: what an agent should research next, and where that ordering comes from | current — implemented 2026-09-09 (`app/agenda.py`, `2a9d82c`) |
| `docs/superpowers/specs/2026-09-09-knowledge-building-design.md` | How an installation grows its own packs: the two research planes, keys, the agenda run, provenance + undo, and the product-identity skill | current — implemented 2026-09-09 (`0ab613d`, `b945408`) |
| `tauri/README.md` | The desktop shell: launch sequence, failure surface, local build | current — built by hand on the Windows host `/mnt/c` exposes (0.5.0, 0.5.1, 0.5.2) |
| `docs/design_flaws.md` | 2026-07-04 audit; Flaws 1–4 fixed, 5–6 → backlog B13 | reference |
| `~/.claude/plans/let-s-go-with-the-eager-torvalds.md` | The G6 pivot design + phase plan | current — Phase 6 in progress |
| `docs/historical/` | Pre-part-centric era (`handover.md`, `SCAFFOLD.md`) + superseded 2026-07 designs/plans (`thoughts/`) + pre-pivot claim-quality roadmap/specs and pipeline history (`overhaul_plan.md`, `claim_relevance_plan.md`, `pipeline_postmortem.md`) | historical — do not follow |

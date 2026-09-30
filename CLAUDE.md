# Kriko — working notes for Claude

Local-first, open knowledge engine for manufactured products. Answers "what is known to go wrong with *this specific one*" from installed **packs** on any listing site; ships with `cars` as the first pack and Sahibinden as the first site adapter (via Chrome extension).

The engine knows nothing about cars. A new category is a data change — a pack directory — never an engine change (goal **G6**; every principle below keeps it true). See `docs/USAGE.md` (operation), `docs/INTERNALS.md` (architecture), `docs/historical/pipeline_postmortem.md` (pre-pivot history only).

## Doctrine — read `docs/DOCTRINE.md` before any work *(2026-09-24)*

Short form, not a substitute:

1. **Write the request down first** in the backlog, quoting the reader, with **Where** (exact screen) and **Done when** (what they can see). Read it back before any code. No "Done when", no start.
2. **Done means observed**: end result on the named screen, on `main`, on Windows where it differs.
3. **Reproduce first, then fix.** Ask outside tools for their facts; never type a list from memory.
4. **Every PR carries its proof** (quote, observation, screenshot); a second agent reviews it against the request.
5. **One area per agent, a PR the same day, merged daily** (by the reader; nothing reaches `main` without the author asking).

## TEMPORARY — app-first phase *(2026-09-01, delete when it ends)*

Until a Windows install opens, runs an analysis, and the reader says so, the loop is the *app*, not the suite. `ci.yml` was un-paused 2026-09-08 (audit: four defects passed every gate → more gates, more often), then deleted 2026-09-13: with no Actions minutes every run failed in <15s unallocated — no logs, red ticks on untested commits, including `main`. A gate always red teaches scrolling past; its three jobs live verbatim in `tools/gate.sh`. Restore = `git revert` + billing change, in that order. `desktop.yml` kept its recipe (the only installer record; its smoke steps would have caught v0.2.4) but lost its triggers the same day for the same reason — hand-run only until minutes return.

The gate moved, not disappeared:

1. **Run `tools/gate.sh` locally before every push** (pytest, both JS suites, types, stale-bundle check). A workflow that cannot run is why the gate is yours, not permission to push broken.
2. **Don't block on CI.** Push, tag, keep working; `gh run watch` in the foreground is the habit being cut.
3. **`desktop.yml` untrimmed, hand-run only.** Don't trim for speed; put `push`/`pull_request` back when minutes return. Every installer since 0.5.0 was built by hand on the Windows host — a billing problem, not a reason to cut the recipe.
4. **Ship to the reader, not the branch.** A fix not in a double-clickable installer is not a fix yet.

Ends when the reader confirms a double-clicked install opens and runs an analysis; then delete this section.

## Task tracking

Open work in `backlog.md` (prioritized, goals G1–G5 + evidence); finished items to `done.md` with date + commit. Check before starting, keep current — single source of truth for status.

## Product principle — what Kriko surfaces (READ BEFORE TOUCHING CLAIM SELECTION)

Each pack states its own bar in `packs/<name>/research/principle.md` (cars below; `packs/drill/` differs deliberately). The engine enforces *ranking*, never *taste*.

Value = **config- and mileage-specific known risks a buyer cannot cheaply get from the standard inspection** — what to worry about for *this* car *before* booking the expert.

| Surface when | Do NOT surface (drop/downrank) |
|---|---|
| **Variant-specific** — engine code, gearbox (dual-clutch/automated vs torque-converter), fuel, market | Generic warning-light items ("ABS light", "ESP fault"), anything true of all cars |
| **Predictable from listing** — mileage/year/transmission/fuel implies a known weak point, no inspection needed | Anything the routine mechanic inspection already catches: fluids/leaks, pads, injector bench tests, compression |
| **Due unless proven otherwise** — cam belt, major service, high-mileage clutch/wear parts; omission in the ad *is* the signal | |
| **High-consequence/expensive** — structural weak points; emissions, dual-clutch/mechatronics, turbo, timing | |

Test: *"Would a buyer learn this from a normal inspection anyway?"* → noise. *"Specific to this engine/gearbox/mileage and predictable from the ad?"* → what we exist to show.

> Status: extraction/gating still keeps whatever sources mention (incl. generic items), so live output does **not** yet reflect this. Aligning it — mileage-gated, maintenance-interval/"not in ad", "inspection covers this" filter — is open work. Honour it in any claim-selection change.

## Scalability — no hardcoded car data (READ BEFORE ADDING A MAKE/MODEL/CODE LIST)

Hardcoding makes/models/engine/gearbox codes as Python constants is a **scalability bug**: every list is a manual edit per new car, and history shows it gets forgotten (`SIBLING_CODE_FAMILIES` stale = Flaw 1 in `docs/design_flaws.md`; `normalize.py` `_MAKE_MAP`/`_MODEL_MAP` same mode). **Derive from the catalog** (`packs/cars/data/**/*.yaml`); reference pattern is `catalog_code_manufacturers()` in `packs/cars/pipeline/stoplists.py` (manufacturer-per-code read off part YAMLs — new part covered at stub creation, no registration step).

**Exception:** small closed vocabularies (fuel types, transmission technologies, spelling aliases) may be constants — the rule covers data growing with *coverage*, not fixed engineering categories.

Stronger post-pivot forms: `kriko/` may hold no car-shaped *anything* — no `make`, `engine_code`, `fuel` (`test_core_is_domain_free.py` AST-walks for car vocabulary). And `extension/` held the site's Turkish (damage states, part regexes, thresholds) until 2026-09-10 — now from the adapter's `local_panel` block; `test_the_extension_speaks_no_sites_own_language` fails on any non-ASCII *word* (lone folded character between delimiters stays legal; a word is vocabulary).

Onboarding a model = new YAML under `packs/cars/data/` only (ideally pipeline-generated; `docs/USAGE.md`); a category = never an edit to `kriko/`.

## Generalization — systemic fixes only, no per-model patches

Per-model research runs, audits, spot-checks, one-off patches do not exist. Every fix ships as the *mechanism* catching that class for every current and future car: **"how would we catch this automatically for every car, without a person?"** — ship that, or cancel the feature (automation principle). Mechanism is catalog- or log-derived (validation, coverage report, telemetry, auto-remediation), never a hand list or manual step. A per-model problem is a *test case* for the mechanism. Tracked as B19; B2/B3 manual steps cancelled 2026-08-03.

## Automation — no human in the data path (READ BEFORE ADDING A REVIEW STEP)

Extraction/scraping never wait for verification or sign-off, per datum or per model. Where a value can't be derived automatically (ledger, catalog pipeline, deterministic rule), **fail open**: emit no claim, surface the gap in the coverage report, log a signal for an automated pass. A "someone should review" step is a bug (HUMAN DECISION #6/#7 retired 2026-08-03: B17 dropped, B11 derives-or-fails-open).

Only allowed human decisions are one-time *policy*: source licensing/ToS (B18, #5), market coverage, source retirement. Per-model problem → all-models mechanism (above) or cancel; never a pipeline human step.

## Layering — dependencies flow one way (READ BEFORE ADDING A CROSS-PACKAGE IMPORT)

Five packages; since the pivot a fan, not a column. Import down only:

```
tauri/  desktop shell (Rust, ~180 lines) — sidecar lifetime, nothing else; no engine logic ever
ui/     Svelte+Vite source → src/app/web/static/; HTTP to app/; no Python, no pack vocabulary
app/    interfaces — cli, web dashboard, mcp server, operator TUI (same HTTP API, no webview)
kriko/  engine — pack store, lookup, ranking, research interface; imports NONE of the others; no category
packs/  per-category data, vocabulary, trust tiers, builder, coverage report (third-party-authored)
packs/cars/pipeline/  evidence ledger + grounded extraction
app/pipeline/         ledger_run, remediate, panel, process; may import packs/cars/pipeline/; nothing imports it
```

**`kriko/` importing anything above is the unforgivable violation** (G6's load-bearing invariant — the engine knowing "car" silently ends data-only categories). Packs are consumed *through the store*, never imported; core wanting pack data means the pack should supply a row.

**Upward deferred import (inside a function body) is the smell** — someone dodging `partially initialized module` instead of fixing layering (11 of them pre-2026-08-21, `packs/cars/pipeline/` → deleted `backend/`). Downward-deferred is fine (startup cost).

Must return nothing (tests excluded — e2e may span layers):

```bash
grep -rnE "^[[:space:]]*(from|import) (backend|app|packs|knowledge)" --include='*.py' src/kriko/  | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) (backend|app|packs)"           --include='*.py' packs/cars/pipeline/  | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) (app|app.pipeline)"                         --include='*.py' packs/      | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) backend"                    --include='*.py' src/app/   | grep -v /pipeline/ | grep -v /tests/
```

Enforced in `src/app/pipeline/tests/test_repo_invariants.py` (also ratchets deleted `backend/` shut). `ui/` rebuild: `npm --prefix ui run build`, commit both; CI fails on stale bundle. Forms from `/api/identity-keys/{pack_id}` + `/api/packs/{pack_id}/vocabulary` at runtime (`test_ui_contains_no_pack_vocabulary`).

**Long work is a row, not a request** (`app/web/jobs.py` single worker, cooperative cancel; state in `app.sqlite` `jobs`; handlers in `app/web/tasks.py`). POST returns a job id; log/result/failure outlive request and process (`running` at startup → `interrupted`). Same acceptance path as MCP (`app/findings.py`) — provenance must not depend on the door.

**Desktop shell is a supervisor, not a second engine.** `src/app/sidecar.py` binds an OS-chosen port, prints `KRIKO_PORT <n>` first (child picks — a parent-found port is already lost at bind). `tauri/` polls `/api/health`, then shows; on failure renders stderr (blank window = bug). **Window ≠ Quit:** close hides, engine serves (extension uses `EXTENSION_PORT` when the reader is on a listing); tray (Open, Quit) ends it; Windows kill is a *tree* kill (PyInstaller onefile re-execs — spawned pid is bootloader, child holds image). `--exit-with-parent` (stdin close) is the crash belt; an orphan holds the WAL lock *and* maps its own `.exe`, failing the next installer ("Error opening file for writing: kriko-sidecar.exe") — so `installer.nsh` stops `Kriko.exe` first (exit closes stdin, the designed way out) then `kriko-sidecar.exe`. Two sockets (announced + fixed 8787) since the extension can't be told a random port. Guards (no crate build): handshake/flag agreement both sides, extension port = server constant, every `start_engine` failure reaches `emit_failure`, NSIS kills the shipped binary, no engine vocabulary in Rust; `test_the_shell_is_valid_rust.py` parses via bare `rustc` (`error:` with no code = syntax; `error[E0432]` = unresolved name — skips without `rustc`, never passes). See `tauri/README.md`.

**Two SQLite files, on purpose:** `~/.kriko/knowledge.sqlite` (engine store) vs `~/.kriko/app.sqlite` (`app/web/state.py`: history/settings). Interface state never enters engine schema (pack uninstall must not drop history; history must not touch `content_digest`). `/api/health` reports both.

**Two update clocks, neither waiting:** knowledge weekly via engine (`kriko/pack/updates.py` decides — index parsed, version + `content_digest` compared, republished version refused as `packstore.install` does; `app/packsource.py` fetches — engine owns no socket); app via Tauri minisign updater, configured at build time (`packaging/configure_updater.py`, keyless trees still build). Checking is a request; installing is a job. The weekly pass is `app/packautoupdate.py` (B166): at startup, if a week has passed since the last success, it submits a `pack_update` job for already-installed packs only; the Updates block is gone from the UI.

**Installer carries first-party packs** (until 0.7.1 it carried none — fresh installs opened empty, and row-level fixes couldn't ship by release). `app/bundledpacks.py` seeds at startup (missing → install; newer → install, never older; failure never blocks start), identity from the `.kpack`'s own `packs` row, set discovered from `packs/*/pack.toml` via `packaging/build_packs.py` — a third pack ships by existing.

Wrong-layer need → move the module (drivers → `app/pipeline/`; interfaces → `app/`; category-specific → `packs/<category>/`). See `docs/INTERNALS.md`, `docs/superpowers/specs/2026-08-21-codebase-organisation-design.md`.

## Documentation map

| Doc | For | Status |
|-----|-----|--------|
| `README.md` | overview, quickstart, supported cars | current |
| `packs/<name>/README.md` | pack coverage + its principle | current |
| `CLAUDE.md` | agent principles + working rules | current |
| `CONTRIBUTING.md` | loop, branches, commits, gate | current |
| `docs/DOCTRINE.md` | request → done: backlog, done-ness, tests, PR proof, parallel agents | current — read first |
| `backlog.md` / `done.md` | task status, single source of truth | current |
| `docs/ARCHITECTURE.md` | reading map, package ownership | current |
| `docs/USAGE.md` | operating stack + growing knowledge | current |
| `docs/HOW_IT_WORKS.md` | matching, pack lifecycle, run, layering diagrams | current |
| `docs/STYLE.md` | doc-writing rules | current |
| `docs/BRAND.md` | mark sources vs renders, rationale | current |
| `docs/INSTALL_WINDOWS.md` | Windows install incl. extension permission | current |
| `docs/INTERNALS.md` | mechanism-level architecture | current (verify vs code) |
| `docs/PACK_CONTRACT.md` | pack contents, must/may | current |
| `docs/superpowers/specs/2026-09-15-ground-truth-benchmark-design.md` | B126 precision/recall/hallucination + sweep | design only |
| `docs/AGENT_OPERATIONS.md` | operation vocabulary, harness protocol, open questions | note — B122–124 |
| `docs/GLOSSARY.md` | one-line words; two with double meanings | current |
| `docs/superpowers/specs/2026-09-01-standalone-app-ui-design.md` | UI rewrite + Tauri phases 0–5 | landed; installers unbuilt (B52) |
| `docs/superpowers/specs/2026-09-03-app-design-and-ia.md` | design system, IA, four features | current |
| `docs/superpowers/specs/2026-09-09-research-agenda-design.md` | B82 research ordering | implemented (`app/agenda.py`, `2a9d82c`) |
| `docs/superpowers/specs/2026-09-14-extension-and-app-harmony-design.md` | extension↔app: palette fork, `claims`/`risks` rename | design only |
| `docs/superpowers/specs/2026-09-09-knowledge-building-design.md` | self-growing packs: planes, keys, agenda, provenance/undo, identity skill | implemented (`0ab613d`, `b945408`) |
| `tauri/README.md` | shell: launch, failures, local build | current — hand-built via `/mnt/c` (0.5.0–0.5.2) |
| `docs/design_flaws.md` | 2026-07-04 audit; flaws 1–4 fixed, 5–6 → B13 | reference |
| `~/.claude/plans/let-s-go-with-the-eager-torvalds.md` | G6 pivot design + phases | Phase 6 in progress |
| `docs/historical/` | pre-part-centric era + superseded 2026-07 designs + pre-pivot roadmaps | historical — do not follow |

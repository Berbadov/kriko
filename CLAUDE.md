# Kriko — working notes for an agent

Local-first, open knowledge engine for manufactured products. It answers one
question, *what is known to go wrong with this specific one*, from installed
**catalogs** on any listing site, entirely on the reader's machine. A
**catalog** is one product category as data; site reading is a **site adapter**,
delivered by the browser extension. A pack is what the code calls a catalog, and
a pack is what this file calls `packs/`.

The engine knows no category. A new category is a data change (a directory
under `packs/`), never an engine change (goal **G6**; every principle below
keeps it true). See `docs/USAGE.md` (operation), `docs/INTERNALS.md`
(mechanism), `docs/ARCHITECTURE.md` (where to read the code).

This file names no model, no agent product and no catalog on purpose. Where a
document has to name one, that is a defect in the document: a decision that
belongs to the reader's own machine must not be frozen into prose that every
other machine reads.

## Doctrine — read `docs/DOCTRINE.md` before any work *(2026-09-24)*

Short form, not a substitute:

1. **Write the request down first** in `backlog.md`, quoting the reader, with
   **Where** (exact screen) and **Done when** (what they can see). Read it
   back before any code. No "Done when", no start.
2. **Done means observed**: end result on the named screen, on `main`, on
   Windows where it differs.
3. **Reproduce first, then fix.** Ask the tool for its facts; never type a list
   from memory.
4. **Every PR carries its proof** (quote, observation, screenshot); a second
   agent reviews it against the request.
5. **One area per agent, a PR the same day, merged daily** (by the reader;
   nothing reaches `main` without the author asking).

## TEMPORARY — app-first phase *(2026-09-01, delete when it ends)*

Until a Windows install opens, runs a check, and the reader says so, the loop is
the *app*, not the suite. `ci.yml` was un-paused 2026-09-08 (audit: four
defects passed every gate, which is why it was un-paused), then deleted
2026-09-13: with no Actions minutes every run failed in under 15 seconds
unallocated, so there were no logs and red ticks on untested commits, `main`
included. A gate that is always red teaches scrolling past it. Its three jobs
live verbatim in `tools/gate.sh`. Restore is `git revert` then the billing
change, in that order. `desktop.yml` kept its recipe (the only installer
record; its smoke steps would have caught v0.2.4) but lost its triggers the
same day for the same reason: hand-run until minutes return.

The gate moved, it did not disappear:

1. **Run `tools/gate.sh` before every push** (pytest, both JS suites, types,
   stale-bundle check). A workflow that cannot run is why the gate is yours,
   not permission to push broken work.
2. **Do not block on CI.** Push, tag, keep working.
3. **`desktop.yml` untrimmed, hand-run only.** Do not trim it for speed; put
   `push`/`pull_request` back when minutes return. Every installer so far was
   built by hand on a Windows host, which is a billing problem and not a reason
   to cut the recipe.
4. **Ship to the reader, not the branch.** A fix not in a double-clickable
   installer is not a fix yet.

Ends when the reader confirms a double-clicked install opens and runs a check;
then delete this section.

## Task tracking

Open work is `backlog.md`, and it is the only status file: a finished item
leaves the backlog and its commit message carries the reasoning. `git log` is
the record of what was done. Check before starting and keep it current.

## Product principle — what Kriko surfaces

**READ BEFORE TOUCHING CLAIM SELECTION.** Each catalog states its own bar in
`packs/<name>/research/principle.md`. The engine enforces *ranking*, never
*taste*: it cannot know what is worth surfacing in a category it knows nothing
about, and a hardcoded answer would be a category assumption in the one layer
that must not have any.

A bar is written as a table of *surface when* against *do not surface*, and a
test a reader can apply to one claim. The shipped example is the pattern, not
the content: specific to the configuration rather than true of the whole
category; predictable from what the listing already says; due unless something
proves otherwise; high-consequence where being wrong is expensive. A category
whose risks are cheap to check by other means has a different bar, and says so.

Honour whatever bar the pack declares in any claim-selection change.

## Scalability — no hardcoded category data

**READ BEFORE ADDING A LIST OF PRODUCT NAMES.** Hardcoding makes, models or
component codes as Python constants is a **scalability bug**: every list is a
manual edit per new product, and history shows it gets forgotten. Derive from
the catalog's own data files, so a new product is covered by adding its data and
there is no registration step anywhere (one worked example is the per-code
ownership lookup in a mature pack's `pipeline/stoplists.py`).

**Exception:** small closed vocabularies (a set of fuel types, a set of
transmission technologies, spelling aliases) may be constants. The rule covers
data that grows with coverage, not fixed engineering categories.

The stronger form after the pivot: `kriko/` may hold no category-shaped
*anything*, and `test_core_is_domain_free.py` walks its AST to prove it. The
extension used to hold one site's own language and no longer does; the words
arrive in the adapter's `local_panel` block, and
`test_the_extension_speaks_no_sites_own_language` fails on any non-ASCII *word*
(a lone folded character between delimiters stays legal; a word is vocabulary).

Onboarding one product is a new data file under `packs/<name>/data/`. A new
category is never an edit to `kriko/`.

## Generalization — systemic fixes only, no per-product patches

Per-product research runs, audits, spot-checks and one-off patches do not
exist. Every fix ships as the *mechanism* that catches that class for every
current and future product: **"how would we catch this automatically for
everything, without a person?"** Ship that, or cancel the feature. A mechanism
is catalog- or log-derived (validation, a coverage report, telemetry,
auto-remediation), never a hand-written list or a manual step. A per-product
problem is a *test case* for the mechanism.

## Automation — no human in the data path

**READ BEFORE ADDING A REVIEW STEP.** Extraction and scraping never wait for
verification or sign-off, per datum or per product. Where a value cannot be
derived automatically (a ledger, a catalog pipeline, a deterministic rule),
**fail open**: emit no claim, surface the gap in the coverage report, log a
signal for an automated pass. A "someone should review" step is a bug.

The only allowed human decisions are one-time *policy*: source licensing and
terms of service, market coverage, source retirement. A problem with one
product becomes an all-products mechanism or a cancelled feature, never a
pipeline step a person walks.

## Layering — dependencies flow one way

**READ BEFORE ADDING A CROSS-PACKAGE IMPORT.** Six packages. Since the pivot
a fan, not a column. Import down only:

```
tauri/  desktop shell (Rust, ~180 lines) — sidecar lifetime, nothing else; no engine logic ever
ui/     Svelte+Vite source -> src/app/web/static/; HTTP to app/; no Python, no catalog vocabulary
app/    interfaces — cli, web dashboard, mcp server, operator TUI (same HTTP API, no webview)
kriko/  engine — pack store, lookup, ranking, research interface; imports NONE of the others; no category
packs/  per-category data, vocabulary, trust tiers, builder, coverage report (third-party-authored)
packs/<name>/pipeline/  evidence ledger + grounded extraction, per category
app/pipeline/           ledger_run, remediate, panel, process; may import packs/<name>/pipeline/; nothing imports it
```

**`kriko/` importing anything above is the unforgivable violation.** It is
G6's load-bearing invariant: the engine knowing one category silently ends
data-only categories. Packs are consumed *through the store*, never imported;
core wanting pack data means the pack should supply a row.

**Upward deferred import (inside a function body) is the smell** — someone
dodging `partially initialized module` instead of fixing layering. Downward
deferred is fine (startup cost).

Must return nothing (tests excluded, e2e may span layers):

```bash
grep -rnE "^[[:space:]]*(from|import) (backend|app|packs|knowledge)" --include='*.py' src/kriko/  | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) (backend|app|packs)"           --include='*.py' packs/*/pipeline/  | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) (app|app.pipeline)"                         --include='*.py' packs/  | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) backend"                    --include='*.py' src/app/   | grep -v /pipeline/ | grep -v /tests/
```

Enforced in `src/app/pipeline/tests/test_repo_invariants.py`. `ui/` rebuild:
`npm --prefix ui run build`, commit both; the gate fails on a stale bundle.
Forms come from `/api/identity-keys/{pack_id}` and
`/api/packs/{pack_id}/vocabulary` at runtime
(`test_ui_contains_no_pack_vocabulary`, in that same invariants file).

**Long work is a row, not a request** (`app/web/jobs.py`, one worker,
cooperative cancel; state in `app.sqlite` `jobs`; handlers in
`app/web/tasks.py`). The POST returns a job id; log, result and failure
outlive the request and the process (`running` at startup becomes
`interrupted`). Same acceptance path as MCP (`app/findings.py`), so provenance
must not depend on which door the work arrived through.

**Desktop shell is a supervisor, not a second engine.** `src/app/sidecar.py`
binds an OS-chosen port and prints `KRIKO_PORT <n>` first (a parent-found port
is already lost at bind). `tauri/` polls `/api/health`, then shows; on failure
it renders stderr, because a blank window is a bug. **Window is not Quit:**
closing hides and the engine keeps serving, which the extension needs; the tray
(Open, Quit) ends it. On Windows a kill is a *tree* kill, because a one-file
bundle re-executes: the spawned pid is the bootloader and the child holds the
image. `--exit-with-parent` (stdin close) is the crash belt; an orphan holds
the write-ahead lock *and* maps its own executable, which fails the next
install, so `installer.nsh` stops the shell first (its exit closes stdin, the
designed way out) and the sidecar second. Two sockets, announced and fixed,
because the extension cannot be told a random port. Guards with no crate build:
handshake and flag agreement on both sides, the extension port equals the
server constant, every `start_engine` failure reaches `emit_failure`, the
installer script kills the shipped binary, and no engine vocabulary appears in
Rust. `test_the_shell_is_valid_rust.py` parses through bare `rustc` (`error:`
with no code means a syntax error, `error[E0432]` means an unresolved name; it
skips where there is no `rustc`, and never passes). See `tauri/README.md`.

**Two SQLite files, on purpose:** `~/.kriko/knowledge.sqlite` (the engine
store) against `~/.kriko/app.sqlite` (`app/web/state.py`: history and
settings). Interface state never enters the engine schema: uninstalling a pack
must not drop history, and history must not move a `content_digest`.
`/api/health` reports both.

**Two update clocks, neither waiting:** knowledge updates weekly through the
engine (`kriko/pack/updates.py` decides, `app/packsource.py` fetches, so the
engine owns no socket) and the app updates through the shell's minisign
updater, configured at build time (`packaging/configure_updater.py`, so a
keyless tree still builds). Checking is a request; installing is a job. The
weekly pass is `app/packautoupdate.py`, which at startup submits an
`pack_update` job for already-installed packs only when a week has passed since
the last success. There is no updates block in the UI.

**The installer carries first-party catalogs** (until 0.7.1 it carried none,
so a fresh install opened empty and row-level fixes could not ship by
release). `app/bundledpacks.py` seeds at startup: missing means install, newer
means install, never older, and a failure never blocks start. Identity comes
from the bundle's own `packs` row, and the set is discovered from
`packs/*/pack.toml` by `packaging/build_packs.py`, so a third catalog ships by
existing.

A need from the wrong layer means moving the module (drivers to
`app/pipeline/`, interfaces to `app/`, category-specific to
`packs/<name>/`). See `docs/INTERNALS.md` and
`docs/superpowers/specs/2026-08-21-codebase-organisation-design.md`.

## Documentation map

| Doc | For | Status |
|-----|-----|--------|
| `README.md` | overview, quickstart, what a catalog is | current |
| `packs/<name>/README.md` | one catalog's coverage and its own bar | current |
| `CLAUDE.md` | agent principles and working rules | current |
| `CONTRIBUTING.md` | loop, branches, commits, gate | current |
| `docs/DOCTRINE.md` | request to done: backlog, done-ness, tests, PR proof, parallel agents | current, read first |
| `backlog.md` | open work, the only status file | current |
| `docs/ARCHITECTURE.md` | reading map, package ownership | current |
| `docs/USAGE.md` | operating the stack and growing knowledge | current |
| `docs/HOW_IT_WORKS.md` | matching, catalog lifecycle, a run, layering | current |
| `docs/STYLE.md` | how these documents are written | current |
| `docs/BRAND.md` | mark sources against rendered output, and why | current |
| `docs/INSTALL_WINDOWS.md` | Windows install including the extension permission | current |
| `docs/INTERNALS.md` | mechanism-level architecture, every endpoint and table | current |
| `docs/PACK_CONTRACT.md` | what a catalog contains, must and may | current |
| `docs/GLOSSARY.md` | one line per word, and the words with two meanings | current |
| `docs/AGENT_OPERATIONS.md` | operation vocabulary, the harness protocol, open questions | a note, dated 2026-09-14 |
| `docs/superpowers/specs/2026-09-15-ground-truth-benchmark-design.md` | precision, recall and hallucination, plus the sweep | design only |
| `docs/superpowers/specs/2026-09-01-standalone-app-ui-design.md` | the UI rewrite and its shell phases | landed |
| `docs/superpowers/specs/2026-09-03-app-design-and-ia.md` | design system, information architecture, four features | current |
| `docs/superpowers/specs/2026-09-09-research-agenda-design.md` | research ordering | implemented |
| `docs/superpowers/specs/2026-09-14-extension-and-app-harmony-design.md` | extension and app: palette fork, the claims rename | design only |
| `docs/superpowers/specs/2026-09-09-knowledge-building-design.md` | self-growing catalogs: planes, keys, provenance, undo | implemented |
| `tauri/README.md` | the shell: launch, failures, local build | current, hand-built |
| `docs/design_flaws.md` | the 2026-07-04 audit; flaws 1 to 4 fixed | reference |
| `docs/audits/` | dated audits of a named release | record, not a worklist |
| `docs/historical/` | the pre-pivot era, superseded designs and old roadmaps | historical, do not follow |

# Kriko — working notes for an agent

Local-first, open knowledge engine for manufactured products. It answers one
question, *what is known to go wrong with this specific one*, from installed
**catalogs** on any listing site, entirely on the reader's machine. A
**catalog** is one product category as data; site reading is a **site adapter**,
delivered by the browser extension. A pack is what the code calls a catalog, and
a pack is what this file calls `packs/`.

The engine knows no category. A new category is a data change (a directory
under `packs/`), never an engine change (goal **G6**; every principle below
keeps it true). See `docs/USAGE.md` (operation), `docs/HOW_IT_WORKS.md`
(mechanism), `docs/ARCHITECTURE.md` (where to read the code).

This file names no model, no agent product and no catalog on purpose. Where a
document has to name one, that is a defect in the document: a decision that
belongs to the reader's own machine must not be frozen into prose that every
other machine reads.

## Doctrine — `docs/DOCTRINE.md` *(lean since 2026-10-12)*

About a fifth of the effort goes on process; the rest is the product.

1. **Know what was asked:** quote the reader and write **Done when** before
   code. In the PR for up to a day of work; a GitHub issue for more.
2. **Done means observed**: on the screen the reader uses, on Windows where it
   differs; a changed screen gets a screenshot in the PR.
3. **Reproduce first, then fix.**
4. **Test behaviour, not prose**: no tests that only keep documents in step.
5. **Proof sized to the change**; a second-agent review only for big or
   lookup-touching PRs. The reader merges.
6. **Versions and README notes move at release**, not per change
   (`kriko-ui/README.md`, the release section).

## The gate — green on every push *(2026-10-11)*

There are no Actions minutes, so `ci.yml` is gone and `tools/gate.sh` is the
only gate: version agreement, ruff, mypy, pytest, both JS suites, the wheel,
and `cargo check` + `cargo test` for `kriko-ui/src-tauri/`, plus a
`cargo check` for Windows (the `x86_64-pc-windows-gnu` target) off a Windows host,
so the Windows-only code is compiled on every push. It was left red for weeks
(43 failures, 15 type errors) because merges skipped it; 1.5.0 brought it back
to green. So:

1. **Run `tools/gate.sh` before every push and every merge.** A red gate on
   your branch is yours to fix before pushing. A red gate on `main` is the
   first work of the day, before any feature.
2. **A behaviour change updates its tests in the same commit.** A test that
   asserts retired behaviour is rewritten to assert the new intent, or deleted
   with the code it guarded. It is never left failing for someone else.
3. **`desktop.yml` is the desktop release recipe, hand-dispatched.** Its
   `bundle` job builds the Windows x64 installer and portable ZIP; its
   `bundle-macos` job builds the Apple Silicon (`arm64`) disk image by running
   `kriko-ui/package-macos.sh` on a `macos-14` runner. Tauri and PyInstaller do
   not cross-compile, so a macOS package is assembled on a Mac of its own
   architecture; Intel is not built. The macOS job uploads a workflow artifact
   and publishes no release asset yet, because `tools/release_readiness.py`
   records a Windows platform only; a macOS row has to exist before the disk
   image joins a release. Dispatch it on the reviewed source branch first,
   verify and download the artifacts, then tag that exact source SHA and upload
   those artifacts to a new draft release. Dispatching on a tag runs the native
   builds again and creates a draft; use that path only when a second build is
   intended. See `kriko-ui/README.md`. Do not trim the workflow.
4. **Ship to the reader, not the branch.** A fix is not done until its package
   has been built and observed on the target platform. Windows and each native
   Mac architecture need their own packaging and smoke evidence.

On Linux, `cargo test` needs `libxkbcommon-dev` and `libxkbcommon-x11-dev`;
without them it fails at link time, not in a test.

## Task tracking

Open work bigger than a day is a GitHub issue (Linear mirroring optional);
nothing in the repo is a status file. A PR closes its issue
(`Closes #n`), and its commit message carries the reasoning. `git log` is the
record of what was done. Check the issues before starting and keep them
current.

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

## Catalogs grow from quick looks *(2026-10-11)*

A quick look is already sourced and quote-checked, so it is the raw material
of a catalog, not a preview of a research run. Two rules follow:

1. **No second research run for what is already known.** A quick look whose
   product a catalog already holds is filed by re-reading each quote against
   its page and attaching it (`tasks._file_quick_look`). A product the
   catalog lacks joins it too when the quick look read every identity key of
   one of the catalog's kinds (`pack_identity`, written by
   `categorypack.add_subject`); an agent is spent only when it could not.
2. **Accumulation is a harvest, not a chore.** `POST /api/packs/harvest`
   files every saved quick look not yet filed, installs each catalog that
   gained claims once, and returns its `.kpack` link to share. A look that
   names no catalog, or lacks an identity key, is listed as needing an agent, never sent to one
   unasked, because spending an agent is the reader's press.

So a catalog shared between readers is the sum of their grounded quick
looks, and every claim in it still carries the page and the quote it came from.

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
kriko-ui/  desktop app (Tauri: a Rust shell and a React interface) — supervises the sidecar and draws every screen from the local API; no engine logic ever
app/    interfaces — cli, local HTTP API, mcp server, operator TUI
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

Enforced in `src/app/pipeline/tests/test_repo_invariants.py`.

**Long work is a row, not a request** (`app/web/jobs.py`: as many at once
as Settings says, never two on one pack, cooperative cancel; state in `app.sqlite` `jobs`; handlers in
`app/web/tasks.py`). The POST returns a job id; log, result and failure
outlive the request and the process (`running` at startup becomes
`interrupted`). Same acceptance path as MCP (`app/findings.py`), so provenance
must not depend on which door the work arrived through.

**Desktop shell is a supervisor, not a second engine.** `src/app/sidecar.py`
binds an OS-chosen port and prints `KRIKO_PORT <n>` first (a parent-found port
is already lost at bind). `kriko-ui/src-tauri/src/engine.rs` polls `/api/health` while
the window says it is starting; on failure it renders stderr, because a blank
window is a bug. **Window is not Quit:**
closing hides and the engine keeps serving, which the extension needs; the tray
(Open, Quit) ends it. On Windows a kill is a *tree* kill, because a one-file
bundle re-executes: the spawned pid is the bootloader and the child holds the
image. `--exit-with-parent` (stdin close) is the crash belt; an orphan holds
the write-ahead lock *and* maps its own executable, which fails the next
install, so the NSIS installer (`kriko-ui/src-tauri/tauri.conf.json` with
`windows/hooks.nsh`) stops the app first (its exit
closes stdin, the designed way out) and the sidecar second. Two sockets, announced and fixed,
because the extension cannot be told a random port. Guards with no crate build:
handshake and flag agreement on both sides, the extension port equals the
server constant, every start failure reaches the failure screen, the installer
kills the shipped binaries, and the app reads the store only through the HTTP
API (no SQL, no sqlite crate). `test_the_shell_is_valid_rust.py` parses through bare `rustc` (`error:`
with no code means a syntax error, `error[E0432]` means an unresolved name; it
skips where there is no `rustc`, and never passes). See `kriko-ui/README.md`.

**Two SQLite files, on purpose:** `~/.kriko/knowledge.sqlite` (the engine
store) against `~/.kriko/app.sqlite` (`app/web/state.py`: history and
settings). Interface state never enters the engine schema: uninstalling a pack
must not drop history, and history must not move a `content_digest`.
`/api/health` reports both.

**Two update clocks, neither waiting:** knowledge updates weekly through the
engine (`kriko/pack/updates.py` decides, `app/packsource.py` fetches, so the
engine owns no socket). The app checks the latest release through
`app/appupdate.py`; its verified download is the Windows x86_64 installer
(`kriko-<version>-x86_64-setup.exe`), which the Windows shell runs after closing
Kriko — the corner notice offers it (`kriko-ui/src/ui/UpdateNotice.tsx`, the
shell's `app_install_update`). It does
not update portable archives
or the macOS app: the Mac package is installed from a disk image and updated by
downloading the next one, and `app/appupdate.py` matches the Windows installer
name only, so a Mac build offers no update. Checking is a
request; the weekly pass is `app/packautoupdate.py`, which at startup submits
a `pack_update` job for already-installed packs only when a week has passed
since the last success. There is no pack-updates block in the UI.

**The installer carries no packs** (#169). A fresh install opens onto an empty
store, and Overview (the Knowledge group) offers the published index's packs with an
Install button (same `pack_update` job as an update). The sidecar freezes no `.kpack`, no build step makes one for the
installer, and startup seeds nothing. The reader installs the packs they want,
and a pack already installed is kept current by the weekly update above. The
release job still builds each `packs/<name>` into a `.kpack` and publishes
`packs.json`; that is the update channel, not what the installer contains.
`test_the_installer_carries_no_packs.py` pins it.

A need from the wrong layer means moving the module (drivers to
`app/pipeline/`, interfaces to `app/`, category-specific to
`packs/<name>/`). See `docs/ARCHITECTURE.md`.

## Documentation map

| Doc | For | Status |
|-----|-----|--------|
| `README.md` | overview, quickstart, what a catalog is | current |
| `packs/<name>/README.md` | one catalog's coverage and its own bar | current |
| `CLAUDE.md` | agent principles and working rules | current |
| `docs/DOCTRINE.md` | request to done, kept lean: what was asked, done-ness, tests, PR proof; then setup, branches, commits, the gate | current, read first |
| `docs/ARCHITECTURE.md` | reading map, package ownership | current |
| `docs/USAGE.md` | operating the stack and growing knowledge | current |
| `docs/HOW_IT_WORKS.md` | matching, catalog lifecycle, a run, layering | current |
| `docs/STYLE.md` | how these documents are written | current |
| `docs/INSTALL_WINDOWS.md` | Windows install including the extension permission | current |
| `docs/INSTALL_MACOS.md` | macOS install on Apple Silicon: the disk image, Gatekeeper, building it | current |
| `docs/PACK_CONTRACT.md` | what a catalog contains, must and may | current |
| `docs/KRIKO_AGENT.md` | the built-in research stack: its bounds, its search dial, what a buying answer owes | current |
| `docs/security/shared-access.md` | the password-and-code protocol, the trial, and what neither protects | current |
| `docs/design/kriko-agent-first.md` | the app arranged around the Kriko Agent: what exists, what changes | a proposal, dated 2026-10-23 |
| `docs/AGENT_OPERATIONS.md` | operation vocabulary, the harness protocol, open questions | a note, dated 2026-09-14 |
| `kriko-ui/README.md` | the desktop app: engine supervision, screens, installer | current, hand-built |

The map names what is here. It used to name `docs/BRAND.md`, `docs/INTERNALS.md`,
`docs/PROTOCOL.md`, `docs/GLOSSARY.md` and `docs/UPDATE_PROTOCOL.md` as current:
all five were deleted by the `reset` commit and do not exist, while this file
went on citing them for two months. If a document is wanted back, restore it —
a row in this table is not a document.

# Codebase organisation — design

**Date:** 2026-08-21
**Branch:** `feat/agent-model-onboarding`
**Status:** approved, pending execution
**Revised:** 2026-08-21 — Phase 5 (dependency-cycle refactor) added

## Problem

Five distinct kinds of disorder, at different layers:

1. `knowledge/` root holds 21 loose modules — live pipeline code mixed with spent
   one-off migration scripts, two of which are per-model patches that the
   generalization principle in `CLAUDE.md` forbids.
2. `knowledge/ledger.db` is tracked *and* listed in `.gitignore`. Gitignore does not
   untrack; the 6.9 MB binary re-diffs on every commit and appears in three recent ones.
3. ~50 uncommitted files spanning four unrelated features share one working tree.
4. Root clutter: `sahibinden_example/` (7.8 MB, 152 tracked files, zero references),
   `local.db`, `thoughts/`, root-owned `logs/`. `.pytest_cache` is not gitignored.
5. Four docs that `CLAUDE.md` itself marks "historical — do not follow" sit beside
   current ones in `docs/`.

## Baseline

`python -m pytest -q` → **760 passed, 1 failed** (2026-08-21).

The single failure is a test-harness bug, not a product bug.
`knowledge/tests/test_hub_web.py::test_every_element_the_script_reaches_for_exists_on_the_page`
regex-scans `hub.js` for `$('#id')` selectors without stripping comments. The new
`hub.js:7` comment documents a past bug using an illustrative `$('#missing')`
selector, which the scanner reads as live code.

Every phase below must hold **760 passed** and drive the failure count to zero.

## Non-goals

- No history rewrite. `git rm --cached` stops future churn; historical blobs stay in
  `.git`. Shrinking the pack is a separate, deliberate decision.
- No *renaming*. `discover.py` existing twice with unrelated meanings, and the vague
  `auto.py` / `process.py`, are real readability problems but are left alone — Phase 5
  moves files without also changing what they are called, so every move stays
  greppable. Renames are follow-up work.
- Phase 5 relocates modules to break the dependency cycle (added 2026-08-21 after the
  original "no relocation" scope proved unable to address the intuitiveness problem).
  Phases 1-4 still change no import paths; all churn is isolated to Phase 5.
- No splitting of the large files (`hub/web.py` 1151 lines, `hover_lite.js` 1084,
  `hub/static/hub.js` 935). Its own project, after this lands.
- `.opencode/` and `opencode.json` untouched — another harness's config.

## Phase 1 — commit the dirty tree

Six commits, each diff read before staging. Runtime artifacts are excluded here and
handled in Phase 2.

| # | Commit | Files |
|---|--------|-------|
| 1 | source tiers | `knowledge/sources/tiers.py`, `catalog/source_tiers.yaml`, `tests/test_source_tiers.py` |
| 2 | catalog registry + generations | `catalog/registry.py`, `components.yaml`, `generations/` |
| 3 | part YAML v3 | `parts/migrate_v3.py`, `parts/validate_part_yaml.py`, 24 × `backend/data/parts/**/*.yaml` |
| 4 | serving payload v2 | `backend/api/main.py`, `api/schemas.py`, `core/resolver.py`, `db/models.py`, `db/schema.sql`, `sync.py`, `tests/test_serving_gold.py`, `tests/test_serving_payload_v2.py`, `tests/fixtures/serving_gold/`, `tests/test_sync_consequence.py`, `tests/test_sync_validation_gate.py`, `deploy/Dockerfile`, `docs/INTERNALS.md` |
| 5 | hover_lite UI | `extension_ui/hover_lite/{hover_lite.js,hover_lite.css,risk_card.js}` |
| 6 | hub picker + comment-scanner fix | `knowledge/hub/static/{hub.js,style.css}`, `hub/tests/{harness.js,picker.test.js}`, `knowledge/tests/test_hub_web.py` |

Commit 6 fixes the baseline failure: strip `//` line comments and `/* */` blocks from
the script text before scanning for selectors. The guard keeps its value (it still
catches genuinely absent elements) and stops penalising explanatory comments.

If any group's diff turns out to span features, it is split further rather than
force-fitted into the table.

## Phase 2 — git hygiene

1. `git rm --cached` for the tracked runtime artifacts: `knowledge/ledger.db`,
   `knowledge/hub/runs.jsonl`.
2. `git rm --cached -r sahibinden_example/` — 152 files, 7.8 MB, zero code references.
   Kept on disk and gitignored, not deleted: it is a useful scraper reference sample.
3. `.gitignore` additions: `.pytest_cache/`, `knowledge/catalog/cache/`,
   `knowledge/hub/runs.jsonl`, `sahibinden_example/`.
4. `local.db` is already ignored and untracked — no action.

## Phase 3 — knowledge/ dead-code removal (21 → 13 modules)

Delete seven leaf modules. Each has zero importers; every apparent reference is a
self-reference inside its own docstring. Each imports *from* live modules and is
imported by nothing, so no dependency edge is severed.

Five of the seven were already listed for deletion in
`docs/superpowers/plans/2026-07-07-evidence-ledger-stage1.md:2328`; that plan was
only half executed (its `purge_*.py` targets are gone, these were left behind).

| Module | Why dead |
|---|---|
| `downgrade_unsourced_claims.py` | one-off retroactive fix; on the July delete list |
| `find_cross_file_duplicates.py` | one-off report; `docs/design_flaws.md:55` calls its existence the symptom |
| `generalize_titles.py` | one-off title rewrite; logic now in the extraction path |
| `merge_ea888_power_tunes.py` | **per-model patch** — violates the generalization principle |
| `normalize_domains.py` | one-off; `domains.normalize_domain` is the live mechanism |
| `fix_sibling_contamination.py` | **per-model patch**; `stoplists.mentions_sibling_code` is the live mechanism |
| `verify_agent.py` | `docs/handover.md:4` states this flow "is not how Kriko works today" |

Retained at `knowledge/` root (13): `auto`, `consequence_tier`, `dedup`, `discover`,
`domains`, `extract`, `ground_mileage_threshold`, `ground_year_window`,
`langextract_client`, `process`, `scaffold`, `stoplists`, `yamlutil`.

`scaffold.py` is retained despite `docs/SCAFFOLD.md` being marked historical —
`README.md:153` still documents it as the bootstrap entry point. Reconciling those
two is follow-up work, not part of this cleanup.

Full suite runs after deletion to confirm 760 still pass.

## Phase 4 — docs and stale artifacts

1. `docs/historical/` gets the two "do not follow" docs: `SCAFFOLD.md`, `handover.md`.

   **Revised during execution:** `pipeline_postmortem.md` stays in `docs/`. It is
   marked "historical" but not "do not follow", and three live files cite it as a
   standing convention — `knowledge/parts/search_templates.py:54`,
   `knowledge/tests/test_langextract_client.py:3`, `docs/design_flaws.md:155`. A
   postmortem people still reason from is reference material, not an artefact.
2. `CLAUDE.md`'s documentation-map table lists a fourth, `kriko_build_plan.md`, which
   does not exist anywhere in the tree — a dangling reference. Drop that row and
   update the other three to their new `docs/historical/` paths.
3. `thoughts/` moves to `docs/historical/thoughts/` (6 files, all 2026-07-05/22,
   superseded by `docs/superpowers/`).

   **Revised during execution:** the spec originally said untrack and gitignore.
   `done.md:316` cites `thoughts/ledger_acceptance_parity_2026-07-22.txt` as the
   evidence artefact for a completed item, so untracking it would leave a dangling
   citation in the project record for anyone cloning the repo. Moved and re-pointed
   instead.
4. Record the outcome in `done.md` per the project's tracking convention.

## Verification

- Full `pytest -q` after phases 1, 3 and 4 — 760 passed, 0 failed.
- `git status --porcelain` empty at the end, apart from deliberately ignored artifacts.
- `python -c "import knowledge.process, knowledge.auto, knowledge.extract"` after
  Phase 3 as a fast import-graph smoke check.
- `git ls-files | wc -l` before/after, to quantify the tracked-file reduction.

## Phase 5 — break the backend/knowledge dependency cycle

### The problem

`backend/` and `knowledge/` import each other. 12 of the 18 cross-boundary imports are
written inside function bodies rather than at module top — the standard workaround for
`ImportError: partially initialized module`. Each deferred import is a patch over the
same structural break, applied one call site at a time. There is no layering, so there
is no mental model of what sits on top of what.

The root cause is one misfiled directory. `backend/tools/{coverage,demand,replay,analyses}.py`
are operator analysis tools, not serving code — verified: nothing in `backend/api`,
`backend/core`, `backend/db` or `backend/sync.py` imports them, while the pipeline, hub,
ledger and MCP server import `backend.tools.coverage` from six separate call sites.
They were filed under `backend/` because they read the serving database, but reading a
database does not make a module part of the server.

### Target layering

Dependencies flow one way only:

```
  ops/       hub, mcp, reports (coverage/demand/replay/analyses),
  layer 3    swap, remediate — operates and inspects the layers below
     |
     v
  backend/   sync ETL, api, resolver, db, matcher
  layer 2    ingests the catalog, serves risk to the extension
     |
     v
  knowledge/ catalog, extraction, ledger, parts, sources
  layer 1    produces the YAML catalog — imports nothing above it
```

`backend/` importing `knowledge/` stays legal and unchanged (layer 2 -> layer 1); it is
`knowledge/` reaching up into `backend/` that must stop.

### Moves

| From | To | Why |
|---|---|---|
| `backend/tools/{coverage,demand,replay,analyses}.py` | `ops/reports/` | operator tooling; unused by the serving path; source of 6 of the 11 deferred imports |
| `knowledge/hub/` | `ops/hub/` | operator web dashboard — layer 3 behaviour |
| `knowledge/mcp/` | `ops/mcp/` | operator control surface — layer 3 behaviour |
| `knowledge/ledger/{swap,remediate}.py` | `ops/` | acceptance-parity harness; needs `backend.api.main`, which only layer 3 may import |
| `knowledge/ledger/panel.py` | `ops/` | read-only pipeline + cost dashboard; imports `backend.tools.coverage`, so leaving it in layer 1 would make it import *upward into `ops/`* after the move — a worse violation than today's |
| `knowledge/process.py` | `ops/` | orchestrates `backend.sync` — layer 3 behaviour |
| `backend/core/title_sim.py` | `knowledge/title_sim.py` | pure string utility; `knowledge/dedup.py` needs `title_tokens`, and layer 1 may not import layer 2 |
| `backend/tests/test_{coverage_tool,demand,observability}.py` | `ops/tests/` | follow the code they cover |
| `knowledge/tests/test_ledger_{panel,swap,remediate}.py` | `ops/tests/` | follow the code they cover |

### Non-Python references that break (verified, all must be updated in the same commit)

These are invisible to import-graph analysis and each fails only at runtime:

1. **`.mcp.json:6`** — `"args": ["-m", "knowledge.mcp.server"]` becomes `ops.mcp.server`.
   This is how the kriko MCP server is wired into Claude Code; the server must be
   restarted after the change or its tools break mid-session.
2. **`opencode.json:6`** — hardcodes the same module path. Same edit.
3. **`package.json:6`** — the `npm test` glob `'knowledge/hub/tests/**/*.test.js'`
   becomes `'ops/hub/tests/**/*.test.js'`. Missing this silently stops running the hub
   tests rather than failing.
4. **`deploy/Dockerfile`** — copies a deliberate stdlib-only slice of `knowledge/`.
   `title_sim.py` moving into `knowledge/` requires a new
   `COPY knowledge/title_sim.py ./knowledge/title_sim.py` line, because
   `backend/core/resolver.py` and `backend/sync.py` both import it and both ship in the
   image. Without it the container builds clean and fails at request time.
   `backend/tools/` leaving `backend/` needs no Dockerfile change (line 10 copies
   `backend/` wholesale; the image simply gets smaller).
5. **Prose references** in `backend/api/main.py:160`, `backend/observability.py:9`,
   `backend/config.py:29`, `backend/sync.py:46` cite `backend/tools/...` paths in
   comments. Stale comments, not breakage, but updated with the move.

### Execution order

1. Create `ops/` with `__init__.py`; move `backend/tools/` -> `ops/reports/` via
   `git mv`, update the ~11 importers. Run suite.
2. Move `hub/` and `mcp/`; update `.mcp.json`, `opencode.json`, `package.json`. Run
   suite **and** `npm test`.
3. Move `swap.py`, `remediate.py`, `panel.py`, `process.py`; update importers including
   `knowledge/auto.py:273,358`. Run suite.
4. Move `title_sim.py`; update `backend/sync.py:26`, `backend/core/resolver.py:47`,
   `backend/tests/test_resolver_dedup.py:9`, `knowledge/dedup.py:11`; add the Dockerfile
   COPY line. Run suite.
5. Update the architecture section of `docs/INTERNALS.md` and the documentation map in
   `CLAUDE.md` to describe the three layers.

Each step is its own commit, gated on the full suite. `git mv` preserves history.

### Definition of done

- `grep -rnE "^[[:space:]]*(from|import) backend" --include='*.py' knowledge/` returns
  nothing. Both forms must be checked: `knowledge/ledger/swap.py:284` uses
  `import backend.sync as sync_mod`, which a `from backend`-only grep misses.
- Baseline for that grep today: **14 hits in `knowledge/` (11 of them deferred inside
  function bodies), plus 4 in `backend/` (1 deferred)** — 18 cross-boundary imports, 12
  of them cycle workarounds. Target: 14 -> 0 upward, 4 downward retained and hoisted to
  module top.
- 760 tests pass; `npm test` passes.
- `docker build -f deploy/Dockerfile .` succeeds and the built image can import
  `backend.core.resolver`.

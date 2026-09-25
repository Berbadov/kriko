> TL;DR (archived 2026-09-25): Design (2026-08-21, executed same day — five phases landed)
for repo disorder: commit the 50-file dirty tree in 6 commits (fixing the 760-passed/1-failed
baseline's comment-scanner harness bug), `git rm --cached` runtime artifacts (6.9 MB ledger.db,
7.8 MB `sahibinden_example/`), delete 7 dead leaf modules (21→13), move stale docs to
`docs/historical/`, then new Phase 5 breaking the backend↔knowledge import cycle via `ops/`
layering (one-way deps, `git mv`, Dockerfile/MCP/package.json reference fixes).

# Codebase organisation — design

**Date:** 2026-08-21 · **Branch:** `feat/agent-model-onboarding` · **Status:** executed 2026-08-21 — all five phases landed; see done.md · **Revised:** Phase 5 (dependency-cycle refactor) added same day.

## Problem

Five disorders: (1) `knowledge/` root: 21 loose modules (live code + spent one-offs, incl. two per-model patches violating `CLAUDE.md` generalisation); (2) `knowledge/ledger.db` tracked *and* gitignored — 6.9 MB binary re-diffs every commit (×3 recent); (3) ~50 uncommitted files across four features; (4) root clutter: `sahibinden_example/` (7.8 MB, 152 files, zero refs), `local.db`, `thoughts/`, root-owned `logs/`, un-ignored `.pytest_cache`; (5) four `CLAUDE.md`-marked-historical docs beside current ones.

## Baseline

`pytest -q` → **760 passed, 1 failed** (2026-08-21). The failure is a harness bug: `test_every_element_the_script_reaches_for_exists_on_the_page` regex-scans `hub.js` `$('#id')` selectors without stripping comments; `hub.js:7`'s illustrative `$('#missing')` comment trips it. Every phase must hold 760 passed and drive failures to zero.

## Non-goals

- No history rewrite (`git rm --cached` stops churn; blobs stay; pack-shrinking is separate).
- No *renames* (duplicate `discover.py`, vague `auto.py`/`process.py` stay — Phase 5 moves without renaming so moves stay greppable; renames are follow-up).
- Phases 1–4 change no import paths; Phase 5 isolates all churn. No big-file splits (`hub/web.py` 1151, `hover_lite.js` 1084, `hub.js` 935 — separate project). `.opencode/`/`opencode.json` untouched.

## Phase 1 — commit the dirty tree

Six commits, each diff read before staging (runtime artifacts excluded → Phase 2): (1) source tiers (`sources/tiers.py`, `catalog/source_tiers.yaml`, test); (2) catalog registry + generations; (3) part YAML v3 (`migrate_v3.py`, validator, 24 part YAMLs); (4) serving payload v2 (`main.py`, schemas, resolver, models, schema.sql, sync, gold/payload tests, fixtures, Dockerfile, INTERNALS); (5) hover_lite UI (js/css/risk_card); (6) hub picker + **comment-scanner fix** (strip `//` + `/* */` before scanning — keeps guard value, stops penalising comments). Split further if a group spans features.

## Phase 2 — git hygiene

`git rm --cached`: `knowledge/ledger.db`, `knowledge/hub/runs.jsonl`, `sahibinden_example/` (kept on disk + gitignored as scraper reference — not deleted). `.gitignore` += `.pytest_cache/`, `knowledge/catalog/cache/`, `runs.jsonl`, `sahibinden_example/`. (`local.db` already ignored.)

## Phase 3 — knowledge/ dead-code removal (21 → 13 modules)

Seven leaf modules, zero importers (apparent refs are self-docstring mentions); each imports *from* live code, imported *by* nothing: `downgrade_unsourced_claims`, `find_cross_file_duplicates` (existence called the symptom in `design_flaws.md:55`), `generalize_titles` (logic in extraction path), `merge_ea888_power_tunes` (**per-model patch**), `normalize_domains` (`domains.normalize_domain` is live), `fix_sibling_contamination` (**per-model patch**; `stoplists.mentions_sibling_code` live), `verify_agent` (`handover.md:4` says that flow is dead). Five were on the July ledger-plan delete list (half-executed). Retained 13 incl. `scaffold.py` (`README.md:153` still documents it — reconciling with historical `SCAFFOLD.md` is follow-up). Suite re-run: 760 pass.

## Phase 4 — docs and stale artifacts

1. `SCAFFOLD.md`, `handover.md` → `docs/historical/`. **Revised in execution:** `pipeline_postmortem.md` **stays** — marked historical but cited as live convention by `search_templates.py:54`, `test_langextract_client.py:3`, `design_flaws.md:155`.
2. Drop the dangling `kriko_build_plan.md` row from `CLAUDE.md`'s doc map (file doesn't exist); repoint the other three to `docs/historical/`.
3. `thoughts/` (6 files, 2026-07-05/22) → `docs/historical/thoughts/`. **Revised:** moved + re-pointed, not untracked — `done.md:316` cites the ledger-acceptance artefact, and untracking would dangle the citation.
4. Record in `done.md`.

## Verification

`pytest -q` after phases 1, 3, 4 (760/0); `git status --porcelain` empty (modulo ignored); import smoke (`knowledge.process/auto/extract`); `git ls-files | wc -l` before/after.

## Phase 5 — break the backend/knowledge dependency cycle

### The problem

18 cross-boundary imports (14 in `knowledge/` — 11 deferred in function bodies — plus 4 in `backend/`, 1 deferred), each a workaround for `partially initialized module`. Root cause: one misfiled directory — `backend/tools/{coverage,demand,replay,analyses}.py` are operator tools (nothing serving imports them; pipeline/hub/ledger/MCP import them from 6 sites) filed under `backend/` for reading the DB.

### Target layering

One-way layering — `ops/` (hub, mcp, reports, swap, remediate) → `backend/` (sync ETL, api, resolver, db, matcher) → `knowledge/` (catalog, extraction, ledger, parts, sources). `backend/`→`knowledge/` stays legal; `knowledge/`→`backend/` must stop.

### Moves

`git mv`, history preserved: `backend/tools/*` → `ops/reports/`; `knowledge/{hub,mcp}/` → `ops/`; `knowledge/ledger/{swap,remediate,panel}.py` → `ops/` (panel imports `backend.tools.coverage`, so staying would invert the violation); `knowledge/process.py` → `ops/` (orchestrates `backend.sync`); `backend/core/title_sim.py` → `knowledge/title_sim.py` (pure strings; layer 1 can't import layer 2); both sides' affected tests follow their code.

### Non-Python references that break (verified, all must be updated in the same commit)

`.mcp.json:6` + `opencode.json:6` module paths (`knowledge.mcp.server`→`ops.mcp.server`; restart the MCP server after); `package.json:6` test glob (`knowledge/hub`→`ops/hub`; missing it silently drops hub tests); `deploy/Dockerfile` gains `COPY knowledge/title_sim.py` (resolver + sync ship in-image and import it; builds clean, fails at request time without it); prose path comments in `main.py:160`, `observability.py:9`, `config.py:29`, `sync.py:46`.

### Execution order

(1) `backend/tools/`→`ops/reports/` + ~11 importers, suite; (2) hub + mcp + the three config files, suite + `npm test`; (3) swap/remediate/panel/process incl. `auto.py:273,358`, suite; (4) title_sim + 4 importers + Dockerfile line, suite; (5) INTERNALS architecture + CLAUDE.md doc map. Each step its own gated commit.

### Definition of done

`grep -rnE "^[[:space:]]*(from|import) backend" knowledge/` empty (check both import forms — `swap.py:284` uses `import backend.sync`); 14 upward → 0, 4 downward retained and hoisted to top; 760 + `npm test` green; image builds and imports `backend.core.resolver`.

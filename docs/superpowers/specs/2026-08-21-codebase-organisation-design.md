# Codebase organisation — design

**Date:** 2026-08-21
**Branch:** `feat/agent-model-onboarding`
**Status:** approved, pending execution

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
- No module relocation. Live modules stay at `knowledge/` root, so no import path
  changes anywhere.
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

1. `docs/historical/` gets the three self-declared-historical docs: `SCAFFOLD.md`,
   `handover.md`, `pipeline_postmortem.md`.
2. `CLAUDE.md`'s documentation-map table lists a fourth, `kriko_build_plan.md`, which
   does not exist anywhere in the tree — a dangling reference. Drop that row and
   update the other three to their new `docs/historical/` paths.
3. Retire `thoughts/` (6 files, all 2026-07-05/22, superseded by `docs/superpowers/`).
   Removed from git, kept on disk and gitignored.
4. Record the outcome in `done.md` per the project's tracking convention.

## Verification

- Full `pytest -q` after phases 1, 3 and 4 — 760 passed, 0 failed.
- `git status --porcelain` empty at the end, apart from deliberately ignored artifacts.
- `python -c "import knowledge.process, knowledge.auto, knowledge.extract"` after
  Phase 3 as a fast import-graph smoke check.
- `git ls-files | wc -l` before/after, to quantify the tracked-file reduction.

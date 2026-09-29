> TL;DR (archived 2026-09-25): Design (2026-08-29) diagnosing "too complicated" as Phase 6b
building the generic engine without wiring it (6 concerns with two implementations, generic at
zero callers; orphaned product-principle gate = live regression) plus an undefined pack
contract. Nine steps: collapse 5 forks, gates-as-pack-rows (the one behaviour change), pack
contract, dead-code audit (corrected 2026-08-30: none dead), break two giant `build()`s,
group the flat drawer, reading map, tidy. Baseline `f038df9`, 594 tests.

# Simplification and readability pass — design

**Date:** 2026-08-29 · **Branch:** `feat/knowledge-engine-pivot` · **Baseline:** `f038df9` (Phase 6b landed; 594 tests green, ~15s) · **Goal alignment:** G6 (category-free knowledge engine)

## Problem

"Too complicated and unorganised" + G6 ("adding a category is a data change") not true in practice — one cause: **Phase 6b built the generic engine correctly, wired none of it, left the pre-pivot forks running.**

### Evidence

Six concerns with two implementations (generic at **zero callers**): chunking, ingest, extraction (`kriko/ledger/*` vs `packs/cars/pipeline/ledger/*`); grounding (`kriko/extract/grounding.py` vs inline `quote not in document` + `app/mcp_server.py:291`); title similarity (`kriko/text/title_sim.py` vs verbatim `packs/…/title_sim.py`); claim gating (`kriko/gates.py` pack-rows vs orphaned 243-line `agent/gates.py`). Generics already take injected policy (`extractor=`, `signal_detector=`, `gate_reason=`).

Two consequences: (1) **green tests hide drift** — each copy has its own suite (same failure Phase 6c notes recorded); (2) **live regression** — the orphaned gate enforced the product principle at write time (warning lights, DTC litanies, ungrounded quotes) with no caller/test, so `submit_findings`' quote-presence check lets principle-violating evidence through.

### The pack contract is undefined

`packs/drill/` (5 YAML + README) vs `packs/cars/` (12,900 lines incl. `pipeline/`) — same word, two shapes, no required-minimum statement. G6 blocker and readability blocker at once (can't tell engine / contract / cars' business apart).

### What is *not* the problem

File size. `packstore.py` (518) and `stoplists.py` (536) are cohesive and stay. Real outliers: `packs/cars/build.py:357 build()` (457 lines) and `kriko/pack/build.py:168 build()` (300).

## Non-goals

Four-layer fan (`app/` → `kriko/` ← `packs/`) stays (this pass makes it *true*); `packstore.py`/`stoplists.py` untouched; extension untouched; P0/P1 claim-quality backlog (B16, B11, B19, B5) untouched; no behaviour change except step 3.

## Plan

Nine steps, one commit each against a green suite. Steps 1–4 pivot work; 5–9 readability.

### 1. Land Phase 6b — DONE (`f038df9`)

Readable-diffs baseline, 594 green.

### 2. Collapse the five forks

Each becomes a thin caller passing cars policy as args: ledger `{chunking,ingest,extraction}` call `kriko/ledger/*`; `mcp_server.py` uses `is_grounded`; `title_sim.py` deleted for `kriko/text/title_sim.py`. Proves the generic path (only real pack uses it); ~350 duplicated lines gone; behaviour unchanged (parity harnesses green).

### 3. Gating becomes pack data, and gets wired in

Cars' Python gate vocabulary → `packs/cars/vocabulary/gates.yaml` rows; `submit_findings` calls `gate_reason` + `is_grounded`; `agent/gates.py` deleted once expressed as rows. **The one intended behaviour change** (agent path rejects low-value findings again) — own commit + own tests (incl. warning-light refusal with actionable reason). **Fail-open preserved:** no `gate_terms` rows ⇒ gates nothing (`kriko/gates.py` contract, CLAUDE.md automation principle).

### 4. Write the pack contract

`docs/PACK_CONTRACT.md` (required minimum vs optional `pipeline/`), enforced by a test both packs satisfy (can't drift). Minimum per `manifest.py`: `pack.toml` `[pack]` id/name/version + `[identity]` (≥1 subject kind with identity keys — else all subjects hash alike) + `data/`. Optional: `vocabulary/`, `research/`, `trust/`, `adapters/`, `build.py`, `pipeline/`, `coverage.py` (`drill/` = minimum-plus-vocabulary; `cars/` = everything). Makes scope landable by non-authors.

### 5. Delete confirmed dead code — RESULT: THERE IS NONE

**Corrected 2026-08-30.** Original claim (`model_state.py` zero-refs) was wrong — it has `test_model_state.py` (11 tests); the grep searched the dotted path, which can't match `from … import model_state`. Proper re-run (all import styles, no test-dir filter, entry-point + doc-mention detection): **no dead modules** — candidates are pytest-discovered tests or `python -m` entry points from `docs/USAGE.md`/docstrings. Earlier "14 modules" figure = "no *production* importer", a much weaker claim. Alive-and-kept: `catalog/doctor.py`, `fitment/validate_fitment.py`, `pipeline/scaffold.py`, `ledger/eval_verdict.py`, `repair_missing_stub_scaffold.py`.

### 6. Break the two giant build functions

Both `build()`s become named-stage sequences; pure extraction, no behaviour change.

### 7. Group the flat drawer

`packs/cars/pipeline/`'s 14 loose modules into `claims/` (ground_year_window, ground_mileage_threshold, consequence_tier, maintenance, dedup) + `util/` (paths, yamlutil, domains). Mechanical moves; membership confirmed against imports.

### 8. Reading map

`docs/ARCHITECTURE.md`, one human-first page (start points, package ownership, entry points, "chasing X? read these three files").

### 9. Repo tidy

Drop empty `deploy/`; reconcile stale `USAGE.md` refs; update `backlog.md` + `done.md`.

## Readability targets

No function over ~80 lines (outside tests); one-line "what this owns" docstring per module; every public surface reachable from `ARCHITECTURE.md`; no concern twice-implemented.

## Verification

Suite green per step (~15s, cheap); `test_pack_parity.py` + `ledger/parity.py` stay green (behaviour proof for steps 2, 6, 7); `test_repo_invariants.py` layering greps + `backend/` ratchet green; step 3 alone may change behaviour (new rejection tests).

## Risks

Over-gating drops good findings (fail-open contract; kept-claim tests; own revertable commit) | Python judgement inexpressible as rows (keep as pack-supplied callable, discovered in step 3) | ledger parity breaks (abandon per-module) | grouping churns imports for little gain (mechanical, last, droppable).

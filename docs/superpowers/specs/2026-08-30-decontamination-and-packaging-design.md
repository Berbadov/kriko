> TL;DR (archived 2026-09-25): Design (2026-08-30) for the repository reading cars-first
despite category-free code: 23 car-shaped comments/docstrings (one mangled `sed` line),
car-only engine tests, 50 archaeology refs, no packaging, stale README/front door. Six parts:
`src/` layout + `pyproject.toml`, docs currency, ~120-line README, prose decontamination with a
failing-first domain-free gate, archaeology removal, second-category fixtures. Baseline
`c1c88d2`, 605 tests; fan unchanged, no behaviour changes.

# Decontamination and packaging — design

**Date:** 2026-08-30 · **Branch:** `feat/knowledge-engine-pivot` (pushed; 26 simplification commits merged) · **Baseline:** `c1c88d2`, 605 tests green · **Goal alignment:** G6 (cars is pack #1)

## Problem

Simplification made the code category-free, not the *repository* (now public on GitHub). Four suite-invisible gaps:

### 1. The engine explains itself in cars

Zero car logic in `kriko/` (AST-enforced), but 23 comments/docstrings explain generic mechanisms through cars only — plus one broken `sed`-mangled sentence (`lookup/__init__.py:6`: "together held 876 lines of car packs.cars.pipeline…"). A dishwasher-pack author reading `lookup/conditions.py` ("five car-specific compatibility checks"), `match.py`, `research/__init__.py` concludes "car tool, generic veneer". Worse than car *code* — no test sees prose.

### 2. The engine proves its generality using only cars

14 car references in `kriko/`'s own tests (`test_ids.py` has 10) — Renaults/Volkswagens demonstrating "works for any category" is assertion, not proof.

### 3. Fifty pieces of archaeology

"Old pipeline / used to live / before the pivot / legacy" — meaningful to the author, noise to strangers, and they date files. Worst: `packs/cars/pipeline/requirements.txt` (functional!) points at deleted `knowledge/requirements.txt` with annotations to non-existent modules.

### 4. The repository is not packaged, and its front door is stale

No `pyproject.toml` (un-installable); 247-line insider README with a duplicated-`kriko/` `File layout` block; three untouched-since-2026-06-29 pre-pivot planning docs beside current ones, unmarked.

## Non-goals

Dependency fan unchanged (packaging *above* it, prose *inside* it — no boundary redrawn; two tests enforce); no behaviour changes (prose/packaging/fixtures only); INTERNALS/USAGE keep scope (stale refs corrected); eight long functions (B37) stay long.

## Plan

Six parts, own commits, in order. Parts 1–3 structural first (prose then describes the final layout).

### 1. `src/` layout and `pyproject.toml`

`src/kriko/` + `src/app/`; `packs/`, `extension/`, `docs/` stay at root — **packs are content shipped as one `.kpack`, not library code** (under `src/` they'd claim installable-distribution status and force package-data config). Cheap too: 7 of 11 root-walking path computations live in `packs/` and stay correct; four break (+1 `.parent` each: `panel.py:32`, `remediate.py:39`, `test_repo_invariants.py:12`, `test_pack_contract.py:14`). `pyproject.toml`: Python 3.14 (CI), runtime deps actually imported (`fastapi`, `mcp`, `pydantic`, `pyyaml`, `uvicorn`); heavy pipeline deps (`langextract`, `mistralai`, `trafilatura`, `yt-dlp`, `selectolax`, `exa-py`, `anthropic`, `textual`) become an optional build-only extra. `pytest.ini` testpaths + CI updated.

### 2. `docs/` states which documents are current

`overhaul_plan.md`, `claim_relevance_plan.md`, `pipeline_postmortem.md` → `docs/historical/` (exists for this; labelled); two live referrers each updated to say historical. `design_flaws.md` **stays** (four live refs + open B13).

### 3. `README.md` rewritten for a cold reader

Target ~120 lines: what it is + the one question it answers; **one real ranked-claim example** (current README never shows the product); fewest working install/run commands; what a pack is + the two shipped ones (`PACK_CONTRACT.md`); links out (ARCHITECTURE, CLAUDE.md, CONTRIBUTING). `Design principles` → link (not CLAUDE.md duplicate); `File layout` → pointer (deletes the duplicated-`kriko/` bug instead of fixing it twice).

### 4. Decontaminate the engine's prose, and enforce it

Rewrite the 23 car-shaped comments/docstrings (generic rule first; a genuinely clarifying category example — e.g. `adapters.py`'s "148.000 km" separator case — may follow as illustration, never definition). Repair the mangled sentence. **Enforcement:** `test_core_is_domain_free.py` walks docstrings/comments against the same banned vocabulary, with a named file+term allowlist (every exception a visible decision). **Fails CI** — a gate, not a report. `app/` same bar, except `app/pipeline/` drives the cars pipeline by design (car names correct there; only generic-mechanism-through-cars prose goes).

### 5. Remove the archaeology

All 50 go; non-obvious-choice survivors become one `# History:` constraint line, not narrative. `requirements.txt` rewritten or deleted (record which).

### 6. The engine's tests prove generality with a second category

Engine fixtures move off cars (`packs/drill/` vocabulary as the falsifier; two categories where identity/union is under test). Assertions unchanged. `packs/cars/**/tests/` keep car fixtures (they test cars).

## Verification

605 green per part (`.venv/bin/python -m pytest -o addopts="" -q`); part 1: `app.cli`, `packs.cars.build`, web app start + `pip install -e .`; part 4: gate demonstrated to fail on a planted car term; part 6: no car vocab in `kriko/tests/` off-allowlist; layering greps + invariants green.

## Risks

Missed `__file__` path breaks at runtime only (four known sites; run every entry point) | docstring gate too strict (allowlist seeded same commit) | fixture rewrite weakens coverage (assertions frozen; changed assertions get reported) | prose work drifts into behaviour (comments/docstrings only — executable diff lines are review findings) | wrong dep split (derive from imports; clean-venv install + start each entry point).

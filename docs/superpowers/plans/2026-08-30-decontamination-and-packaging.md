> TL;DR (archived 2026-09-25): 7 tasks making the repo read as a category-free engine with cars
as pack #1: `src/` layout + `pyproject.toml`, docs currency (`overhaul/claim_relevance/postmortem`
to `docs/historical/`), README rewrite, domain-free prose gate, 23 car-shaped comments fixed,
50 archaeology refs removed, engine tests moved off car fixtures.
> Baseline `c1c88d2`, 605 tests, no behaviour changes, dependency fan untouched. Full file dumps trimmed below — see git history.

# Decontamination and Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository read the way the code already behaves — a category-free knowledge engine with cars as pack #1 — and make it installable.

**Architecture:** Tasks 1–3 are structural (packaging, docs, README) and land first so later prose describes the final layout. Task 4 extends the domain-free gate to prose and **fails**, producing the offence list. Tasks 5–6 fix that prose. Task 7 moves the engine's test fixtures off cars. The dependency fan is untouched throughout.

**Tech Stack:** Python 3.14, pytest, `ast` + `tokenize` (comments are *not* in the AST), tomllib/pyproject, SQLite, FastAPI, PyYAML.

**Spec:** `docs/superpowers/specs/2026-08-30-decontamination-and-packaging-design.md`

## Global Constraints

- Tests: `.venv/bin/python -m pytest -o addopts="" -q` (`-o addopts=""` required — `pytest.ini` already sets `-q`; bare `python` does not exist). Baseline: **605 passed, ~26s**.
- **Dependency fan unchanged** (`app/` → `kriko/` ← `packs/`). Never weaken `test_repo_invariants.py` to pass.
- **No behaviour changes.** Packaging, prose, fixtures only — an executable change in a prose diff is a review finding.
- **`packs/` stays at root** (content shipped as `.kpack`, not library code). Only `kriko/` and `app/` move under `src/`.
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Push to `feat/knowledge-engine-pivot` authorised; do not merge to main. Baseline commit: `d3cbe6f`.

---

## File Structure

**Created:** `pyproject.toml` (metadata, Python floor, runtime deps, optional `pipeline` extra).

| From | To |
|---|---|
| `kriko/` | `src/kriko/` |
| `app/` | `src/app/` |
| `docs/overhaul_plan.md` | `docs/historical/overhaul_plan.md` |
| `docs/claim_relevance_plan.md` | `docs/historical/claim_relevance_plan.md` |
| `docs/pipeline_postmortem.md` | `docs/historical/pipeline_postmortem.md` |

**Substantially rewritten:** `README.md` (247 → ~120 lines); `test_core_is_domain_free.py` (gate extended to prose); `packs/cars/pipeline/requirements.txt` (rewritten or deleted).

---

### Task 1: `src/` layout and `pyproject.toml`

**Files:** create `pyproject.toml`; move `kriko/`→`src/kriko/`, `app/`→`src/app/`; modify `pytest.ini`, `ci.yml`; one extra `.parent` in `app/pipeline/{panel.py:32,remediate.py:39}`, `test_repo_invariants.py:12` (×4→×5), `test_pack_contract.py:14` (`parents[2]`→`parents[3]`).
**Interfaces:** import paths **unchanged** once installed / `src/` on path — every later task depends on this.

- [ ] **Step 1: Baseline** — suite → `605 passed`; all of `app.cli app.mcp_server app.web packs.cars.build packs.cars.coverage` importable (`OK`). Write both down; Step 8 compares.
- [ ] **Step 2: `git mv`** the two packages (renames keep the diff readable).
- [ ] **Step 3: `pyproject.toml`** — deps derived from actual imports (`grep -rhoE "^(import|from) [a-z_]+" src/kriko src/app`): `fastapi`, `mcp`, `pydantic`, `pyyaml`, `uvicorn`. Full TOML — see git history. Check `license` against a real `LICENSE` file; ask if none.
- [ ] **Step 4: Fix the four path computations** (+1 `.parent` each). Verify by printing, not reasoning: import each module / run its test and confirm the computed root contains `packs/` + `README.md` (a wrong root imports clean and fails later — the failure this step prevents).
- [ ] **Step 5: `pytest.ini`** — `testpaths = src/kriko src/app packs`; keep the comment on explicit paths.
- [ ] **Step 6: CI** — replace dep install with `pip install -e ".[dev,pipeline]"`; match `ci.yml`'s unusual indent exactly.
- [ ] **Step 7: Clean-install check** — `pip install -e .`, then `kriko.__file__` / `app.__file__` must resolve under `src/`.
- [ ] **Step 8: Entry points + suite** — all modules `OK`, **605 passed**, identical to Step 1.
- [ ] **Step 9: Commit** — `build: src/ layout and a pyproject, so Kriko can be installed` (`packs/` deliberately excluded: a pack is content, not distribution).

---

### Task 2: `docs/` says which documents are current

**Files:** move the three pre-pivot docs → `docs/historical/`; modify live documents referencing them.
**Interfaces:** none. Task 3's README table depends on final locations.

- [ ] **Step 1: Find references first** (per-doc grep over `*.md`, excluding `node_modules` + `docs/historical/`). Expect ~2 live hits each for the moved three, ~4 for `design_flaws`.
- [ ] **Step 2: `git mv`** the three. **`design_flaws.md` stays** (touched 2026-08-21, four live refs, backs open B13).
- [ ] **Step 3: Repoint + reword** — new path `docs/historical/<name>.md`; where prose implies currency, say historical (the directory warning already says "don't follow").
- [ ] **Step 4: Confirm** — old-path grep (excluding historical + superpowers archival records) → no output.
- [ ] **Step 5: Suite + commit** — `docs: move the pre-pivot planning documents into historical/`.

---

### Task 3: `README.md` for someone who has never seen this project

**Files:** rewrite `README.md` (~120 lines).
**Interfaces:** consumes Task 1 layout + Task 2 locations; produces nothing importable.

- [ ] **Step 1: Capture real output** — build/install cars pack, run a lookup, use the genuine result. **Never invent a sample** (a fabricated README example is the most damaging false documentation). If the CLI cannot drive a lookup, report it and use the smallest real thing.
- [ ] **Step 2: Write it** — (1) what it is + local-first (keep existing opening); (2) the real output block (the missing section); (3) install/run, fewest verified-working commands; (4) what a pack is + `cars`/`drill` + `PACK_CONTRACT.md`; (5) next-steps table (ARCHITECTURE, CLAUDE.md, CONTRIBUTING, backlog). Delete `Design principles` (link CLAUDE.md) and `File layout` (ARCHITECTURE.md owns it; current block lists `kriko/` twice). Keep `Supported cars (TR market)`.
- [ ] **Step 3: Verify** — path-extraction script → `MISSING: none`; run every command yourself (a broken command is worse than an omitted one).
- [ ] **Step 4: Suite + commit** — `docs: a README for someone who has never seen this project`.

---

### Task 4: Extend the domain-free gate to prose — and watch it fail

Modify `src/kriko/tests/test_core_is_domain_free.py`. Produces `ALLOWED_PROSE: dict[str, set[str]]` (Task 5 populates it). **Ends red on purpose** — the failure list is Task 5's work queue. Fix no prose here.

- [ ] **Step 1: Note what reverses** — module docstring ("prose deliberately exempt… history worth keeping") + `test_the_guard_actually_catches_something`'s docstring exemption. Both must change or the test contradicts itself.
- [ ] **Step 2: Comments need `tokenize`** — `ast` discards comments (not nodes); docstrings are `ast.Constant` (existing `_docstring_nodes()` covers them). New `_comments()` via `tokenize.generate_tokens` → `(lineno, text)`. Full helper — see git history.
- [ ] **Step 3: Prose scan + allowlist** — empty `ALLOWED_PROSE` + `_prose_offences()` reporting docstrings/comments separately (works via `_split_identifier`, which lowercases/splits any text). Full code — see git history.
- [ ] **Step 4: Gate test** — `test_the_engine_does_not_explain_itself_in_one_category`. Full test — see git history.
- [ ] **Step 5: Invert the exemptions** — docstring now says prose is checked; old `_offences` assertion stays true for `_offences`, plus a companion asserting `_prose_offences` catches the same docstring (both halves pinned).
- [ ] **Step 6: Capture the failure** — targeted pytest → **FAIL**, ~23 offences across `lookup/`, `adapters.py`, `research/`, `text/` (`tee /tmp/prose-offences.txt`).
- [ ] **Step 7: Commit red** — `test(gates): the domain-free guard now reads the prose too, and it fails` (offence list belongs in history, not a scratch file).

---

### Task 5: Decontaminate the engine's prose

**Files:** every file in Task 4's list (expect `lookup/{__init__,match,conditions,query}.py`, `adapters.py`, `research/__init__.py`, `text/title_sim.py`) + `test_core_is_domain_free.py` (`ALLOWED_PROSE`).
**Interfaces:** consumes `ALLOWED_PROSE`; produces a green prose test. Rule: **generic mechanism first**; a clarifying category example follows only into the allowlist.

- [ ] **Step 1: Repair `lookup/__init__.py:6` first** (`"together held 876 lines of car packs.cars.pipeline…"` — mangled `sed` output in the central module's docstring; write a sentence true of the current code).
- [ ] **Step 2: Rewrite each offence** — e.g. `conditions.py:3` → "one evaluator handles every pack-declared condition (usage thresholds, time windows, configuration compatibility), returning met/unmet/unknown". Judgement calls (make, don't ask): `adapters.py`'s "148.000 km" stays (real parsing hazard → allowlist as locale-formatting instance); `conditions.py:16`'s mileage-less-ad either generalises or allowlists — record the choice.
- [ ] **Step 3: Populate `ALLOWED_PROSE`** — every entry carries a *why* comment (an unexplained entry is a way of silencing the test).
- [ ] **Step 4: Gate green** — both executable and prose checks PASS.
- [ ] **Step 5: Prove no code changed** — added non-comment/non-docstring lines must be only `ALLOWED_PROSE` entries; anything else in `src/kriko/` is a behaviour change — revert.
- [ ] **Step 6: Suite (605 + prose test) + commit** — `docs(engine): the engine stops explaining itself in one category`.

---

### Task 6: Remove the archaeology, repo-wide

**Files:** ~50 sites across `src/kriko/`, `src/app/`, `packs/`; rewrite/delete `packs/cars/pipeline/requirements.txt`.
**Interfaces:** none.

- [ ] **Step 1: Find all** (`the old (pipeline|code|serving|path|system)|used to (live|be|hard-code)|before the pivot|legacy`) — expect ~50, tests included.
- [ ] **Step 2: Decide each** — (1) **Delete** (explains nothing without the deleted code — most); (2) **Rewrite** (dates current behaviour → state it); (3) **Keep as one `# History:` line** (non-obvious constraint only). Test: would a reader new to the code be confused without it?
- [ ] **Step 3: `app/` bar with one exception** — `app/pipeline/` drives the cars pipeline by design (car names stay where they describe that work); `app/web/routers/`, `mcp_server.py` serve any pack (generic prose only).
- [ ] **Step 4: `requirements.txt`** — points at deleted `knowledge/requirements.txt` with dead annotations; it is *functional*. Delete if `pip install -e ".[pipeline]"` fully replaces it (grep referencers first), else rewrite against the real tree. Report the choice.
- [ ] **Step 5: Prove no code changed** (added non-comment lines must be requirements/pyproject only).
- [ ] **Step 6: Suite + commit** — `docs: delete the archaeology`.

---

### Task 7: The engine's tests prove generality with a second category

**Files:** `src/kriko/tests/test_{ids,adapters,research,packstore}.py` + whatever the Step 1 scan names. **Fixtures change; assertions do not** — an assertion that must change was coupled to car semantics: **report it, don't edit it**.
**Interfaces:** consumes `packs/drill/` vocabulary (no engine/fuel/displacement; wear in charge cycles — use its real terms, never invented ones).

- [ ] **Step 1: Scan** (`megane|golf|clio|renault|volkswagen|dsg|tdi|tsi|dci|k9k|ea888|dq200|gearbox|mileage`) — expect ~14 hits, ten in `test_ids.py`.
- [ ] **Step 2: Read the drill pack** (`pack.toml`, `data/subjects.yaml`, `vocabulary/terms.yaml`) — brand, model line, battery platform, charge cycles.
- [ ] **Step 3: Convert file by file** (`test_ids.py` first — identity hashing is where "same product" lives), running each after; same assertions.
- [ ] **Step 4: Two categories where the test crosses them** — union/collision tests must use two distinct kinds of object (that is the claim under test).
- [ ] **Step 5: Confirm** — car-word grep → empty, except a test deliberately about two categories that says so. (`packs/cars/**/tests/` keep car fixtures — untouched.)
- [ ] **Step 6: Suite (605 + prose test, none lost) + commit** — `test(engine): the engine's own tests stop proving generality with cars`.
- [ ] **Step 7: `git push`** (tracking `origin/feat/knowledge-engine-pivot` authorised; no merge to main).

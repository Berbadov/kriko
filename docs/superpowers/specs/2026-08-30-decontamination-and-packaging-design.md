# Decontamination and packaging — design

**Date:** 2026-08-30
**Branch:** `feat/knowledge-engine-pivot` (pushed; 26 commits of the simplification pass merged in)
**Baseline:** `c1c88d2`, 605 tests green
**Goal alignment:** G6 — Kriko is a category-free knowledge engine; cars is pack #1

## Problem

The simplification pass made the code category-free. It did not make the
*repository* read that way, and a repository is now what people see: the branch
is on GitHub.

Four gaps, all invisible to the test suite:

### 1. The engine explains itself in cars

`kriko/` contains **zero** car logic — `kriko/tests/test_core_is_domain_free.py`
walks its AST and enforces that. But 23 production comments and docstrings
explain generic mechanisms exclusively through cars, and one is outright broken:

```
kriko/lookup/__init__.py:6
"together held 876 lines of car packs.cars.pipeline. Nothing here knows
 what a car is; the..."
```

That is a `sed` rewrite from an earlier rename, mangled and unreviewed, sitting
in the docstring of the engine's central module.

This is worse than car *code* would be, because no test can see it. Someone
arriving to write a pack for dishwashers reads `lookup/conditions.py` ("the five
car-specific compatibility checks"), `match.py` ("dropping the car entirely
served nothing"), `research/__init__.py` ("every car-specific thing the old
pipeline hard-coded") and reasonably concludes the engine is a car tool with a
generic veneer. The code says category-free; the prose says cars.

### 2. The engine proves its generality using only cars

`kriko/`'s own tests carry 14 car references across four files —
`test_ids.py` alone has 10. The suite that exists to demonstrate the engine works
for any category demonstrates it exclusively with Renaults and Volkswagens. That
is an assertion, not a proof.

### 3. Fifty pieces of archaeology

Production code carries **50** instances of "the old pipeline", "used to live",
"before the pivot", "legacy". Meaningful to the author, meaningless to a
stranger, and they date a file rather than explaining it.

`packs/cars/pipeline/requirements.txt` is the worst case because it is
*functional*: it instructs the reader to `pip install -r knowledge/requirements.txt`
— a path deleted two passes ago — and annotates dependencies with `ops/hub/web.py`,
`ops/mcp/server.py`, `knowledge/extract.py`, `forums.py`, `specialists.py`, none
of which exist.

### 4. The repository is not packaged, and its front door is stale

No `pyproject.toml`; Kriko cannot be installed. `README.md` is 247 lines written
for someone who already knows the project, and its `File layout` block lists
`kriko/` **twice** — a copy-paste error in the section a new reader trusts most.
Three planning documents untouched since 2026-06-29, from before the pivot, sit
in `docs/` beside current ones with nothing marking them stale.

## Non-goals

- **The dependency fan does not change.** `app/` → `kriko/` ← `packs/` is the G6
  invariant, enforced by two tests, and it just passed a 14-task review. This
  design adds a packaging layer above it and rewrites prose inside it. It does
  not redraw a single boundary.
- No behaviour changes. Every part of this is prose, packaging, or test fixtures.
- `docs/INTERNALS.md` and `docs/USAGE.md` keep their scope; only their stale
  references are corrected.
- The eight long functions (backlog B37) stay long.

## Plan

Six parts, each its own commit, in this order. Parts 1–3 are structural and must
land before the prose work so the prose describes the final layout.

### 1. `src/` layout and `pyproject.toml`

```
src/kriko/     the engine
src/app/       interfaces
packs/         stays at the root
extension/     stays
docs/          stays
pyproject.toml NEW
```

**`packs/` deliberately stays out of `src/`.** Packs are content, not library
code — `docs/PACK_CONTRACT.md` defines a pack as a directory authored by a third
party and shipped as one `.kpack` file. Placing them under `src/` would claim
they are part of the installable distribution, contradict that model, and force
package-data configuration to ship their YAML.

It is also far cheaper. Eleven path computations walk up to the repository root;
**seven are inside `packs/`** and stay correct untouched. Four break and each
needs one additional `.parent`:

| file | current |
|---|---|
| `app/pipeline/panel.py:32` | `Path(__file__).resolve().parent.parent.parent` |
| `app/pipeline/remediate.py:39` | `Path(__file__).resolve().parent.parent.parent` |
| `app/pipeline/tests/test_repo_invariants.py:12` | `.parent` × 4 |
| `kriko/tests/test_pack_contract.py:14` | `Path(__file__).resolve().parents[2]` |

`pyproject.toml` declares Python 3.14 (matching CI) and the runtime dependencies
the engine and interfaces actually import — `fastapi`, `mcp`, `pydantic`,
`pyyaml`, `uvicorn`. The pipeline's heavier dependencies (`langextract`,
`mistralai`, `trafilatura`, `yt-dlp`, `selectolax`, `exa-py`, `anthropic`,
`textual`) become an optional extra, since they are needed only to *build*
knowledge, never to read it.

`pytest.ini`'s `testpaths` and the CI workflow update to match.

### 2. `docs/` states which documents are current

`overhaul_plan.md`, `claim_relevance_plan.md` and `pipeline_postmortem.md` move
to `docs/historical/`, which exists for exactly this and is already labelled
"historical context only; don't follow their instructions". Each is referenced
from two live documents; those references update to the new path and say the
document is historical.

`design_flaws.md` **stays** — it is referenced by four live documents and by open
backlog item B13.

### 3. `README.md` rewritten for a cold reader

Target ~120 lines, for someone who has just found Kriko on GitHub and knows
nothing:

1. What it is and the one question it answers.
2. **One concrete example of real output** — an actual ranked claim for an actual
   listing. The current README describes the idea but never shows the product.
3. Install and run, in the fewest commands that work.
4. What a pack is, and the two shipped ones, linking `docs/PACK_CONTRACT.md`.
5. Links out: `docs/ARCHITECTURE.md` as the way into the code, `CLAUDE.md` for
   principles, `CONTRIBUTING.md` for contributing.

The `Design principles` section becomes a link rather than a duplicate of
`CLAUDE.md`. The `File layout` block is replaced by a pointer to
`docs/ARCHITECTURE.md`, which already carries a verified package table — deleting
the duplicated-`kriko/` bug rather than fixing it twice.

### 4. Decontaminate the engine's prose, and enforce it

Rewrite the 23 car-shaped comments and docstrings in `kriko/` so each states the
generic rule first. A category example may follow when it genuinely clarifies —
`adapters.py`'s "148.000 km" thousand-separator case earns its place — but as an
illustration, never as the definition.

`kriko/lookup/__init__.py:6`'s mangled sentence is repaired.

**Enforcement:** `kriko/tests/test_core_is_domain_free.py` is extended to walk
docstrings and comments in `kriko/`, not only executable positions, against the
same banned vocabulary. Deliberate illustrations are permitted through an
explicit allowlist that names the file and the term, so every exception is a
visible decision rather than an oversight. **This test fails CI**; it is a gate,
not a report.

`app/` is held to the same bar with one distinction: `app/pipeline/` drives the
cars pipeline and imports `packs.cars.pipeline` by design, so naming cars where
it genuinely describes that work is correct and stays. What goes is prose that
explains a **generic** mechanism through cars alone.

### 5. Remove the archaeology

The 50 "the old X" references go. Where one explains a non-obvious choice, it
survives as a single `# History:` line stating the constraint rather than the
narrative.

`packs/cars/pipeline/requirements.txt` is rewritten against reality, or deleted
if `pyproject.toml`'s optional extra fully replaces it — decide during
implementation and record which.

### 6. The engine's tests prove generality with a second category

`kriko/`'s own tests move their fixtures off cars. The engine's suite should
demonstrate that a subject is a subject whether it has an engine code or a
charge-cycle count; using only cars makes the central claim untestable by
construction.

`packs/drill/` already exists as the car-shape falsifier and its vocabulary is
the natural source. Where a test needs two distinct categories — identity
hashing, cross-pack union — it should use two.

`packs/cars/tests/` and `packs/cars/pipeline/tests/` keep their car fixtures;
they are testing the cars pack, where cars are the subject.

## Verification

- 605 tests green after every part. Command: `.venv/bin/python -m pytest -o addopts="" -q`
  (`pytest.ini` sets `-q`, so a plain `-q` suppresses the count).
- After part 1: `python -m app.cli`, `python -m packs.cars.build` and the web app
  all still start, and `pip install -e .` succeeds.
- After part 4: the extended domain-free test fails when a car term is added to a
  `kriko/` docstring — demonstrated, not assumed.
- After part 6: no car vocabulary remains in `kriko/tests/` outside the allowlist.
- Both layering greps from `CLAUDE.md` stay silent; `test_repo_invariants.py`
  stays green.

## Risks

| Risk | Mitigation |
|---|---|
| A missed `__file__` path breaks only at runtime | The four known sites are listed; part 1 ends by running every entry point, not just the suite |
| The docstring gate is too strict and blocks legitimate examples | The allowlist is part of the same commit, seeded with the examples worth keeping |
| Part 6 rewrites working tests and weakens coverage | Fixtures change, assertions do not; any test whose *assertion* needs changing is reported rather than edited |
| Prose rewriting drifts into behaviour change | Parts 4 and 5 touch comments and docstrings only; any executable change in those diffs is a review finding |
| `pyproject.toml` dependency split is wrong | Derived from actual imports in `kriko/` and `app/`, verified by installing into a clean venv and starting each entry point |

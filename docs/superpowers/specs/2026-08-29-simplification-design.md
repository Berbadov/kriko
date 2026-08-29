# Simplification and readability pass — design

**Date:** 2026-08-29
**Branch:** `feat/knowledge-engine-pivot`
**Baseline:** `f038df9` (Phase 6b landed; 610 tests green, ~15s)
**Goal alignment:** G6 (Kriko becomes a category-free knowledge engine)

## Problem

Two complaints, one cause.

The stated complaint is that the codebase is "too complicated and unorganised"
to read and investigate. The structural complaint is that G6 — adding a product
category must be a data change — is not yet true in practice.

Both come from the same fact: **Phase 6b built the generic engine layer
correctly, wired none of it, and left the pre-pivot forks running.**

### Evidence

Six concerns now have two implementations. The generic one has **zero callers**;
the fork is what actually runs.

| Concern | Generic (built, 0 callers) | Fork still in use |
|---|---|---|
| Chunking | `kriko/ledger/chunking.py` | `packs/cars/pipeline/ledger/chunking.py` |
| Ingest | `kriko/ledger/ingest.py` | `packs/cars/pipeline/ledger/ingest.py` |
| Extraction | `kriko/ledger/extraction.py` | `packs/cars/pipeline/ledger/extraction.py` |
| Grounding | `kriko/extract/grounding.py` | inline `quote not in document`, `app/mcp_server.py:291` |
| Title similarity | `kriko/text/title_sim.py` | `packs/cars/pipeline/title_sim.py` (verbatim logic) |
| Claim gating | `kriko/gates.py` (pack rows) | `packs/cars/pipeline/agent/gates.py` (orphaned, 243 lines) |

The generic versions already accept injected policy
(`extractor=`, `signal_detector=`, `gate_reason=`). The forks exist only because
nobody did the second half of the move.

Two consequences follow:

1. **Green tests hide it.** Each copy has its own suite, so both pass while
   drifting apart. This is the same failure the Phase 6c notes recorded — "every
   suite built its own fixture and the one pack that ships was never built in CI".
2. **A live regression.** `packs/cars/pipeline/agent/gates.py` enforces the
   CLAUDE.md product principle at write time (rejecting warning-light items, DTC
   litanies, ungrounded quotes). It has no caller and no test.
   `app/mcp_server.py`'s `submit_findings` checks only that the quote appears in
   the document, so the agent research path currently writes evidence the product
   principle says to drop.

### The pack contract is undefined

`packs/drill/` is five YAML files and a README. `packs/cars/` is 12,900 lines
including a whole `pipeline/`. Same word, two shapes three orders of magnitude
apart, and nothing states which parts are required. A third-party pack author has
no contract to write against — only two examples that disagree.

This is simultaneously the G6 blocker and the reason the tree is hard to read:
you cannot tell what is engine, what is pack contract, and what is merely cars'
own business.

### What is *not* the problem

File size was the wrong metric. `kriko/store/packstore.py` (518 lines) and
`packs/cars/pipeline/stoplists.py` (536) are each 17–21 small, well-named
functions on one cohesive topic. They are fine and stay untouched.

The real outliers are two functions:

| Function | Lines |
|---|---|
| `packs/cars/build.py:357 build()` | 457 |
| `kriko/pack/build.py:168 build()` | 300 |

## Non-goals

Out of scope for this pass, explicitly:

- The four-layer fan (`app/` → `kriko/` ← `packs/`). It is the right split; this
  pass makes it *true*, not different.
- `packstore.py`, `stoplists.py` — cohesive, leave them.
- The Chrome extension.
- Claim-quality work from the P0/P1 backlog (B16, B11, B19, B5).
- Any behaviour change other than step 3, which is deliberate and isolated.

## Plan

Nine steps. Steps 1–4 are pivot work; 5–9 are the readability pass. Each ships as
its own commit against a green suite.

### 1. Land Phase 6b — DONE (`f038df9`)

Baseline commit so later diffs are readable. 610 tests green.

### 2. Collapse the five forks

Each fork becomes a thin caller of the engine version, passing cars policy as
arguments rather than re-implementing the orchestration.

- `packs/cars/pipeline/ledger/{chunking,ingest,extraction}.py` call
  `kriko/ledger/*` with cars' lexicon, blocklist, language check and gate.
- `app/mcp_server.py` uses `kriko.extract.grounding.is_grounded`.
- `packs/cars/pipeline/title_sim.py` is deleted; callers use `kriko/text/title_sim.py`.

**G6 significance:** proves the generic path works by making the only real pack
use it. **Effect:** removes roughly 350 duplicated lines and the drift risk.
**Behaviour:** unchanged — parity harnesses must stay green.

### 3. Gating becomes pack data, and gets wired in

`kriko/gates.py` reads gate rules from a pack's `gate_terms` rows — the G6 shape.
`packs/cars/pipeline/agent/gates.py` hardcodes the same judgements in Python — the
pre-pivot shape. Collapse to the first.

- Cars' Python gate vocabulary moves into `packs/cars/vocabulary/gates.yaml` rows.
- `app/mcp_server.py:submit_findings` calls `kriko.gates.gate_reason` with the
  pack's loaded vocabulary, and `kriko.extract.grounding.is_grounded` for the
  quote check.
- `packs/cars/pipeline/agent/gates.py` is deleted once its rules are rows.

**This is the one intended behaviour change**: the agent write path starts
rejecting low-value findings again. It gets its own commit and its own tests,
including a test that a warning-light finding is refused with a reason the agent
can act on.

**Fail-open rule preserved:** a pack with no `gate_terms` rows gates nothing, per
`kriko/gates.py`'s existing contract and CLAUDE.md's automation principle.

### 4. Write the pack contract

`docs/PACK_CONTRACT.md`: the required minimum for a pack, and what an optional
`pipeline/` adds on top. Backed by a test that both `packs/cars` and `packs/drill`
satisfy the stated minimum, so the document cannot drift from the code.

**Required minimum**, per `kriko/pack/manifest.py`, which is the authority:

- `pack.toml` with `[pack]` keys `id`, `name`, `version`
- `pack.toml` with an `[identity]` table declaring at least one subject kind and
  its identity attribute keys — the manifest raises without it, because every
  subject of a kind would otherwise hash to the same id
- `data/` — the rows themselves

**Optional**, and to be documented as such: `vocabulary/`, `research/`, `trust/`,
`adapters/`, `build.py`, `pipeline/`, `coverage.py`. `packs/drill/` is the
minimum-plus-vocabulary example; `packs/cars/` is the everything example.

**G6 significance:** this is what makes the scope change landable by someone other
than the author.

### 5. Delete confirmed dead code

`packs/cars/pipeline/catalog/model_state.py` (148 lines) has zero references
anywhere, including docs. Each further candidate is re-verified individually
before deletion.

**Confirmed alive, keep:** `catalog/doctor.py`, `fitment/validate_fitment.py`,
`pipeline/scaffold.py`, `ledger/eval_verdict.py`,
`catalog/repair_missing_stub_scaffold.py` — all `python -m` entry points reachable
from `docs/USAGE.md` or their own module docstrings.

### 6. Break the two giant build functions

`packs/cars/build.py:build()` (457 lines) and `kriko/pack/build.py:build()` (300)
become sequences of named stages. Pure extraction, no behaviour change.

### 7. Group the flat drawer

`packs/cars/pipeline/` holds 14 loose modules beside 6 tidy subpackages. Group by
what they own:

- `claims/` — `ground_year_window`, `ground_mileage_threshold`,
  `consequence_tier`, `maintenance`, `dedup`
- `util/` — `paths`, `yamlutil`, `domains`

Mechanical moves; exact membership confirmed against imports during
implementation.

### 8. Reading map

`docs/ARCHITECTURE.md`, one page, written for a human investigating the tree
rather than for CI: where to start, what each package owns, the entry points, and
a "chasing X? read these three files" index.

### 9. Repo tidy

Remove the empty `deploy/`. Reconcile stale `docs/USAGE.md` references. Update
`backlog.md` and `done.md`.

## Readability targets

Measurable, checked at the end:

- No function over ~80 lines outside tests.
- Every module has a one-line "what this owns" docstring.
- Every package's public surface is reachable from `docs/ARCHITECTURE.md`.
- No concern has two implementations.

## Verification

- Full suite green after every step. It runs in ~15s, so per-commit is cheap.
- `packs/cars/tests/test_pack_parity.py` and
  `packs/cars/pipeline/ledger/parity.py` stay green — these are the
  behaviour-preservation harnesses for steps 2, 6 and 7.
- `app/pipeline/tests/test_repo_invariants.py` keeps enforcing the four layering
  greps and the `backend/` ratchet.
- Step 3 is the only step permitted to change behaviour; it carries new tests
  asserting the new rejections.

## Risks

| Risk | Mitigation |
|---|---|
| Step 3 over-gates and drops good findings | Fail-open contract; tests cover a kept claim as well as a rejected one; own commit, easily reverted |
| Cars' Python gate has judgement not expressible as rows | Discovered during step 3; if real, keep it as a pack-supplied callable rather than reverting to an engine constant |
| Step 2 changes ledger behaviour subtly | Parity harnesses are the gate; step is abandoned per-module if parity breaks |
| Step 7's grouping churns imports for little gain | Mechanical and last-in-line; can be dropped without affecting steps 2–4 |

> TL;DR (archived 2026-09-25): Split `knowledge/` (7,783 lines) into generic engine `kriko/`
+ car-specific `packs/cars/pipeline/`. Key seam: `stoplists.py` split first (generic filters
to `kriko/text.py`, judgement vocab to pack rows). 6 tasks, baseline 570 tests, branch
`feat/knowledge-engine-pivot` (HUMAN DECISION #8, 2026-08-27).
> Invariants: `kriko/` imports nothing above it; no car vocab in executable positions; packs
consumed via store rows. Full file dumps trimmed below — see git history.

# Phase 6b — Split `knowledge/` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `knowledge/` (7,783 lines) into a generic evidence pipeline under `kriko/` and a car-specific one under `packs/cars/pipeline/`, so a second real pack can have a pipeline without duplicating the extraction machinery.

**Architecture:** The blocker was one module: `knowledge/stoplists.py` is imported by eight modules including the otherwise-generic ledger, and derives from the car catalog. Split it first — language/source-domain filters (generic) move to `kriko/text.py`; judgement vocabulary (the cars product principle in Python) becomes pack-declared rows. Then `kriko/ledger/` and `kriko/extract/` fall out car-free, and the remainder moves into `packs/cars/pipeline/`.

**Tech Stack:** Python 3.14, SQLite (WAL), pytest, PyYAML. No new dependencies.

**Spec:** `~/.claude/plans/let-s-go-with-the-eager-torvalds.md` (G6 pivot design, Phase 6); split-vs-move-wholesale is HUMAN DECISION #8 in `backlog.md`, resolved 2026-08-27 for the split.

## Global Constraints

- **`kriko/` may import none of `backend`, `ops`, `apps`, `packs`, `knowledge`.** Enforced by `ops/tests/test_repo_invariants.py` — the load-bearing G6 invariant.
- **No car vocabulary in `kriko/` executable positions** (`make`, `engine_code`, `fuel`, `variant`, `gearbox`, `dsg`, `tdi`). Enforced by `kriko/tests/test_core_is_domain_free.py` (AST walk; docstring prose is fine, value-position string literals are not).
- **A pack is consumed through the store, never imported.** Core modules get pack data as rows.
- **No hardcoded car data anywhere**, including pack Python: coverage-growing values derive from `packs/cars/data/**/*.yaml`. Fixed engineering categories may be constants.
- **No human in the data path.** Underivable values fail open: emit nothing, log the gap.
- Full suite at every task boundary: `.venv/bin/python -m pytest -q` must exit 0. Baseline: **570 tests**.
- Commit per task. Branch: `feat/knowledge-engine-pivot`.

---

## File Structure

**New in `kriko/` (generic — no car vocabulary):**

| File | Responsibility |
|---|---|
| `kriko/text.py` | Language detection, verbose-title and blocked-domain filters, generic code-token shape. Pure string functions. |
| `kriko/gates.py` | Evaluates pack-declared gate vocabulary. Knows *how* to gate, never *what* is worth gating. |
| `kriko/ledger/` | `db, ingest, chunking, cluster, costs, extraction, verdict, parity, eval_verdict` — evidence rows, provenance, dedupe, verdict cache. |
| `kriko/extract/` | `client` (langextract), `grounding`, `dedup`, `title_sim`, `domains`, `consequence_tier`. |

**New in `packs/cars/` (car-specific):**

| File | Responsibility |
|---|---|
| `packs/cars/vocabulary/gates.yaml` | Cars product principle as data: inspection-covered, generic-maintenance, ambiguous terms, warning-light patterns, specificity signals. |
| `packs/cars/pipeline/catalog/` | `discover, write_variants, identity, doctor, generations, model_state, registry, emissions, repair_missing_stub_scaffold`. |
| `packs/cars/pipeline/parts/`, `fitment/` | Part and fitment YAML validation, search templates. |
| `packs/cars/pipeline/{acquire,export,resolve}.py` | The car-shaped ends of the ledger run. |
| `packs/cars/pipeline/vocabulary.py` | What survives of `stoplists`: sibling codes, foreign-manufacturer detection, catalog-derived code manufacturers. |

**Deleted:** the whole of `knowledge/`.

---

### Task 1: The gate vocabulary becomes pack data

`INSPECTION_COVERED`, `GENERIC_MAINTENANCE_TERMS`, `AMBIGUOUS_INSPECTION_TERMS`, `WARNING_LIGHT_PATTERNS`, `has_specificity_signal` are the cars product principle as Python constants. Five modules import them, so while they live in `knowledge/` nothing importing them can move to `kriko/`. This task unblocks all later ones.

**Files:**
- Create: `kriko/gates.py`, `packs/cars/vocabulary/gates.yaml`, `kriko/tests/test_gates.py`
- Modify: `kriko/pack/build.py` (emit gate rows), `kriko/store/schema.sql` (one table), `kriko/tests/test_pack_build.py`

**Interfaces:**
- Consumes: `kriko.store.db.connect`, the `terms` table pattern from `kriko/pack/build.py`.
- Produces: `kriko.gates.GateVocabulary` (frozen dataclass: `covered`, `generic`, `ambiguous: frozenset[str]`; `noise_patterns`, `specificity_patterns: tuple[re.Pattern, ...]`); `load_gates(conn, pack_id) -> GateVocabulary`; `gate_reason(text, vocab) -> str | None` (rejecting rule name, or `None` to keep).

- [ ] **Step 1: Add the storage table** — `gate_terms` table after the `terms` table in `kriko/store/schema.sql` (`kind`: literal phrase for covered/generic/ambiguous, regex for noise/specificity; PK on all but note). Full DDL — see git history.

- [ ] **Step 2: Write the failing test** — `kriko/tests/test_gates.py` (nothing names a car part; asserts keep/reject per kind + `load_gates` round-trip). Full test — see git history.

- [ ] **Step 3: Run it** — `.venv/bin/python -m pytest kriko/tests/test_gates.py -q`. Expected: FAIL (`No module named 'kriko.gates'`).

- [ ] **Step 4: Implement `kriko/gates.py`** — literal lists, compiled regexes, `is_specific` escape; ambiguous rejects only when not specific (the EA211 piston-ring lesson). Full module — see git history.

- [ ] **Step 5: Run it** — same command. Expected: PASS, 8 tests.

- [ ] **Step 6: Builder emits gate rows** — `_gate_rows()` beside `_tier_rows` in `kriko/pack/build.py`; unknown kinds raise (silently ignoring a kind would ship a pack whose author believes a gate runs when it does not). Full helper — see git history.

- [ ] **Step 7: Builder test** — valid YAML builds; `coverd:` typo raises `ValueError("unknown rule kinds")`. Full test — see git history.

- [ ] **Step 8: Run builder tests** — `.venv/bin/python -m pytest kriko/tests/test_pack_build.py -q`. Expected: PASS.

- [ ] **Step 9: Transcribe the cars vocabulary** — `INSPECTION_COVERED`→`covered`, `GENERIC_MAINTENANCE_TERMS`→`generic`, `AMBIGUOUS_INSPECTION_TERMS`→`ambiguous`, `WARNING_LIGHT_PATTERNS`→`noise`, `CODE_TOKEN_RE`/`_DISPLACEMENT_RE`/`_MILEAGE_RE`→`specificity`. Carry each block's comment as the first entry's `note` (they record real incidents). Header comment — see git history.

- [ ] **Step 10: Prove completeness** — `packs/cars/tests/test_gate_vocabulary.py` pins counts from `ded8113` (covered 44, generic 11, ambiguous 3, noise 4, specificity 3; re-check with the `stoplists` length script if the module changed). Full test — see git history.

- [ ] **Step 11: Suite** — `.venv/bin/python -m pytest -q`, exit 0.

- [ ] **Step 12: Commit** — `feat(pivot): Phase 6b/1 — the gate vocabulary becomes pack data` (frozensets→rows; ambiguous rule survives intact, pinned by the vocabulary test).

---

### Task 2: The generic text and source filters move to `kriko/text.py`

`is_german_text`, `is_likely_non_english`, `title_is_verbose`, `is_blocked_source_domain`, `FORUM_DOMAINS`, `UNRELIABLE_DOMAINS` are about language and publishing — a drill pack wants all six unchanged. Sibling codes / foreign-manufacturer detection stay behind for Task 5. Signature change: `is_blocked_source_domain` takes the blocklist as a parameter (distrusted domains are pack data/reader config, not an engine constant); `is_german_text` + `is_likely_non_english` merge into `is_probably_not_english`.

**Files:** create `kriko/text.py`, `kriko/tests/test_text.py`; modify `knowledge/stoplists.py` (re-export during the move).
**Interfaces:** `kriko.text.is_probably_not_english(text, threshold=0.02)`, `kriko.text.title_is_verbose(title, max_len=100)`, `kriko.text.is_blocked_source_domain(url_or_host, blocked: frozenset[str])`, `kriko.text.code_tokens(text) -> set[str]`.

- [ ] **Step 1: Failing test** — `kriko/tests/test_text.py` (10 tests; e.g. `code_tokens("the tensioner rattles") == set()`). Full test — see git history.
- [ ] **Step 2: Run it** — FAIL (`No module named 'kriko.text'`).
- [ ] **Step 3: Create `kriko/text.py`** — move bodies unchanged except the merge + the `blocked` parameter; carry comments (`_NON_ENGLISH_CHAR_MARKERS` records real alphabets).
- [ ] **Step 4: Run it** — PASS, 10 tests.
- [ ] **Step 5: Re-point `knowledge/stoplists.py`** — replaced bodies become `from kriko.text import ...` re-exports (deleted in Task 6); `is_blocked_source_domain` keeps a thin wrapper supplying `UNRELIABLE_DOMAINS` until callers pass one.
- [ ] **Step 6: Suite** — `.venv/bin/python -m pytest -q`, exit 0.
- [ ] **Step 7: Commit** — `feat(pivot): Phase 6b/2 — language and source filters move to kriko/text.py`.

---

### Task 3: `kriko/ledger/` — the generic ledger moves up

After Tasks 1–2, `db, ingest, chunking, cluster, costs, extraction, verdict, parity, eval_verdict` are car-free. `resolve.py` stays — it calls `catalog_code_manufacturers()` (Task 5).

**Files:** create `kriko/ledger/{__init__,db,ingest,chunking,cluster,costs,extraction,verdict,parity,eval_verdict}.py`; move `knowledge/tests/test_ledger_{db,ingest,chunking,cluster,costs,extraction,verdict,parity}.py` → `kriko/tests/`; modify `ops/{ledger_run,panel,remediate}.py` imports.
**Interfaces:** consumes `kriko.gates.load_gates/gate_reason`, `kriko.text.*`; produces each module's existing public functions under `kriko.ledger.*`, names unchanged.

- [ ] **Step 1: `git mv` the modules** (loop over the ten names) so history follows.
- [ ] **Step 2: Rewrite imports** (`knowledge.ledger`→`kriko.ledger`, `knowledge.stoplists`→`kriko.text` via sed), then hand-fix the two seam modules: `extraction.py` takes a `GateVocabulary` parameter and calls `gate_reason`; `verdict.py` takes injected `siblings_of=` / `is_noise=` callables defaulting to fail-open (`frozenset()` / `False`).
- [ ] **Step 3: Move + re-point the tests** (same sed over `kriko/tests/test_ledger_*.py`).
- [ ] **Step 4: Pin the injection** — `gate_product_value(evidence_titles, v, is_noise=_never)` test in `test_ledger_verdict.py`; `cluster_payload`/`pending_clusters` gain `siblings_of` with the same fail-open default. Full test + implementation — see git history.
- [ ] **Step 5: Re-point `ops/`** (`knowledge.ledger`→`kriko.ledger`).
- [ ] **Step 6: Suite + invariant grep** (`(from|import) (backend|ops|apps|packs|knowledge)` in `kriko/` non-tests must print nothing).
- [ ] **Step 7: Commit** — `feat(pivot): Phase 6b/3 — the generic ledger moves into kriko/` (fail-open defaults: an engine that suppresses a claim unasked is worse than one that says too much).

---

### Task 4: `kriko/extract/` — grounded extraction moves up

**Files:** create `kriko/extract/{__init__,client,grounding,dedup,title_sim,domains,consequence_tier}.py`; move `knowledge/tests/test_{langextract_client,extract_claims,consequence_tier}.py` → `kriko/tests/`.
**Interfaces:** `kriko.extract.grounding.extract(...)`, `kriko.extract.client.*` (the langextract wrapper), `kriko.extract.dedup.*`, `kriko.extract.domains.*`.

- [ ] **Step 1: `git mv`** (`langextract_client`→`client`, `extract`→`grounding`, `dedup`, `title_sim`, `domains`, `consequence_tier`).
- [ ] **Step 2: Check `domains.py` for car vocab first** (`engine|transmission|gearbox|emissions|fuel|suspension|brakes`): if it enumerates car subsystems it does **not** move — subsystem taxonomy is category vocabulary already in `terms` rows (`role='domain'`); delete it and re-point callers at pack domain terms.
- [ ] **Step 3: Rewrite imports** across `kriko/extract/`, `kriko/ledger/`, `ops/`, `knowledge/**`.
- [ ] **Step 4: Move + re-point the tests.**
- [ ] **Step 5: Suite + both invariants** (`pytest -q`, domain-free test, upward-import grep — all clean).
- [ ] **Step 6: Commit** — `feat(pivot): Phase 6b/4 — grounded extraction moves into kriko/extract/`.

---

### Task 5: `packs/cars/pipeline/` — the rest moves down

Everything left in `knowledge/` is the cars pipeline; under the pack its car-shapedness stops being a problem.

**Files:** move `knowledge/{catalog,parts,fitment,sources,agent}/` → `packs/cars/pipeline/`; `knowledge/ledger/{acquire,export,resolve}.py`, `{scaffold,maintenance,ground_mileage_threshold,ground_year_window,yamlutil}.py` → same; `stoplists.py`→`vocabulary.py`; remaining 26 `knowledge/tests/` files → `packs/cars/tests/`. Create `packs/cars/pipeline/vocabulary.py`.

- [ ] **Step 1: `git mv` everything** (catalog, parts, fitment, sources, agent dirs; acquire/export/resolve; scaffold/maintenance/ground_*/yamlutil; stoplists→vocabulary.py).
- [ ] **Step 2: Strip the Task 2 re-export block** from `vocabulary.py`; import the four functions directly at use sites. `UNRELIABLE_DOMAINS`/`FORUM_DOMAINS` stay here, passed explicitly into `is_blocked_source_domain`.
- [ ] **Step 3: Rewrite every remaining `knowledge.` import** via the per-module sed map (catalog/parts/fitment/sources/agent/stoplists/scaffold/maintenance/ground_*/yamlutil/ledger.{acquire,export,resolve}), then hand-fix leftovers.
- [ ] **Step 4: Wire the injection points** in `ops/ledger_run.py` (`ops/` may import both layers — that is what it is for): `vocab = load_gates(store, "org.kriko.cars")`; `verdict.run(..., siblings_of=sibling_codes_for, is_noise=title_has_dtc_code)`.
- [ ] **Step 5: Move the remaining tests**, re-point imports, delete `knowledge/tests/__init__.py`.
- [ ] **Step 6: Suite** — exit 0, 570+ tests.
- [ ] **Step 7: Commit** — `feat(pivot): Phase 6b/5 — the cars pipeline moves under the cars pack`.

---

### Task 6: Delete `knowledge/`, and ratchet it shut

**Files:** delete `knowledge/`; modify `ops/tests/test_repo_invariants.py`, `CLAUDE.md`, `docs/INTERNALS.md`.

- [ ] **Step 1: Confirm emptiness** (`find knowledge -type f` → nothing; anything listed gets decided about, not deleted).
- [ ] **Step 2: `git rm -r knowledge/`**.
- [ ] **Step 3: Ratchet test** — `test_knowledge_stays_deleted` next to the `backend/` ratchet (a layer-named package collects whatever authors believe belongs to that layer). Full test — see git history.
- [ ] **Step 4: Update the layering contract** — `CLAUDE.md` fan becomes three packages + the three greps; add the earned sentence: *"`knowledge/` was the cars pipeline under a generic name, and the name is what let car code accumulate unnoticed."*
- [ ] **Step 5: Run everything** — `pytest -q` exit 0; `npm test` 36 pass.
- [ ] **Step 6: Backlog** — mark Phase 6b done with date+commit; HUMAN DECISION #8 resolved for the split; note the payoff (second pack needs gate rows + search templates, not machinery).
- [ ] **Step 7: Commit** — `feat(pivot): Phase 6b/6 — knowledge/ is deleted, and ratcheted shut`.

---

## Verification

After Task 6, all must hold:

```bash
.venv/bin/python -m pytest -q                  # exit 0
npm test                                       # 36 pass
.venv/bin/python -m packs.cars.build --out /tmp/cars.kpack
.venv/bin/python -m apps.cli --store /tmp/s.db install /tmp/cars.kpack
.venv/bin/python -m ops.ledger_run --help      # pipeline drivers still run
grep -rn "knowledge" --include='*.py' . | grep -v '\.venv' | grep -v 'knowledge engine'
```

Last grep: prose matches only ("knowledge engine/pack"), never an import.

## Risks

1. **`ops/ledger_run.py` / `ops/remediate.py` have thin coverage** and their imports change in Tasks 3+5. Mitigation: `--help` + one `--dry-run` at the end of Tasks 3, 5 *and* 6.
2. **Task 1 transcription loses meaning.** Frozenset comments record real incidents → YAML `note:` fields. `test_every_phrase_...` catches dropped lines, not dropped *reasons* — read the Task 1 diff with that in mind.
3. **Forgotten injection wiring fails open** (more claims, not fewer — visible in coverage, not silent). Task 5 Step 4 is not optional; grep every `verdict.run(` / `extraction.run(` after Task 5.

> TL;DR (archived 2026-09-25): 14-task pass making the engine's generic layer the only
implementation (collapse 5 cars forks: chunking, ingest, extraction, grounding, title_sim),
gating-as-pack-data wired into the agent write path (the one behaviour change), pack contract,
then readability (break 457/300-line `build()`s, group flat drawer, ARCHITECTURE.md, tidy).
> Baseline `f038df9`, 594 tests green, parity harnesses gate every fork collapse. Full file dumps trimmed below — see git history.

# Kriko Simplification and Readability Pass — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the engine's generic layer the only implementation of chunking, ingest, extraction, grounding, gating and title similarity, then make the resulting tree readable by a human investigating it cold.

**Architecture:** Four-package fan — `app/` and `packs/` depend on `kriko/`; `kriko/` depends on neither. Phase 6b built the generic modules but left the cars pack running pre-pivot forks. Each task either deletes a fork (cars *calls* the engine with policy injected) or removes something unreadable.

**Tech Stack:** Python 3.14, pytest, SQLite (`sqlite3` stdlib), pydantic, FastAPI, tomllib, PyYAML.

**Spec:** `docs/superpowers/specs/2026-08-29-simplification-design.md`

## Global Constraints

- Tests: `.venv/bin/python -m pytest` (bare `python` does not exist). Whole suite before every commit: `.venv/bin/python -m pytest -o addopts="" -q` (`-o addopts=""` required — `pytest.ini` already sets `-q`, and doubled `-q` suppresses the count). Baseline: **594 passed, ~24s**.
- **`kriko/` may not import `app/`, `packs/`, `backend/`, `knowledge/`** (G6 invariant, `test_repo_invariants.py` enforces; never weaken it).
- **Behaviour preserved except Tasks 6–7.** A broken `test_pack_parity.py` elsewhere means the task is wrong — revert, don't update the golden.
- **No hardcoded car data in `kriko/`** (`test_core_is_domain_free.py` walks the AST).
- Commit per task, message body explains *why* (`CONTRIBUTING.md`), ending `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. **Do not push or open a PR.**
- Baseline `f038df9`, spec `b7c74a0`, branch `feat/knowledge-engine-pivot`.

---

## File Structure

**Deleted:** `packs/cars/pipeline/title_sim.py` (verbatim fork); `packs/cars/pipeline/agent/gates.py` (orphan; vocab→rows, structure→engine); `packs/cars/pipeline/catalog/model_state.py` (zero refs).

**Thin adapters over the engine:** `ledger/chunking.py` (~15 lines, code-token detector over `kriko.ledger.chunking`); `ledger/ingest.py` (~30 lines, blocklist + language check injected); `ledger/extraction.py` (~45 lines, extractor/detector/gate injected).

**Created:** `docs/PACK_CONTRACT.md`; `docs/ARCHITECTURE.md`; `kriko/tests/test_pack_contract.py`; `packs/cars/pipeline/claims/` (ground_year_window, ground_mileage_threshold, consequence_tier, maintenance, dedup); `packs/cars/pipeline/util/` (paths, yamlutil, domains).

---

### Task 1: Delete the `title_sim` fork

Warm-up and the pattern for every later collapse: a pack may import the engine, so a pack-local copy of engine logic is never justified. Same Jaccard, same 0.4 threshold, same stopwords.

**Files:** delete `packs/cars/pipeline/title_sim.py`; modify every importer.
**Interfaces:** consumes `kriko.text.title_sim.title_tokens/title_similar(threshold=0.4)`; produces nothing new.

- [ ] **Step 1: Find importers** — `grep -rn "pipeline.title_sim\|pipeline import title_sim" --include='*.py' app kriko packs` (expect small: the dedup path).
- [ ] **Step 2: Prove identical before deleting** — scratch cross-check on cases incl. `("DQ381 mechatronics failure", "mechatronics failure on the DQ381")` (full script — see git history). Expected `identical on all cases`; on disagreement STOP (drift = behaviour change, report it).
- [ ] **Step 3: Repoint imports** — `packs.cars.pipeline.title_sim` → `kriko.text.title_sim`.
- [ ] **Step 4: `git rm` the fork.** Step 5: suite PASS at 594. Step 6: commit `refactor(cars): drop the title_sim fork, call the engine`.

---

### Task 2: Collapse the chunking fork, and move car vocabulary out of the engine

Cars' chunker adds one thing: the `code_tokens()` detector (a detector is not a term list, so it injects at the `signal_detector=` seam). Also fixes a G6 smell: `kriko/ledger/chunking.py`'s `FAILURE_LEXICON` holds `misfire/judder/shudder/clog/rattle` under a "deliberately category-neutral" docstring.

**Files:** `packs/cars/pipeline/ledger/chunking.py` (~15 lines); `kriko/ledger/chunking.py:16-60`; tests `packs/.../test_ledger_chunking.py` (unchanged), `kriko/tests/test_ledger_chunking.py` (new if absent).
**Interfaces:** consumes `kriko.ledger.chunking.{chunk_text,chunk_has_signal(signal_terms=),Chunk,CHUNK_CHARS=4000,CHUNK_OVERLAP=400}` + `stoplists.code_tokens`; produces cars `chunk_has_signal` + re-exports (existing test imports those names).

- [ ] **Step 1: Record green** — cars chunking test PASS (contract: 4 assertions, incl. `code_tokens`-only case `"the EA888 uses a different tensioner"`).
- [ ] **Step 2: Adapter** — cars module becomes the engine chunker + `CAR_FAILURE_TERMS` + `code_tokens` (full 25-line module — see git history).
- [ ] **Step 3: Move the five terms** out of the engine into `stoplists.CAR_FAILURE_TERMS` (after `GENERIC_MAINTENANCE_TERMS:76`; closed engineering vocab per the scalability exception). Net behaviour identical via `signal_terms`.
- [ ] **Step 4: Cars test** — PASS unchanged. Step 5: engine test (`test_filler_is_not_signal`, full — see git history). Step 6: engine test PASS. Step 7: suite PASS (count rises by new tests). Step 8: commit `refactor(ledger): one chunker, and the engine forgets what a misfire is`.

---

### Task 3: Collapse the ingest fork

Cars' `ingest.py` (172 lines) vs engine's (168) differ in exactly three ways: a `Document` hint, a `component_hint`/`subject_hint` key both `None`, and two functions hardcoding cars' blocklist instead of the injected default.

**Files:** `packs/cars/pipeline/ledger/ingest.py` (~30 lines); test unchanged.
**Interfaces:** consumes `kriko.ledger.ingest.{ingest_document,flag_blocked_sources,flag_foreign_language}` + `stoplists.{is_blocked_source_domain,is_german_text}`; produces same three cars functions — arities load-bearing (`ledger_run.py:36-37`, `remediate.py:119`, `acquire.py:27` call them by name/arity).

- [ ] **Step 1: Record green** (contract: `test_flag_blocked_sources_marks_only_blocked_domains`, `test_flag_foreign_language_marks_only_german`, `test_ingest_document_stores_hint_not_attribution`).
- [ ] **Step 2: Confirm the hint difference is a no-op** — `insert_evidence` resolves `claim.get("component_hint") or claim.get("subject_hint")` (grep it; both spell `None`; else STOP and report).
- [ ] **Step 3: Adapter** (full module — see git history). Re-export any other public name callers use (`grep -n "^def \|^[A-Z_]* ="` pre-change).
- [ ] **Step 4: Cars test PASS unchanged.** Step 5: suite PASS at Task-2 count. Step 6: commit `refactor(ledger): one ingest, with cars' source policy injected`.

---

### Task 4: Collapse the extraction fork

Largest of the five: cars' `extraction.py` (122 lines) reimplements the engine's chunk loop, cache, budget charge, evidence insert. Engine takes `extractor=`, `signal_detector=`, `gate_reason=`; cars needs langextract, its detector, and a `component_hint` remap through them.

**Files:** `packs/cars/pipeline/ledger/extraction.py` (~45 lines); test unchanged.
**Interfaces:** consumes `kriko.ledger.extraction.{extract_document,extract_pending,pending_extraction_estimate}` + `langextract_client.extract_grounded`; produces same three cars functions. Arities + `extract_grounded` as a **module-level name resolved at call time** are load-bearing (`ledger_run.py:46,49`, `remediate.py:193`, `panel.py:76-77` call positionally; `test_ledger_run.py:12,26` monkeypatches the dotted path).

- [ ] **Step 1: Record green** (caching, budget exhaustion, low-value flag, monkeypatch path).
- [ ] **Step 2: Adapter** (full module — see git history). One real difference vs the fork: `_extract` remaps *before* `_low_value_reason` sees the dict — safe, it reads only `title`/`rationale`, untouched by the remap.
- [ ] **Step 3: Extraction + run + remediate tests PASS unchanged** (monkeypatch failure ⇒ `extract_grounded` resolved too early — must be read in the function body, never a default arg/constant).
- [ ] **Step 4: Suite PASS.** Step 5: engine extraction now has a production caller (grep). Step 6: commit `refactor(ledger): one extraction loop, cars supplies the policy`.

---

### Task 5: Cars' low-value rules become pack rows

`gates.yaml` declares the vocabulary and `kriko/gates.py` evaluates it, but extraction still judges from `stoplists.py` frozensets — two sources of truth.

**Files:** `packs/cars/pipeline/ledger/extraction.py` (`_low_value_reason`); its test.
**Interfaces:** consumes `kriko.gates.{load_gates,gate_reason}` (`"covered"|"generic"|"noise"|"ambiguous"|None`); `_low_value_reason` keeps `(claim: dict) -> str | None`, only reason strings change.

- [ ] **Step 1: Coverage check** — every frozenset term present in `gates.yaml` (script — see git history); missing terms get **added to YAML first** (don't delete from `stoplists.py` yet — Task 7 owns other callers).
- [ ] **Step 2: Failing test** — `test_low_value_reason_comes_from_pack_rows_not_python_constants` (warning-light → `"noise"`; `DQ381 mechatronics … 120000 km` → `None`). Full test — see git history.
- [ ] **Step 3: FAIL** (`"warning-light pattern"`, not `"noise"`).
- [ ] **Step 4: `vocabulary_from_rows`** in `kriko/gates.py` (offline pipeline has only the YAML; installed store has rows; both compile identically). `load_gates` delegates to it (behaviour unchanged — `test_gates.py` + `test_gate_vocabulary.py` check). Full function — see git history.
- [ ] **Step 5: Rewrite `_low_value_reason`** against pack rows (full — see git history). The `isinstance(entries, list)` filter is load-bearing: Task 6's `limits:` mapping must not read as patterns.
- [ ] **Step 6: Test PASS** (update any old assertion on the literal `"warning-light pattern"` → `"noise"` — the vocabulary intentionally changes). Step 7: suite. Step 8: commit `refactor(cars): the extraction gate reads the pack's rows, not frozensets`.

---

### Task 6: The engine learns the structural gate rules

`agent/gates.py` holds non-vocabulary rules (title-length cap, DTC shape, min rationale length, "no config anchor at all") — generic rule *shapes* with category-specific thresholds. Shapes move to `kriko/gates.py`, parameterised by pack values.

**Files:** `kriko/gates.py`; `gates.yaml` (`limits` block); `kriko/tests/test_gates.py`.
**Interfaces:** `GateVocabulary` gains `max_title_chars/min_rationale_chars = 0` (0 = undeclared = don't check, fail open); new `structural_reasons(title, rationale, vocab, *, has_anchor=False) -> list[str]`.

- [ ] **Step 1: Failing tests** (undeclared limits gate nothing; over-long title / short rationale / anchorless rejected). Full tests — see git history. Step 2: FAIL (`ImportError: structural_reasons`).
- [ ] **Step 3: Implement** — dataclass fields + `structural_reasons` (full — see git history). New fields default `0`, so Step-1 tests pass standalone.
- [ ] **Step 4: PASS.** Step 5: declare cars' limits as rows — `limits: [{pattern: max_title_chars, note: "100"}, {pattern: min_rationale_chars, note: "60"}]` (ex-`max_len=100`, `MIN_RATIONALE_CHARS=60`; list-of-mappings so `build.py`'s emission loop handles it unchanged).
- [ ] **Step 6: Builder + loaders learn `limits`** — `packs/cars/build.py:732/750` (raises on unknown kinds — declare or the pack stops building); same in `kriko/pack/build.py:435` if it enumerates kinds; `vocabulary_from_rows(rows, limits=None)` gains optional second arg; `load_gates` splits `kind='limits'` notes; cars `_vocabulary()` splits YAML the same way (full code — see git history).
- [ ] **Step 7: Round-trip through a real build** — vocab test PASS; limits present in built `.kpack` (build + sqlite query script — see git history; match `main()`'s real flags).
- [ ] **Step 8: Still category-free** (`test_core_is_domain_free.py` PASS — "identifier/variant/usage figure", never engine code/gearbox/mileage). Step 9: suite. Step 10: commit `feat(gates): the engine learns rule shapes, the pack keeps the numbers`.

---

### Task 7: Wire the gate into the agent write path, and delete the orphan

**Behaviour change on purpose.** `submit_findings` checks only quote-presence; the 243-line product-principle gate has no caller and no test, so the agent path writes evidence the principle says to drop.

**Files:** `app/mcp_server.py:259-330`; delete `agent/gates.py`; `app/tests/test_mcp_server.py`.
**Interfaces:** consumes `kriko.gates.{load_gates,gate_reason,structural_reasons}` + `is_grounded`; `submit_findings(subject_id, pack_id, findings)` signature and `{"accepted", "rejected": [{title, reason}]}` shape unchanged.

- [ ] **Step 1: Failing tests** — warning-light finding refused with an actionable reason; specific finding accepted (adapt `store`/`SUBJECT_ID`/`PACK_ID` to the file's fixtures; subject must exist or the gate is never reached). Full tests — see git history.
- [ ] **Step 2: FAIL** (warning-light currently accepted).
- [ ] **Step 3: Wire in** — imports; `vocab = load_gates(conn, pack_id)` per call after the subject check; engine `is_grounded` replaces the inline quote check; `gate_reason` then structural gate before the `source_id` line (full hunks — see git history).
- [ ] **Step 4: PASS incl. pre-existing grounding tests.** A newly-failing fixture that is too generic is the gate working — make the fixture specific, **never** weaken the gate; unfixable fixtures get reported, not guessed.
- [ ] **Step 5: Delete orphan** — reference grep → `git rm agent/gates.py`; repoint `docs/USAGE.md:114` at `kriko/gates.py` + `gates.yaml`.
- [ ] **Step 6: Suite.** Step 7: commit `fix(mcp): submit_findings enforces the product principle again`.

---

### Task 8: Write the pack contract, and test it

`packs/drill/` (5 YAML files) vs `packs/cars/` (12,900 lines): no stated minimum, so a third-party author has two disagreeing examples and no rule.

**Files:** create `docs/PACK_CONTRACT.md`, `kriko/tests/test_pack_contract.py`; link from `README.md`.
**Interfaces:** consumes `kriko.pack.manifest.load(root) -> Manifest` (root, pack_id, name, version, publisher, license, origin_url, `identity_keys`, `raw`, `vocabulary_dir`/`data_dir`); the test is the enforcement.

- [ ] **Step 1: Failing test** — both shipped packs meet the contract (a one-example contract is indistinguishable from the example). Full test — see git history.
- [ ] **Step 2: Run** — both PASS; a `drill` failure means the **minimum is wrong — fix document + test**, never pad `drill` to an invented rule.
- [ ] **Step 3: The document**, no hedging: required minimum exactly as `manifest.py` enforces (`pack.toml` `[pack]` id/name/version; non-empty `[identity]` kind→keys; `data/`; `README.md`); why `[identity]` matters (decides sameness ⇒ merge); optionals with one-line value + demonstrating pack (`vocabulary/`, `research/`, `trust`, `adapters/`, `build.py`, `pipeline/`, `coverage.py`); start from `packs/drill/`; pointer to the test as enforcement.
- [ ] **Step 4: README link** + path check (`grep PACK_CONTRACT README.md && test -f`).
- [ ] **Step 5: Suite.** Step 6: commit `docs: state the pack contract, and test that both packs meet it`.

---

### Task 9: Delete dead code — COMPLETED AS A NO-OP

**Nothing was dead. Nothing deleted.** `model_state.py` has `test_model_state.py` (11 tests); the "zero refs" came from grepping the dotted path, which misses `from … import model_state`. Correct re-run (all import styles, no test-dir filter, entry-point + doc-mention detection): **no dead modules** — candidates are pytest-discovered tests or `python -m` entry points reachable from `docs/USAGE.md`/docstrings. The six expected-alive modules (`doctor.py`, `repair_missing_stub_scaffold.py`, `validate_fitment.py`, `scaffold.py`, `eval_verdict.py`, `consequence_tier.py`) are alive. Future re-check query (deadcode AST script — see git history); never search dotted paths.

---

### Task 10: Break `packs/cars/build.py`'s 457-line `build()`

**Files:** `packs/cars/build.py:357-816`. Guards (unchanged): `test_pack_parity.py`, `test_repo_invariants.py`.
**Interfaces:** `build(out_path) -> tuple[Path, dict]`, `main(argv=None) -> int` — signatures unchanged; new stage functions private.

- [ ] **Step 1: Byte baseline** — build → `/tmp/cars-before.kpack` + sha; if `_now()` breaks reproducibility, row-counts per table instead (script — see git history; match `main()`'s real flags).
- [ ] **Step 2: List stages from the code** (`sed -n '357,816p'`): load catalog → subjects → attributes → claims+conditions → evidence/sources → vocabulary/gates → adapters → manifest. Follow existing blank-line/banner structure; **no invented stages**.
- [ ] **Step 3: Extract one stage at a time** (`_emit_subjects(conn, catalog, pack_id) -> dict[...]` shape; bodies moved verbatim — writing logic means the boundary is wrong). After **each**: `pytest packs/cars/tests/ app/pipeline/tests/test_repo_invariants.py -q` PASS (per-stage extraction is what makes mistakes findable).
- [ ] **Step 4: `build()` reads as named calls** — AST length check (`STILL LONG` > 80 → `checked`; script — see git history).
- [ ] **Step 5: Pack unchanged** — rebuild + diff row counts vs Step 1 (a moved count = dropped/duplicated rows; find before committing).
- [ ] **Step 6: Suite.** Step 7: commit `refactor(cars): build() becomes a sequence of named stages`.

---

### Task 11: Break `kriko/pack/build.py`'s 300-line `build()`

Same shape, generic builder — matters more per line (every pack author reads it). Guard: `kriko/tests/test_pack_build.py` unchanged; `packs/` in the test invocation (drill proves the generic path for a pack with no `pipeline/`).

**Files:** `kriko/pack/build.py:168-467`. **Interfaces:** `build(...)` signature preserved **exactly** (keyword-only markers, defaults) — read `168-175` verbatim first; cars + drill depend on it.

- [ ] **Steps 1–3:** record signature + green tests; list stages (`sed -n '168,467p'`); extract per stage with per-extraction `pytest kriko/tests/test_pack_build.py packs/ -q`.
- [ ] **Step 4: No function over 80 lines** (same AST check). Step 5: signature byte-identical (`sed -n '/^def build/,/) ->/p'` vs Step 1 — any diff breaks both packs). Step 6: suite. Step 7: commit `refactor(pack): the generic builder becomes a sequence of named stages`.

---

### Task 12: Group the flat drawer

14 loose modules beside 6 subpackages: `claims/` (ground_year_window, ground_mileage_threshold, consequence_tier, maintenance, dedup) + `util/` (yamlutil, domains). **`paths.py` stays** — `PIPELINE_ROOT` derives from its own location; moving it silently shifts three roots (location *is* its meaning).

**Files:** create both `__init__.py`s; move listed modules; modify every importer. **Interfaces:** contents unchanged at new dotted paths; no signature changes.

- [ ] **Step 1: Import graph baseline** (`grep` both import forms → `/tmp/imports-before.txt` + count).
- [ ] **Steps 2–3: `git mv`** into `claims/` (5 modules) and `util/` (yamlutil, domains); `__init__.py` one-liners (full — see git history).
- [ ] **Step 4: Repoint importers** (dotted-path sed for both groups + manual pass for the `from packs.cars.pipeline import X` form the sed misses).
- [ ] **Step 5: Suite** (`ImportError` names the miss). Step 6: docs stale-path grep (`pipeline/(yamlutil|domains|dedup|maintenance|consequence_tier|ground_)`) → update hits. Step 7: commit `refactor(cars): group the pipeline's flat drawer`.

---

### Task 13: Write the reading map

The deliverable the user actually asked for: `docs/ARCHITECTURE.md` making the tree investigable without reading it all.

**Files:** create `docs/ARCHITECTURE.md`; modify `README.md`, `CLAUDE.md` (doc-map table).
**Interfaces:** consumes the final state of Tasks 1–12; produces nothing importable.

- [ ] **Step 1: Regenerate facts** (package sizes, entry points; script — see git history) — write from output, not memory.
- [ ] **Step 2: The page**, in order: one paragraph (what Kriko is + the category-free invariant); the fan diagram (copied from CLAUDE.md so they can't disagree); package→owns→read-first table (`app/`, `app/pipeline/`, `kriko/`, `packs/`, `packs/cars/pipeline/`, `extension/`); "Chasing X? read these" (listing→cards, claim visibility, pack contents, build/install, evidence origins, refusal rules — 2–3 real files each, line-anchored); entry points; how to run things. **Every path must exist.**
- [ ] **Step 3: Path check** (`MISSING: none`; script — see git history).
- [ ] **Step 4: Link rows** in `CLAUDE.md` (+ README). Step 5: suite. Step 6: commit `docs: a reading map for the tree`.

---

### Task 14: Repo tidy and backlog reconciliation

**Files:** delete `deploy/` (empty); modify `docs/USAGE.md`, `docs/INTERNALS.md`, `backlog.md`, `done.md`.
**Interfaces:** consumes Tasks 1–13; produces nothing importable.

- [ ] **Step 1: `rmdir deploy`** (git ignores empty dirs — may be working-tree-only; `find deploy -type f` first; non-empty ⇒ inspect).
- [ ] **Step 2: Stale refs** — `knowledge/|apps/|extension_ui/|backend/|ops/` outside historical/superpowers ⇒ fix to current path or delete the sentence.
- [ ] **Step 3: USAGE commands** — every `python -m X` must import (`GONE` lines get fixed/removed).
- [ ] **Step 4: `done.md`** — one entry per task (date + hash, match existing format).
- [ ] **Step 5: `backlog.md`** — B33 Phase 6b landed (`f038df9`); Phase 6c extension-manifest follow-up stays open; file new items surfaced here; **file the long-function residue as P2** (eight functions 90–194 lines from Step 6's report; readability item, not a bug).
- [ ] **Step 6: Final verification** — suite PASS; four layering greps silent (note: `packs.cars.pipeline.*` self-imports are not violations — match the test's scoping, don't edit the test); 80-line scan is a **report, not a gate** (the eight out-of-scope functions: `validate_part()` 194, `process.run()` 153, `run_part()` 152, `ledger_run.main()` 144, `export_all()` 142, `submit_findings()` 128, `lookup()` 119, `build_report()` 114 — print, don't fail).
- [ ] **Step 7: Commit** — `chore: reconcile docs and backlog with the simplification pass`.

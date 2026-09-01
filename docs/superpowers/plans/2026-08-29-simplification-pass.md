# Kriko Simplification and Readability Pass — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the engine's generic layer the only implementation of chunking, ingest, extraction, grounding, gating and title similarity, then make the resulting tree readable by a human investigating it cold.

**Architecture:** Kriko is a four-package fan — `app/` (interfaces) and `packs/` (category data) both depend on `kriko/` (the engine), and `kriko/` depends on neither. Phase 6b built the engine's generic modules but left the cars pack running pre-pivot forks of all of them. Every task below either deletes a fork by making cars *call* the engine with its own policy injected, or removes something that makes the tree hard to read.

**Tech Stack:** Python 3.14, pytest, SQLite (`sqlite3` stdlib), pydantic, FastAPI, tomllib, PyYAML.

**Spec:** `docs/superpowers/specs/2026-08-29-simplification-design.md`

## Global Constraints

- **Run tests with the repo venv:** `.venv/bin/python -m pytest`. A bare `python` does not exist on this machine.
- **The whole suite is the gate, always.** Run it before every commit, not a subset:

  ```bash
  .venv/bin/python -m pytest -o addopts="" -q
  ```

  **Baseline: 594 passed, ~24s.** Use `-o addopts=""` — `pytest.ini` already sets
  `-q`, so a plain `pytest -q` passes `-q` twice and pytest suppresses the
  `N passed` summary line entirely. Without the override you get a wall of dots
  and no count, which is how the number in an earlier draft of this plan was
  wrong for three commits.
- **`kriko/` may not import `app/`, `packs/`, `backend/` or `knowledge/`.** This is the load-bearing G6 invariant. `app/pipeline/tests/test_repo_invariants.py` enforces it; never weaken that test to make a task pass.
- **Behaviour is preserved except in Tasks 6–7**, which change behaviour deliberately. If `packs/cars/tests/test_pack_parity.py` breaks in any other task, the task is wrong — revert it, do not update the golden.
- **No hardcoded car data in `kriko/`.** No `make`, `engine_code`, `fuel`, or car vocabulary in executable positions. `kriko/tests/test_core_is_domain_free.py` walks the AST for this.
- **Commit per task**, with the message body explaining *why*, per `CONTRIBUTING.md`. End every commit message with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- **Do not push or open a PR.** The user integrates manually.
- **Baseline:** `f038df9` (Phase 6b, 594 tests green), spec at `b7c74a0`. Branch `feat/knowledge-engine-pivot`.

---

## File Structure

**Deleted by this plan:**

| File | Why |
|---|---|
| `packs/cars/pipeline/title_sim.py` | verbatim fork of `kriko/text/title_sim.py` |
| `packs/cars/pipeline/agent/gates.py` | orphaned; vocabulary → pack rows, structure → engine rule shapes |
| `packs/cars/pipeline/catalog/model_state.py` | zero references anywhere |

**Reduced to thin adapters over the engine:**

| File | Becomes |
|---|---|
| `packs/cars/pipeline/ledger/chunking.py` | cars' code-token detector wrapping `kriko.ledger.chunking` |
| `packs/cars/pipeline/ledger/ingest.py` | `kriko.ledger.ingest` with cars' blocklist and language check injected |
| `packs/cars/pipeline/ledger/extraction.py` | `kriko.ledger.extraction` with cars' extractor, detector and gate injected |

**Created:**

| File | Responsibility |
|---|---|
| `docs/PACK_CONTRACT.md` | what a pack must contain vs. what it may |
| `docs/ARCHITECTURE.md` | one-page reading map for a human investigating the tree |
| `kriko/tests/test_pack_contract.py` | asserts both shipped packs meet the documented minimum |
| `packs/cars/pipeline/claims/` | claim-shaping modules, grouped out of the flat drawer |
| `packs/cars/pipeline/util/` | plumbing modules, grouped out of the flat drawer |

---

### Task 1: Delete the `title_sim` fork

The warm-up, and the pattern every later collapse follows: a pack may import the
engine, so a pack-local copy of engine logic is never justified.
`packs/cars/pipeline/title_sim.py` and `kriko/text/title_sim.py` implement the
same Jaccard with the same 0.4 threshold and the same stopword list.

**Files:**
- Delete: `packs/cars/pipeline/title_sim.py`
- Modify: every importer found in Step 1

**Interfaces:**
- Consumes: `kriko.text.title_sim.title_tokens(title: str) -> set[str]`, `kriko.text.title_sim.title_similar(title_a: str, title_b: str, threshold: float = 0.4) -> bool`
- Produces: nothing new. Later tasks rely only on the fork being gone.

- [ ] **Step 1: Find every importer of the fork**

```bash
grep -rn "pipeline.title_sim\|pipeline import title_sim" --include='*.py' app kriko packs
```

Write the list down. It is expected to be small (the dedup path).

- [ ] **Step 2: Confirm the two implementations agree before deleting either**

Write this scratch check and run it. It is a throwaway, not a committed test:

```bash
.venv/bin/python - <<'PY'
from kriko.text import title_sim as engine
from packs.cars.pipeline import title_sim as fork
cases = [
    ("DQ381 mechatronics failure", "mechatronics failure on the DQ381"),
    ("timing chain stretch", "turbo actuator fault"),
    ("", "anything"),
    ("EA888 oil consumption at 120000 km", "oil consumption EA888"),
]
for a, b in cases:
    assert engine.title_tokens(a) == fork.title_tokens(a), (a, "tokens")
    assert engine.title_similar(a, b) == fork.title_similar(a, b), (a, b)
print("identical on all cases")
PY
```

Expected: `identical on all cases`. If it disagrees, STOP — the fork has drifted
and this is a behaviour change, not a deletion. Report it rather than proceeding.

- [ ] **Step 3: Repoint every importer at the engine**

For each file from Step 1, change the import. Example shape:

```python
# before
from packs.cars.pipeline.title_sim import title_similar, title_tokens
# after
from kriko.text.title_sim import title_similar, title_tokens
```

- [ ] **Step 4: Delete the fork**

```bash
git rm packs/cars/pipeline/title_sim.py
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, same test count as the baseline (594).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor(cars): drop the title_sim fork, call the engine

packs/cars/pipeline/title_sim.py reimplemented kriko/text/title_sim.py
verbatim — same Jaccard, same 0.4 threshold, same stopword list. Its
docstring justified the copy with "the engine cannot import a pack",
which is true and irrelevant: the dependency runs the other way, and a
pack importing the engine is the whole point of the fan.

Verified identical on both implementations before deleting.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: Collapse the chunking fork, and move car vocabulary out of the engine

`packs/cars/pipeline/ledger/chunking.py` duplicates the engine's chunker and
lexicon, adding only one thing: cars' `code_tokens()` detector. The engine's
`chunk_has_signal` already accepts `signal_terms`, but a *detector* is not a term
list, so cars injects it at the `signal_detector=` seam instead.

This task also fixes a G6 smell in the engine: `kriko/ledger/chunking.py`'s
`FAILURE_LEXICON` contains `misfire`, `judder`, `shudder`, `clog` and `rattle` —
car-repair vocabulary sitting in a category-free engine, directly under a
docstring claiming the vocabulary is "deliberately category-neutral".

**Files:**
- Modify: `packs/cars/pipeline/ledger/chunking.py` (becomes ~15 lines)
- Modify: `kriko/ledger/chunking.py:16-60` (`FAILURE_LEXICON`)
- Test: `packs/cars/pipeline/tests/test_ledger_chunking.py` (exists; must keep passing unchanged)
- Test: `kriko/tests/test_ledger_chunking.py` (create if absent)

**Interfaces:**
- Consumes: `kriko.ledger.chunking.chunk_text(text: str) -> list[Chunk]`, `kriko.ledger.chunking.chunk_has_signal(text: str, signal_terms: Iterable[str] = ()) -> bool`, `kriko.ledger.chunking.Chunk` (frozen dataclass: `index: int, start: int, end: int, text: str`), `CHUNK_CHARS: int = 4000`, `CHUNK_OVERLAP: int = 400`
- Consumes: `packs.cars.pipeline.stoplists.code_tokens(text: str) -> set[str]`
- Produces: `packs.cars.pipeline.ledger.chunking.chunk_has_signal(text: str) -> bool` and re-exports `chunk_text`, `Chunk`, `CHUNK_CHARS`, `CHUNK_OVERLAP` — the existing cars test imports all of these by those names.

- [ ] **Step 1: Run the existing cars chunking test and record it green**

Run: `.venv/bin/python -m pytest packs/cars/pipeline/tests/test_ledger_chunking.py -v`
Expected: PASS. These four assertions are the behaviour contract for this task —
especially `chunk_has_signal("the EA888 uses a different tensioner")`, which
passes only because of `code_tokens`.

- [ ] **Step 2: Rewrite the cars chunking module as an adapter**

Replace the entire contents of `packs/cars/pipeline/ledger/chunking.py` with:

```python
"""Cars' chunk gate: the engine's failure lexicon plus car code tokens.

Chunking itself is generic and lives in ``kriko.ledger.chunking``. The only
car-shaped part is what counts as signal — an engine or gearbox code makes a
chunk worth extracting even when it names no failure word. ``code_tokens`` is
catalog-derived, so a new part is covered the moment its stub exists.
"""

from kriko.ledger.chunking import (  # noqa: F401 — re-exported for callers
    CHUNK_CHARS,
    CHUNK_OVERLAP,
    Chunk,
    chunk_text,
)
from kriko.ledger.chunking import chunk_has_signal as _engine_has_signal
from packs.cars.pipeline.stoplists import CAR_FAILURE_TERMS, code_tokens


def chunk_has_signal(text: str) -> bool:
    """Whether this chunk is worth spending extraction tokens on."""
    if _engine_has_signal(text, signal_terms=CAR_FAILURE_TERMS):
        return True
    return bool(code_tokens(text))
```

- [ ] **Step 3: Move the car vocabulary out of the engine into the pack**

In `kriko/ledger/chunking.py`, remove these five car-repair terms from
`FAILURE_LEXICON`, leaving the rest (which are category-neutral failure words in
Turkish and English):

```
"misfire", "judder", "shudder", "clog", "rattle"
```

In `packs/cars/pipeline/stoplists.py`, add near the other frozensets (after
`GENERIC_MAINTENANCE_TERMS` at line 76):

```python
# Failure words specific to machines with engines and drivetrains. These used
# to sit in kriko/ledger/chunking.py's FAILURE_LEXICON, which made the engine
# hold car vocabulary. Closed engineering vocabulary, so a constant is allowed
# per CLAUDE.md's scalability-principle exception.
CAR_FAILURE_TERMS: frozenset[str] = frozenset({
    "misfire", "judder", "shudder", "clog", "rattle",
})
```

Net behaviour is identical: cars passes the terms back in via `signal_terms`.

- [ ] **Step 4: Run the cars chunking test**

Run: `.venv/bin/python -m pytest packs/cars/pipeline/tests/test_ledger_chunking.py -v`
Expected: PASS, all four assertions, unchanged file.

- [ ] **Step 5: Add the engine-side test proving the lexicon is now category-free**

Create or extend `kriko/tests/test_ledger_chunking.py`:

```python
"""kriko.ledger.chunking — generic chunking and the pre-LLM signal gate."""

from kriko.ledger.chunking import (
    CHUNK_CHARS, CHUNK_OVERLAP, chunk_has_signal, chunk_text,
)


def test_chunks_overlap_and_cover_the_whole_text():
    text = "x" * (CHUNK_CHARS * 2)
    chunks = chunk_text(text)
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
    assert chunks[1].start == CHUNK_CHARS - CHUNK_OVERLAP


def test_short_text_is_one_chunk():
    assert len(chunk_text("short")) == 1


def test_empty_text_still_yields_one_chunk():
    assert len(chunk_text("")) == 1


def test_the_default_lexicon_is_category_neutral():
    """A failure word any category shares is signal; a car word is not.

    The engine may not know what a misfire is — that is pack vocabulary, and
    it reaches the gate through signal_terms rather than through a constant
    here. Guards the G6 invariant at the one place it silently regressed.
    """
    assert chunk_has_signal("this part has a known failure")
    assert chunk_has_signal("bu parçada kronik arıza var")
    assert not chunk_has_signal("the engine has a misfire")
    assert chunk_has_signal("the engine has a misfire", signal_terms={"misfire"})


def test_filler_is_not_signal():
    assert not chunk_has_signal("today we unbox the new infotainment")
```

- [ ] **Step 6: Run the new engine test**

Run: `.venv/bin/python -m pytest kriko/tests/test_ledger_chunking.py -v`
Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Test count rises by the number of new tests in Step 5.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor(ledger): one chunker, and the engine forgets what a misfire is

packs/cars/pipeline/ledger/chunking.py held a second copy of the chunker
and the failure lexicon so it could add one thing: cars' code_tokens
detector. It now injects that at the seam the engine already provides
and re-exports the rest (56 -> ~20 lines).

Moving the fork exposed the inverse bug. kriko/ledger/chunking.py's
FAILURE_LEXICON carried "misfire", "judder", "shudder", "clog" and
"rattle" — car-repair vocabulary in a category-free engine, directly
under a docstring claiming the lexicon was "deliberately
category-neutral". Those five move to the pack and come back through
signal_terms, so behaviour is unchanged and the claim is now true.

Tested both ways round: the engine treats "misfire" as filler on its
own and as signal when a pack supplies it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Collapse the ingest fork

`packs/cars/pipeline/ledger/ingest.py` (172 lines) differs from
`kriko/ledger/ingest.py` (168) in exactly three ways: a `Document` type hint, a
`component_hint`/`subject_hint` key name that is `None` on both sides, and two
functions that hardcode cars' blocklist instead of using the engine's injected
default.

**Files:**
- Modify: `packs/cars/pipeline/ledger/ingest.py` (becomes ~30 lines)
- Test: `packs/cars/pipeline/tests/test_ledger_ingest.py` (exists; must keep passing unchanged)

**Interfaces:**
- Consumes: `kriko.ledger.ingest.ingest_document(conn, doc, source_type: str, target_hint: str) -> int`, `kriko.ledger.ingest.flag_blocked_sources(conn, is_blocked_source_domain=lambda _url: False) -> int`, `kriko.ledger.ingest.flag_foreign_language(conn, is_foreign_language=lambda _text: False) -> int`
- Consumes: `packs.cars.pipeline.stoplists.is_blocked_source_domain(url_or_host: str) -> bool`, `packs.cars.pipeline.stoplists.is_german_text(text: str, threshold: float = 0.02) -> bool`
- Produces: `packs.cars.pipeline.ledger.ingest.ingest_document(conn, doc: Document, source_type: str, target_hint: str) -> int`, `flag_blocked_sources(conn) -> int`, `flag_foreign_language(conn) -> int` — `app/pipeline/ledger_run.py:36-37`, `app/pipeline/remediate.py:119` and `packs/cars/pipeline/ledger/acquire.py:27` call these by exactly these names and arities. Do not change them.

- [ ] **Step 1: Record the fork's behaviour as green**

Run: `.venv/bin/python -m pytest packs/cars/pipeline/tests/test_ledger_ingest.py -v`
Expected: PASS. Note the test names — they are the contract:
`test_flag_blocked_sources_marks_only_blocked_domains`,
`test_flag_foreign_language_marks_only_german`,
`test_ingest_document_stores_hint_not_attribution`.

- [ ] **Step 2: Confirm the one substantive difference is a no-op**

The fork writes `"engine_or_variant_hint": None` where the engine writes
`"subject_hint": None`, in the backfill path. `kriko/ledger/db.py:insert_evidence`
resolves the column as `claim.get("component_hint") or claim.get("subject_hint")`,
so both spell `None`. Verify:

```bash
grep -n "component_hint.*or.*subject_hint" kriko/ledger/db.py
```

Expected: one hit inside `insert_evidence`. If the fallback chain differs from
this, STOP and report — the collapse would change what gets stored.

- [ ] **Step 3: Rewrite the cars ingest module as an adapter**

Replace the entire contents of `packs/cars/pipeline/ledger/ingest.py` with:

```python
"""Cars' ingest: the engine's ledger ingest with this pack's source policy.

Ingest — inserting documents, backfilling evidence, flagging rows out of
clustering — is generic and lives in ``kriko.ledger.ingest``. What is car
policy is *which* sources are untrustworthy and *which* language is foreign to
this pack's market, and those arrive as injected predicates.
"""

from kriko.ledger.ingest import ingest_document  # noqa: F401 — re-exported
from kriko.ledger import ingest as _engine
from packs.cars.pipeline.stoplists import is_blocked_source_domain, is_german_text


def flag_blocked_sources(conn) -> int:
    """Flag evidence whose source document is on cars' blocked-domain list."""
    return _engine.flag_blocked_sources(
        conn, is_blocked_source_domain=is_blocked_source_domain
    )


def flag_foreign_language(conn) -> int:
    """Flag evidence written in a language outside this pack's market."""
    return _engine.flag_foreign_language(conn, is_foreign_language=is_german_text)
```

Keep any other public name the module currently exports — re-check with
`grep -n "^def \|^[A-Z_]* =" ` against the pre-change file and re-export anything
a caller uses.

- [ ] **Step 4: Run the cars ingest test**

Run: `.venv/bin/python -m pytest packs/cars/pipeline/tests/test_ledger_ingest.py -v`
Expected: PASS, all three tests, test file unchanged.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, same count as after Task 2.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor(ledger): one ingest, with cars' source policy injected

The cars fork differed from kriko/ledger/ingest.py in three ways: a type
hint, a claim key that spells None either way (insert_evidence resolves
component_hint or subject_hint), and two functions that hardcoded cars'
blocklist where the engine already took the predicate as an argument.

172 -> ~30 lines. The public names ledger_run, remediate and acquire
call are unchanged.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: Collapse the extraction fork

The largest of the five. `packs/cars/pipeline/ledger/extraction.py` (122 lines)
reimplements the engine's chunk loop, cache check, budget charge and evidence
insert. The engine's version already takes `extractor=`, `signal_detector=` and
`gate_reason=`. Cars needs three things through those seams: langextract as the
extractor, its own chunk detector, and its `component_hint` remap.

**Files:**
- Modify: `packs/cars/pipeline/ledger/extraction.py` (becomes ~45 lines)
- Test: `packs/cars/pipeline/tests/test_ledger_extraction.py` (exists; must keep passing unchanged)

**Interfaces:**
- Consumes: `kriko.ledger.extraction.extract_document(conn, doc_id: int, budget: Budget, *, extractor: Callable[[str], Iterable[dict]], signal_detector: Callable[[str], bool] = chunk_has_signal, gate_reason: Callable[[dict], str | None] | None = None) -> int`
- Consumes: `kriko.ledger.extraction.extract_pending(conn, budget: Budget, **kwargs) -> int`, `kriko.ledger.extraction.pending_extraction_estimate(conn, signal_detector=chunk_has_signal) -> tuple[int, float]`
- Consumes: `packs.cars.pipeline.langextract_client.extract_grounded(text: str) -> Iterable[dict]`
- Produces: `packs.cars.pipeline.ledger.extraction.extract_document(conn, doc_id: int, budget: Budget) -> int`, `extract_pending(conn, budget: Budget) -> int`, `pending_extraction_estimate(conn) -> tuple[int, float]`. **These arities are load-bearing**: `app/pipeline/ledger_run.py:46,49`, `app/pipeline/remediate.py:193` and `app/pipeline/panel.py:76-77` call them positionally, and `app/pipeline/tests/test_ledger_run.py:12,26` monkeypatches `packs.cars.pipeline.ledger.extraction.extract_grounded` **by that dotted path** — so `extract_grounded` must remain a module-level name here, and the extractor must resolve it at call time, not at import time.

- [ ] **Step 1: Record the fork's behaviour as green**

Run: `.venv/bin/python -m pytest packs/cars/pipeline/tests/test_ledger_extraction.py app/pipeline/tests/test_ledger_run.py -v`
Expected: PASS. These cover caching, budget exhaustion, the low-value flag and
the monkeypatch path.

- [ ] **Step 2: Rewrite the cars extraction module as an adapter**

Replace the entire contents of `packs/cars/pipeline/ledger/extraction.py` with:

```python
"""Cars' extraction: the engine's chunk loop with this pack's policy injected.

Orchestration — chunking, the cache, the budget charge, the evidence insert —
is generic and lives in ``kriko.ledger.extraction``. Three things here are cars
policy: langextract as the extractor, the code-token chunk gate, and the
low-value rules that decide which extracted claims get flagged.

``extract_grounded`` stays a module-level name because app/pipeline's tests
monkeypatch it by dotted path; the extractor resolves it at call time so the
patch is seen.
"""

from collections.abc import Iterable

from kriko.ledger import extraction as _engine
from kriko.ledger.costs import Budget
from kriko.ledger.extraction import (  # noqa: F401 — re-exported for callers
    EXTRACTION_MODEL,
    EXTRACTOR_VERSION,
    estimate_chunk_tokens,
)
from packs.cars.pipeline.langextract_client import extract_grounded
from packs.cars.pipeline.ledger.chunking import chunk_has_signal
from packs.cars.pipeline.stoplists import (
    GENERIC_MAINTENANCE_TERMS,
    WARNING_LIGHT_PATTERNS,
    has_specificity_signal,
)


def _extract(text: str) -> Iterable[dict]:
    """Run langextract, then map its claim shape onto the ledger's.

    Resolved through the module global so a monkeypatched extract_grounded is
    honoured (app/pipeline/tests/test_ledger_run.py patches this dotted path).
    """
    for claim in extract_grounded(text):
        mapped = dict(claim)
        mapped["component_hint"] = claim.get("engine_or_variant_hint")
        yield mapped


def _low_value_reason(claim: dict) -> str | None:
    text = f"{claim.get('title', '')} {claim.get('rationale', '')}".lower()
    for pat in WARNING_LIGHT_PATTERNS:
        if pat.search(text):
            return "warning-light pattern"
    hit = next((kw for kw in GENERIC_MAINTENANCE_TERMS if kw in text), None)
    if hit and not has_specificity_signal(text):
        return f"generic maintenance: {hit!r}"
    return None


_POLICY = dict(
    extractor=_extract,
    signal_detector=chunk_has_signal,
    gate_reason=_low_value_reason,
)


def extract_document(conn, doc_id: int, budget: Budget) -> int:
    return _engine.extract_document(conn, doc_id, budget, **_POLICY)


def extract_pending(conn, budget: Budget) -> int:
    return _engine.extract_pending(conn, budget, **_POLICY)


def pending_extraction_estimate(conn) -> tuple[int, float]:
    return _engine.pending_extraction_estimate(conn, signal_detector=chunk_has_signal)
```

Note the one real difference from the fork: the fork passed the *original*
claim to `_deterministic_low_value_reason` and the *remapped* one to
`insert_evidence`. Here `_extract` remaps first, so `_low_value_reason` sees the
mapped dict. It reads only `title` and `rationale`, which the remap does not
touch, so the flag decision is identical.

- [ ] **Step 3: Run the extraction and run tests**

Run: `.venv/bin/python -m pytest packs/cars/pipeline/tests/test_ledger_extraction.py app/pipeline/tests/test_ledger_run.py app/pipeline/tests/test_ledger_remediate.py -v`
Expected: PASS, all tests, all three test files unchanged.

If `test_ledger_run.py` fails with the extractor returning real langextract
output, the monkeypatch is not being honoured — `_extract` is resolving
`extract_grounded` too early. Confirm it is read inside the function body, not
captured as a default argument or module constant.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Verify the last generic module now has a caller**

```bash
grep -rn "kriko.ledger.extraction\|kriko.ledger import extraction" --include='*.py' app packs | grep -v /tests/
```

Expected: at least one hit in `packs/cars/pipeline/ledger/extraction.py`. Before
this task the engine's extraction module had zero production callers.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor(ledger): one extraction loop, cars supplies the policy

kriko/ledger/extraction.py was written in Phase 6b to take an extractor,
a signal detector and a gate as arguments — exactly so a pack could
supply category policy without the engine knowing any. Nothing ever
called it. The cars fork went on re-implementing the chunk loop, the
cache check, the budget charge and the evidence insert around its own
copies.

Cars now injects three things and inherits the rest: langextract as the
extractor, the code-token chunk gate, and its low-value rules. 122 -> ~45
lines, and the engine's extraction path has a production caller for the
first time.

extract_grounded stays a module-level name resolved at call time —
app/pipeline's tests monkeypatch it by dotted path.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 5: Cars' low-value rules become pack rows

`packs/cars/vocabulary/gates.yaml` already declares cars' full gate vocabulary as
rows, and `kriko/gates.py` already evaluates it. But
`packs/cars/pipeline/ledger/extraction.py` still judges low value from
`stoplists.py` frozensets — two sources of truth for the same question.

**Files:**
- Modify: `packs/cars/pipeline/ledger/extraction.py` (the `_low_value_reason` written in Task 4)
- Test: `packs/cars/pipeline/tests/test_ledger_extraction.py`

**Interfaces:**
- Consumes: `kriko.gates.load_gates(conn, pack_id: str) -> GateVocabulary`, `kriko.gates.gate_reason(text: str, vocab: GateVocabulary) -> str | None`. `gate_reason` returns one of `"covered"`, `"generic"`, `"noise"`, `"ambiguous"`, or `None`.
- Produces: `_low_value_reason` keeps its `(claim: dict) -> str | None` signature; only the reason strings change.

- [ ] **Step 1: Confirm the row vocabulary covers what the frozensets cover**

```bash
.venv/bin/python - <<'PY'
import yaml, pathlib
rows = yaml.safe_load(pathlib.Path("packs/cars/vocabulary/gates.yaml").read_text())
flat = {k: [x["pattern"] if isinstance(x, dict) else x for x in (v or [])]
        for k, v in rows.items()}
for kind, patterns in flat.items():
    print(f"{kind}: {len(patterns)}")
from packs.cars.pipeline.stoplists import (
    GENERIC_MAINTENANCE_TERMS, INSPECTION_COVERED, AMBIGUOUS_INSPECTION_TERMS,
)
for name, const, kind in [
    ("GENERIC_MAINTENANCE_TERMS", GENERIC_MAINTENANCE_TERMS, "generic"),
    ("INSPECTION_COVERED", INSPECTION_COVERED, "covered"),
    ("AMBIGUOUS_INSPECTION_TERMS", AMBIGUOUS_INSPECTION_TERMS, "ambiguous"),
]:
    missing = sorted(set(const) - set(flat.get(kind, [])))
    print(f"\n{name} -> {kind}: {len(missing)} not in rows")
    for m in missing:
        print("   ", m)
PY
```

Any term printed as missing must be **added to `packs/cars/vocabulary/gates.yaml`**
under the matching key before continuing. Do not delete it from `stoplists.py`
yet — other callers still read those frozensets, and Task 7 handles them.

- [ ] **Step 2: Write the failing test**

Add to `packs/cars/pipeline/tests/test_ledger_extraction.py`:

```python
def test_low_value_reason_comes_from_pack_rows_not_python_constants():
    """The gate's vocabulary is data the pack ships, not an engine constant.

    A warning-light claim is rejected because packs/cars/vocabulary/gates.yaml
    declares that pattern under `noise` — not because a frozenset in
    stoplists.py happens to list it. The reason string is the rule kind, which
    is what makes a rejection traceable back to the row that caused it.
    """
    from packs.cars.pipeline.ledger.extraction import _low_value_reason

    assert _low_value_reason({"title": "ABS warning light comes on",
                              "rationale": ""}) == "noise"
    assert _low_value_reason({"title": "DQ381 mechatronics unit fails at 120000 km",
                              "rationale": "Known weak point."}) is None
```

- [ ] **Step 3: Run it and watch it fail**

Run: `.venv/bin/python -m pytest packs/cars/pipeline/tests/test_ledger_extraction.py::test_low_value_reason_comes_from_pack_rows_not_python_constants -v`
Expected: FAIL — `_low_value_reason` currently returns
`"warning-light pattern"`, not `"noise"`.

- [ ] **Step 4: Add `vocabulary_from_rows` to `kriko/gates.py`**

`load_gates(conn, pack_id)` reads `gate_terms` from an **installed** store. The
ledger pipeline runs offline, before install — it has only the YAML the pack will
later ship (`packs/cars/build.py:368` reads that file, `:744` emits the rows).
Both paths must compile the same rows the same way, so factor the compilation out:

```python
def vocabulary_from_rows(rows: dict[str, list[str]]) -> GateVocabulary:
    """Build a vocabulary from raw {kind: [pattern]} rows.

    ``load_gates`` reads those rows from an installed store; a pack's offline
    pipeline has only the YAML it will later ship. Both end up here, so the
    compilation and the fail-open behaviour cannot diverge.
    """
    def literals(kind: str) -> frozenset[str]:
        return frozenset(p.casefold() for p in rows.get(kind, ()))

    return GateVocabulary(
        covered=literals("covered"),
        generic=literals("generic"),
        ambiguous=literals("ambiguous"),
        noise_patterns=_compile(rows.get("noise", ())),
        specificity_patterns=_compile(rows.get("specificity", ())),
    )
```

Then change the last statement of `load_gates` from constructing `GateVocabulary`
directly to `return vocabulary_from_rows(rows)`. Its behaviour must not change —
`kriko/tests/test_gates.py` and `packs/cars/tests/test_gate_vocabulary.py` are the
check.

- [ ] **Step 5: Rewrite `_low_value_reason` against the pack's rows**

In `packs/cars/pipeline/ledger/extraction.py`, delete the `GENERIC_MAINTENANCE_TERMS`,
`WARNING_LIGHT_PATTERNS` and `has_specificity_signal` imports, and replace
`_low_value_reason` with:

```python
import functools

import yaml

from kriko.gates import GateVocabulary, gate_reason, vocabulary_from_rows
from packs.cars.pipeline.paths import PACK_ROOT


@functools.lru_cache(maxsize=1)
def _vocabulary() -> GateVocabulary:
    """Cars' gate vocabulary, read from the rows this pack ships.

    The same vocabulary/gates.yaml that packs/cars/build.py turns into
    gate_terms rows at install time. Reading it directly is what lets the
    offline pipeline and the serving path answer "is this worth surfacing"
    from one source. Cached: the ledger asks once per extracted claim and the
    file does not change inside a run. Fails open — a missing or unreadable
    file gates nothing, per CLAUDE.md's automation principle.
    """
    path = PACK_ROOT / "vocabulary" / "gates.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return GateVocabulary()
    rows = {
        kind: [e["pattern"] if isinstance(e, dict) else e for e in (entries or [])]
        for kind, entries in raw.items()
        if isinstance(entries, list)
    }
    return vocabulary_from_rows(rows)


def _low_value_reason(claim: dict) -> str | None:
    text = f"{claim.get('title', '')} {claim.get('rationale', '')}"
    return gate_reason(text, _vocabulary())
```

The `isinstance(entries, list)` filter is load-bearing: Task 6 adds a `limits:`
block to the same file which is a mapping, not a list, and it must not be read as
a set of patterns.

- [ ] **Step 6: Run the new test**

Run: `.venv/bin/python -m pytest packs/cars/pipeline/tests/test_ledger_extraction.py -v`
Expected: PASS, including the pre-existing low-value-flag tests. If an older test
asserts the literal string `"warning-light pattern"`, update that assertion to
`"noise"` — the reason vocabulary is intentionally changing to the rule kind.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor(cars): the extraction gate reads the pack's rows, not frozensets

packs/cars/vocabulary/gates.yaml has declared cars' gate vocabulary as
rows since Phase 6b, and kriko/gates.py has evaluated it. The ledger
pipeline went on asking stoplists.py's frozensets the same question, so
"what counts as a low-value claim" had two answers that nothing kept in
step.

The pipeline now asks the rows. Reason strings become the rule kind
(noise, generic, covered, ambiguous), which makes a rejection traceable
to the row that caused it rather than to a branch in Python.

kriko.gates gains vocabulary_from_rows() so the installed-store path and
a pack's offline pipeline compile the same rows the same way.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 6: The engine learns the structural gate rules

`packs/cars/pipeline/agent/gates.py` holds rules that are **not** vocabulary and
so cannot become rows: a title-length limit, a DTC-code shape check, a minimum
rationale length, and "reject anything with no config anchor at all". These are
generic rule *shapes* — any category wants a title that is a phrase not an essay,
and a rationale that explains rather than restates. Only their thresholds and
patterns are category-specific.

Move the shapes into `kriko/gates.py`, parameterised by pack-declared values.

**Files:**
- Modify: `kriko/gates.py`
- Modify: `packs/cars/vocabulary/gates.yaml` (add a `limits` block)
- Test: `kriko/tests/test_gates.py`

**Interfaces:**
- Consumes: `kriko.gates.GateVocabulary` (frozen dataclass, currently: `covered`, `generic`, `ambiguous`, `noise_patterns`, `specificity_patterns`), `kriko.gates.is_specific(text: str, vocab: GateVocabulary) -> bool`
- Produces: `GateVocabulary` gains `max_title_chars: int = 0` and `min_rationale_chars: int = 0` (0 meaning "not declared, do not check" — fail open). Produces `kriko.gates.structural_reasons(title: str, rationale: str, vocab: GateVocabulary, *, has_anchor: bool = False) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Add to `kriko/tests/test_gates.py`:

```python
from kriko.gates import GateVocabulary, structural_reasons


def test_undeclared_limits_gate_nothing():
    """Fail open: a pack that declares no limits gets no structural rejections.

    CLAUDE.md's automation principle — where a value cannot be derived, emit
    nothing rather than guess. A pack author who has not thought about title
    length must not have the engine's opinion imposed on them.
    """
    assert structural_reasons("x", "y", GateVocabulary()) == []


def test_a_title_over_the_declared_limit_is_rejected():
    vocab = GateVocabulary(max_title_chars=20)
    assert structural_reasons("x" * 21, "", vocab) != []
    assert structural_reasons("x" * 20, "", vocab) == []


def test_a_rationale_under_the_declared_minimum_is_rejected():
    vocab = GateVocabulary(min_rationale_chars=30)
    assert structural_reasons("a title", "too short", vocab) != []
    assert structural_reasons("a title", "y" * 30, vocab) == []


def test_text_with_no_specificity_anchor_is_rejected_when_patterns_exist():
    """A pack that declares what 'specific' looks like gets the anchor rule.

    A pack that declares no specificity patterns has no way to express the
    rule, so it does not get it — again, fail open rather than guess.
    """
    vocab = GateVocabulary(specificity_patterns=_compiled(r"\bmk\d\b"))
    assert structural_reasons("a vague problem", "", vocab) != []
    assert structural_reasons("mk4 fails", "", vocab) == []
    assert structural_reasons("a vague problem", "", vocab, has_anchor=True) == []
    assert structural_reasons("a vague problem", "", GateVocabulary()) == []


def _compiled(pattern: str):
    import re
    return (re.compile(pattern, re.IGNORECASE),)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest kriko/tests/test_gates.py -v`
Expected: FAIL with `ImportError: cannot import name 'structural_reasons'`.

- [ ] **Step 3: Implement in `kriko/gates.py`**

Extend the dataclass:

```python
@dataclass(frozen=True)
class GateVocabulary:
    covered: frozenset[str] = frozenset()
    generic: frozenset[str] = frozenset()
    ambiguous: frozenset[str] = frozenset()
    noise_patterns: tuple[re.Pattern, ...] = ()
    specificity_patterns: tuple[re.Pattern, ...] = ()
    # Structural limits the pack declares. Zero means "not declared": the
    # engine has no opinion about how long a good title is, only about the
    # shape of the rule.
    max_title_chars: int = 0
    min_rationale_chars: int = 0
```

Add the function:

```python
def structural_reasons(
    title: str,
    rationale: str,
    vocab: GateVocabulary,
    *,
    has_anchor: bool = False,
) -> list[str]:
    """Rejections that are about a claim's shape rather than its vocabulary.

    Every rule here is generic — a title should be a phrase, a rationale
    should explain, a claim should be tied to something specific. What each
    means numerically is the pack's declaration, and an undeclared limit is
    not checked at all.

    ``has_anchor`` lets a caller assert specificity the text cannot show, such
    as a component identifier carried in a separate field.
    """
    title = (title or "").strip()
    rationale = (rationale or "").strip()
    reasons: list[str] = []

    if not title:
        return ["title is empty — a claim must name a concrete failure mode"]

    if vocab.max_title_chars and len(title) > vocab.max_title_chars:
        reasons.append(
            f"title is {len(title)} chars — it should be a brief phrase naming "
            f"the failure, not a sentence (max {vocab.max_title_chars})"
        )

    if vocab.min_rationale_chars and len(rationale) < vocab.min_rationale_chars:
        reasons.append(
            f"rationale is {len(rationale)} chars — write 2–3 plain sentences a "
            f"non-expert can act on (min {vocab.min_rationale_chars})"
        )

    if vocab.specificity_patterns and not has_anchor:
        if not is_specific(f"{title} {rationale}", vocab):
            reasons.append(
                "nothing ties this to a specific configuration — name the "
                "identifier, variant or usage figure it applies to"
            )

    return reasons
```

Stop there. The two new fields keep their `0` defaults for now, so the engine
tests in Step 1 pass on their own. Step 6 wires them to the pack's declaration.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest kriko/tests/test_gates.py -v`
Expected: PASS.

- [ ] **Step 5: Declare cars' limits as rows**

The `gate_terms` table is `(pack_id, kind, pattern, note)` — see
`kriko/store/schema.sql:77`. A numeric limit has no natural column there, so it
rides as `kind='limit'`, `pattern=<name>`, `note=<value>`. That avoids a schema
migration, and a limit genuinely is a gate term: it is one more rule the pack
declares about what it will not surface.

Add to `packs/cars/vocabulary/gates.yaml`:

```yaml
limits:
    # A title over this is a sentence, not a failure name. A rationale under
    # the minimum is a restated title rather than an explanation. Both were
    # Python constants in the orphaned agent gate (title_is_verbose's
    # max_len=100 and MIN_RATIONALE_CHARS=60); they are category taste, so
    # this is where they belong.
    - { pattern: max_title_chars, note: "100" }
    - { pattern: min_rationale_chars, note: "60" }
```

Note the list-of-mappings shape rather than a plain mapping. It matches every
other kind in the file, so `packs/cars/build.py`'s existing emission loop handles
it unchanged, and Task 5's `isinstance(entries, list)` filter keeps reading it.

- [ ] **Step 6: Teach the builder and the loaders about the new kind**

`packs/cars/build.py:754` **raises** on unknown gate kinds, so `limits` must be
declared or the pack stops building. In `packs/cars/build.py`, add `"limits"` to
both the emission tuple at line 732 and the known-kinds set at line 750:

```python
        for kind in ("covered", "generic", "ambiguous", "noise", "specificity", "limits"):
```

```python
        unknown_gates = set(gate_cfg) - {
            "covered",
            "generic",
            "ambiguous",
            "noise",
            "specificity",
            "limits",
        }
```

Do the same in `kriko/pack/build.py:435`'s emission if it enumerates kinds — check
first:

```bash
grep -n "covered\|specificity\|gate_terms" kriko/pack/build.py
```

Then read the limits back in `kriko/gates.py`'s `vocabulary_from_rows`. The
function currently receives `{kind: [pattern]}`; limits need their note too, so
give it an optional second argument rather than changing the existing shape:

```python
def vocabulary_from_rows(
    rows: dict[str, list[str]],
    limits: dict[str, str] | None = None,
) -> GateVocabulary:
    """Build a vocabulary from raw {kind: [pattern]} rows.

    ``limits`` carries the numeric declarations, which ride in gate_terms as
    kind='limits' with the value in the note column. An unparseable or absent
    limit becomes 0, which means "not declared" and gates nothing.
    """
    def literals(kind: str) -> frozenset[str]:
        return frozenset(p.casefold() for p in rows.get(kind, ()))

    def limit(name: str) -> int:
        try:
            return int((limits or {}).get(name, 0))
        except (TypeError, ValueError):
            return 0

    return GateVocabulary(
        covered=literals("covered"),
        generic=literals("generic"),
        ambiguous=literals("ambiguous"),
        noise_patterns=_compile(rows.get("noise", ())),
        specificity_patterns=_compile(rows.get("specificity", ())),
        max_title_chars=limit("max_title_chars"),
        min_rationale_chars=limit("min_rationale_chars"),
    )
```

In `load_gates`, collect the notes for `kind='limits'` alongside the patterns:

```python
def load_gates(conn, pack_id: str) -> GateVocabulary:
    """Load one pack's gate rows, returning an empty vocabulary if absent."""
    rows: dict[str, list[str]] = {}
    limits: dict[str, str] = {}
    for row in conn.execute(
        "SELECT kind, pattern, note FROM gate_terms WHERE pack_id = ?", (pack_id,)
    ):
        if row["kind"] == "limits":
            limits[row["pattern"]] = row["note"]
        else:
            rows.setdefault(row["kind"], []).append(row["pattern"])
    return vocabulary_from_rows(rows, limits)
```

And in the cars pipeline's `_vocabulary()` from Task 5, split the limits out of
the YAML the same way before calling:

```python
    entries = raw.pop("limits", None) or []
    limits = {
        e["pattern"]: str(e.get("note", ""))
        for e in entries
        if isinstance(e, dict) and "pattern" in e
    }
    rows = {
        kind: [e["pattern"] if isinstance(e, dict) else e for e in (v or [])]
        for kind, v in raw.items()
        if isinstance(v, list)
    }
    return vocabulary_from_rows(rows, limits)
```

- [ ] **Step 7: Verify the round-trip through a real build**

Run: `.venv/bin/python -m pytest packs/cars/tests/test_gate_vocabulary.py app/pipeline/tests/test_repo_invariants.py -v`
Expected: PASS, including `test_every_pack_in_the_repo_builds_and_is_not_empty`.
That test is what catches a `limits` block the builder refuses.

Then confirm the limits survive install:

```bash
.venv/bin/python - <<'LIM'
import sqlite3, subprocess, tempfile, pathlib
out = pathlib.Path(tempfile.mkdtemp()) / "cars.kpack"
subprocess.run(["python", "-m", "packs.cars.build", "--out", str(out)], check=True)
conn = sqlite3.connect(out)
print(list(conn.execute(
    "SELECT kind, pattern, note FROM gate_terms WHERE kind='limits'")))
LIM
```

Expected: both limits present with their values. Adjust the build invocation to
whatever `packs/cars/build.py:main` actually accepts.

- [ ] **Step 8: Verify the engine is still category-free**

Run: `.venv/bin/python -m pytest kriko/tests/test_core_is_domain_free.py -v`
Expected: PASS. The new code names no car concept — "identifier", "variant",
"usage figure", never "engine code", "gearbox" or "mileage".

- [ ] **Step 9: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -F - <<'EOF'
feat(gates): the engine learns rule shapes, the pack keeps the numbers

Some of the orphaned agent gate is not vocabulary and cannot be a row: a
title-length limit, a minimum rationale, "reject anything with no
specificity anchor". Those are generic rule shapes — every category wants
a title that is a phrase and a rationale that explains — and only their
thresholds are taste.

kriko.gates.structural_reasons() implements the shapes; cars declares
max_title_chars: 100 and min_rationale_chars: 60 in its gates.yaml,
straight from the constants the agent gate used. An undeclared limit is
not checked, so a pack that has not thought about title length does not
get the engine's opinion imposed on it.

The wording stays category-free: identifier, variant, usage figure —
never engine code, gearbox or mileage. test_core_is_domain_free passes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 7: Wire the gate into the agent write path, and delete the orphan

**This task changes behaviour on purpose.** `app/mcp_server.py:submit_findings`
currently checks only that the quote appears in the document. The 243-line gate
that enforced the product principle at write time
(`packs/cars/pipeline/agent/gates.py`) has no caller and no test, so the agent
research path writes evidence the product principle says to drop.

**Files:**
- Modify: `app/mcp_server.py:259-330` (`submit_findings`)
- Delete: `packs/cars/pipeline/agent/gates.py`
- Test: `app/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `kriko.gates.load_gates(conn, pack_id: str) -> GateVocabulary`, `kriko.gates.gate_reason(text, vocab) -> str | None`, `kriko.gates.structural_reasons(title, rationale, vocab, *, has_anchor=False) -> list[str]`
- Consumes: `kriko.extract.grounding.is_grounded(source: str, quote: str) -> bool`
- Produces: `submit_findings` keeps its `(subject_id: str, pack_id: str, findings: list[dict]) -> dict` signature and its `{"accepted": [...], "rejected": [{"title": ..., "reason": ...}]}` result shape.

- [ ] **Step 1: Write the failing tests**

Add to `app/tests/test_mcp_server.py`, in the grounding-rule section around
line 144:

```python
def test_a_warning_light_finding_is_refused_by_the_packs_own_gate(store):
    """The product principle is enforced at write time, not requested in a prompt.

    packs/cars/vocabulary/gates.yaml declares dashboard-warning-light language
    under `noise`. A finding matching it must not become evidence, and the
    agent must be told which rule refused it — a prompt asks, a gate decides.
    """
    result = submit_findings(SUBJECT_ID, PACK_ID, [{
        "title": "ABS warning light illuminates",
        "rationale": "The ABS light can come on and should be investigated by a mechanic.",
        "quote": "the ABS warning light illuminates",
        "document_text": "Owners report the ABS warning light illuminates.",
        "source_url": "https://example.test/a",
    }])
    assert result["accepted"] == []
    assert result["rejected"][0]["reason"] == "noise"


def test_a_config_specific_finding_still_lands(store):
    """The gate must not swallow what Kriko exists to surface."""
    result = submit_findings(SUBJECT_ID, PACK_ID, [{
        "title": "DQ381 mechatronics failure from 120000 km",
        "rationale": "The mechatronics unit is a documented weak point on this "
                     "gearbox and replacement is expensive.",
        "quote": "DQ381 mechatronics failure",
        "document_text": "Reports of DQ381 mechatronics failure are common.",
        "source_url": "https://example.test/b",
    }])
    assert result["rejected"] == []
    assert len(result["accepted"]) == 1
```

Adapt `store`, `SUBJECT_ID` and `PACK_ID` to the fixtures the existing test file
already uses — read the top of `app/tests/test_mcp_server.py` first and match its
conventions rather than inventing new ones. The subject must exist in the pack,
or `submit_findings` returns `{"error": ...}` before reaching the gate.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest app/tests/test_mcp_server.py -k "warning_light or config_specific" -v`
Expected: FAIL — the warning-light finding is currently accepted.

- [ ] **Step 3: Wire the gate and the grounding helper into `submit_findings`**

In `app/mcp_server.py`, add the imports:

```python
from kriko.extract.grounding import is_grounded
from kriko.gates import gate_reason, load_gates, structural_reasons
```

Load the vocabulary once per call, immediately after the subject check:

```python
        vocab = load_gates(conn, pack_id)
```

Replace the inline quote check with the engine helper:

```python
            if document and not is_grounded(document, quote):
```

and insert the gate immediately after the `document` checks, before the
`source_id` line:

```python
            rationale = (item.get("rationale") or "").strip()
            reason = gate_reason(f"{title} {rationale}", vocab)
            if reason:
                rejected.append({"title": title, "reason": reason})
                continue

            structural = structural_reasons(
                title, rationale, vocab,
                has_anchor=bool(item.get("component") or item.get("component_hint")),
            )
            if structural:
                rejected.append({"title": title, "reason": "; ".join(structural)})
                continue
```

- [ ] **Step 4: Run the new tests**

Run: `.venv/bin/python -m pytest app/tests/test_mcp_server.py -v`
Expected: PASS, including the pre-existing grounding tests.

If an existing test now fails because its fixture finding is too generic to
survive the gate, that is the gate working. Make the fixture specific enough to
pass — do **not** weaken the gate. If a fixture cannot reasonably be made
specific, report it rather than guessing.

- [ ] **Step 5: Delete the orphan and check nothing referenced it**

```bash
grep -rn "agent.gates\|agent import gates" --include='*.py' app kriko packs
git rm packs/cars/pipeline/agent/gates.py
grep -rn "packs/cars/pipeline/agent/gates" docs/ *.md
```

Update the `docs/USAGE.md:114` reference found by the last grep to point at
`kriko/gates.py` and `packs/cars/vocabulary/gates.yaml` instead.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'EOF'
fix(mcp): submit_findings enforces the product principle again

The agent write path stopped applying the product principle at some point
in the pivot and nobody noticed, because the gate that enforced it —
packs/cars/pipeline/agent/gates.py, 243 lines — was left with no caller
and no test. submit_findings checked only that the quote appeared in the
document, so a "ABS warning light comes on" finding became evidence.

It now asks the pack's own rows (kriko.gates.gate_reason) and the shared
structural rules (structural_reasons), and uses
kriko.extract.grounding.is_grounded instead of an inline `in` check —
that module had zero callers too.

The orphan is deleted: its vocabulary is rows, its thresholds are rows,
its rule shapes are in the engine. Nothing of it is lost, and there is
now one place to change what Kriko refuses to store.

Behaviour change, deliberate and tested both ways: a warning-light
finding is refused with the rule that refused it, a DQ381 mechatronics
finding still lands.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 8: Write the pack contract, and test it

`packs/drill/` is five YAML files. `packs/cars/` is 12,900 lines. Nothing states
which parts are required, so a third-party author has two examples that disagree
by three orders of magnitude and no rule to follow.

**Files:**
- Create: `docs/PACK_CONTRACT.md`
- Create: `kriko/tests/test_pack_contract.py`
- Modify: `README.md` (link the contract from the pack-authoring section)

**Interfaces:**
- Consumes: `kriko.pack.manifest.load(root) -> Manifest`. `Manifest` exposes `root`, `pack_id`, `name`, `version`, `publisher`, `license`, `origin_url`, `identity_keys: dict[str, list[str]]`, `raw: dict`, and the properties `vocabulary_dir` and `data_dir`.
- Produces: nothing importable. The test is the enforcement.

- [ ] **Step 1: Write the failing test**

Create `kriko/tests/test_pack_contract.py`:

```python
"""Every pack in the repo meets the contract docs/PACK_CONTRACT.md states.

The document is the thing a third-party author reads; this test is what stops
it becoming fiction. Both shipped packs are checked, because a contract with
one example is indistinguishable from that example.
"""

from pathlib import Path

import pytest

from kriko.pack.manifest import load

REPO = Path(__file__).resolve().parents[2]
PACKS = sorted(p for p in (REPO / "packs").iterdir() if (p / "pack.toml").exists())


def test_the_repo_ships_more_than_one_pack():
    """A contract validated against a single pack proves nothing."""
    assert len(PACKS) >= 2, f"found only {[p.name for p in PACKS]}"


@pytest.mark.parametrize("root", PACKS, ids=lambda p: p.name)
def test_pack_meets_the_required_minimum(root):
    manifest = load(root)
    assert manifest.pack_id, "[pack] id is required"
    assert manifest.name, "[pack] name is required"
    assert manifest.version, "[pack] version is required"
    assert manifest.identity_keys, (
        "[identity] must declare at least one subject kind, or every subject "
        "of that kind hashes to the same id"
    )
    for kind, keys in manifest.identity_keys.items():
        assert keys, f"[identity] {kind} declares no attribute keys"
    assert manifest.data_dir.is_dir(), "data/ is required — a pack is its rows"
    assert any(manifest.data_dir.rglob("*.yaml")), "data/ holds no rows"


@pytest.mark.parametrize("root", PACKS, ids=lambda p: p.name)
def test_pack_has_a_readme_stating_what_it_covers(root):
    assert (root / "README.md").is_file(), (
        "a pack is a thing someone installs; it must say what it covers"
    )
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest kriko/tests/test_pack_contract.py -v`
Expected: PASS for both packs. If `packs/drill` fails any assertion, that is the
contract telling you the minimum is wrong — **fix the document and the test to
match reality**, do not add files to `drill` to satisfy an invented rule.

- [ ] **Step 3: Write the contract document**

Create `docs/PACK_CONTRACT.md`. It must state, with no hedging:

- The required minimum, exactly as `kriko/pack/manifest.py` enforces it:
  `pack.toml` with `[pack]` `id`, `name`, `version`; a non-empty `[identity]`
  table mapping subject kind → attribute keys; a `data/` directory of rows; a
  `README.md`.
- Why `[identity]` is the most consequential declaration: it decides what counts
  as the same product, and therefore which rows merge with another pack's.
- The optional parts, each with one line on what it buys you and which shipped
  pack demonstrates it: `vocabulary/` (gate terms and adapter vocabulary — both
  packs), `research/` (this category's own principle and templates — both),
  `trust/` (source tiers — cars), `adapters/` (site scraping rules — cars),
  `build.py` (a custom builder when the generic one is not enough — cars),
  `pipeline/` (this category's own evidence pipeline — cars), `coverage.py`
  (a category-specific coverage report — cars).
- A "start here" line: copy `packs/drill/` for the minimum, read `packs/cars/`
  for what a mature pack grows into.
- A pointer to `kriko/tests/test_pack_contract.py` as the enforcement.

- [ ] **Step 4: Link it from the README**

Add the link wherever `README.md` discusses authoring or installing packs. Verify
the path resolves:

```bash
grep -n "PACK_CONTRACT" README.md && test -f docs/PACK_CONTRACT.md && echo OK
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -F - <<'EOF'
docs: state the pack contract, and test that both packs meet it

packs/drill is five YAML files, packs/cars is 12,900 lines, and nothing
said which parts were required. A third-party author had two examples
disagreeing by three orders of magnitude and no rule — which makes G6
("adding a category is a data change") unlandable by anyone who did not
write the engine.

docs/PACK_CONTRACT.md states the minimum manifest.py already enforces,
and names each optional part with the pack that demonstrates it.
kriko/tests/test_pack_contract.py checks both shipped packs against it,
including a guard that the repo ships more than one — a contract
validated against a single pack proves nothing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 9: Delete dead code — COMPLETED AS A NO-OP

**Outcome: nothing was dead. Nothing was deleted.**

This task assumed `packs/cars/pipeline/catalog/model_state.py` was unreferenced.
It is not — `packs/cars/pipeline/tests/test_model_state.py` imports it and
exercises it across eleven tests. The claim came from a grep for the dotted path
`packs.cars.pipeline.catalog.model_state`, which cannot match the
`from ... import model_state` form the test actually uses.

Re-run correctly (all import styles, no test-directory filter, entry-point and
doc-mention detection), **the repo contains no dead modules**. Every candidate is
either a test file — pytest discovers those without anything importing them — or
a `python -m` entry point reachable from `docs/USAGE.md` or its own docstring.

All six modules this task expected to confirm alive are alive, as expected:

```
packs/cars/pipeline/catalog/doctor.py
packs/cars/pipeline/catalog/repair_missing_stub_scaffold.py
packs/cars/pipeline/fitment/validate_fitment.py
packs/cars/pipeline/scaffold.py
packs/cars/pipeline/ledger/eval_verdict.py
packs/cars/pipeline/consequence_tier.py
```

If you need to re-check this in future, the query that works is below. The one
that does not is any search for a dotted module path, because it silently misses
`from <package> import <module>`:

```bash
.venv/bin/python - <<'DEADCODE'
import ast, pathlib, re
root = pathlib.Path('.')
mods, srcs = {}, {}
for p in root.rglob('*.py'):
    s = str(p)
    if any(x in s for x in ('node_modules', '.venv', '__pycache__', '.superpowers')):
        continue
    srcs[s] = p.read_text(errors='ignore')
    if p.name != '__init__.py':
        mods[s] = (p.stem, s[:-3].replace('/', '.'))
for path, (stem, dotted) in sorted(mods.items()):
    hits = sum(
        1 for other, text in srcs.items()
        if other != path and (
            re.search(rf'\b{re.escape(dotted)}\b', text)
            or re.search(rf'import\s+{re.escape(stem)}\b', text)
            or re.search(rf'from\s+\S*\s+import\s+[^\n]*\b{re.escape(stem)}\b', text)
        )
    )
    if hits == 0:
        entry = 'if __name__' in srcs[path]
        print(f"{path}  entry_point={entry}")
DEADCODE
```

---

### Task 10: Break `packs/cars/build.py`'s 457-line `build()`

**Files:**
- Modify: `packs/cars/build.py:357-816`
- Test: `packs/cars/tests/test_pack_parity.py`, `app/pipeline/tests/test_repo_invariants.py` (both exist; must stay green **unchanged** — they are the behaviour proof)

**Interfaces:**
- Consumes: existing module-private helpers `_yaml`, `_now`, `_num`, `_vocabulary`, `_identity_of`, `_label`, `_compat_conditions`, `_conditions_from`, `_part_spans`.
- Produces: `build(out_path: Path) -> tuple[Path, dict]` — signature unchanged. `main(argv=None) -> int` unchanged. New private stage functions are internal; nothing outside the module may call them.

- [ ] **Step 1: Capture the current output as a byte-level baseline**

```bash
.venv/bin/python -m packs.cars.build --out /tmp/cars-before.kpack
sha256sum /tmp/cars-before.kpack | tee /tmp/cars-before.sha
```

Adjust the flag to whatever `main()` actually accepts — read `packs/cars/build.py:817`
first. If the build is not reproducible byte-for-byte (it stamps `_now()`),
compare row counts instead:

```bash
.venv/bin/python - <<'PY'
import sqlite3, sys
conn = sqlite3.connect("/tmp/cars-before.kpack")
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
for t in tables:
    print(t, conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
PY
```

Save that output to `/tmp/cars-before.counts`.

- [ ] **Step 2: Read `build()` and write down its stages**

```bash
sed -n '357,816p' packs/cars/build.py
```

Identify the sequential phases — typically: load catalog YAML, emit subjects,
emit attributes, emit claims with their conditions, emit evidence and sources,
emit vocabulary and gate rows, emit adapters, write the manifest row. Write the
list down before editing anything. **Do not invent stages that are not there**;
follow the blank-line and comment-banner structure the function already has.

- [ ] **Step 3: Extract one stage at a time**

For each stage, extract a module-level private function taking exactly what it
needs and returning exactly what the next stage consumes. Shape:

```python
def _emit_subjects(conn, catalog: dict, pack_id: str) -> dict[str, str]:
    """Write one subject row per catalog variant; return variant_id -> subject_id."""
    # ← the existing lines from build(), moved verbatim, not rewritten
```

The body is always code that already exists: cut it from `build()` and paste it
here unchanged. If you find yourself *writing* logic in a stage function, you have
left refactoring and started editing — stop and reconsider the boundary.

After **each** extraction, run:

```bash
.venv/bin/python -m pytest packs/cars/tests/ app/pipeline/tests/test_repo_invariants.py -q
```

Expected: PASS every time. Extracting one stage at a time is what makes a
mistake findable; a single 457-line rewrite is not reviewable.

- [ ] **Step 4: Confirm `build()` is now a readable sequence**

`build()` should read as a list of named calls plus the return. Verify the length:

```bash
.venv/bin/python - <<'PY'
import ast, pathlib
t = ast.parse(pathlib.Path("packs/cars/build.py").read_text())
for n in ast.walk(t):
    if isinstance(n, ast.FunctionDef):
        ln = (n.end_lineno or n.lineno) - n.lineno
        if ln > 80:
            print(f"STILL LONG: {n.name}() {ln} lines at :{n.lineno}")
print("checked")
PY
```

Expected: `checked` with no `STILL LONG` lines.

- [ ] **Step 5: Prove the built pack is unchanged**

```bash
.venv/bin/python -m packs.cars.build --out /tmp/cars-after.kpack
```

Then re-run the row-count script from Step 1 against `/tmp/cars-after.kpack` and
diff against `/tmp/cars-before.counts`. Expected: no differences. If any count
moved, a stage extraction dropped or duplicated rows — find it before committing.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor(cars): build() becomes a sequence of named stages

457 lines in one function, which is the single least readable thing in
the repo — you cannot hold it in your head, and you cannot review a
change to it without re-reading all of it.

Extracted one stage at a time, running the parity and pack-build tests
after each, so a mistake would surface at the stage that caused it. The
built pack is row-for-row identical, checked by table counts before and
after.

No signature changed; the stages are module-private.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 11: Break `kriko/pack/build.py`'s 300-line `build()`

Same shape as Task 10, on the generic builder. This one matters more per line:
it is the engine's, so every pack author reads it.

**Files:**
- Modify: `kriko/pack/build.py:168-467`
- Test: `kriko/tests/test_pack_build.py` (exists; must stay green unchanged)

**Interfaces:**
- Produces: `build(...)` — read the current signature at `kriko/pack/build.py:168` and preserve it **exactly**, including keyword-only markers and defaults. `packs/cars/build.py` and `packs/drill` both depend on it.

- [ ] **Step 1: Record the signature and the tests as green**

```bash
sed -n '168,175p' kriko/pack/build.py
.venv/bin/python -m pytest kriko/tests/test_pack_build.py -v
```

Write the signature down verbatim. Expected: PASS.

- [ ] **Step 2: Read `build()` and list its stages**

```bash
sed -n '168,467p' kriko/pack/build.py
```

Write the list down before editing.

- [ ] **Step 3: Extract one stage at a time**

After each extraction:

```bash
.venv/bin/python -m pytest kriko/tests/test_pack_build.py packs/ -q
```

Expected: PASS every time. `packs/` is included because both shipped packs go
through this builder — the drill pack is the only check that the generic path
still works for a pack with no `pipeline/`.

- [ ] **Step 4: Confirm no function over 80 lines remains in the file**

```bash
.venv/bin/python - <<'PY'
import ast, pathlib
t = ast.parse(pathlib.Path("kriko/pack/build.py").read_text())
for n in ast.walk(t):
    if isinstance(n, ast.FunctionDef):
        ln = (n.end_lineno or n.lineno) - n.lineno
        if ln > 80:
            print(f"STILL LONG: {n.name}() {ln} lines at :{n.lineno}")
print("checked")
PY
```

Expected: `checked`, no long functions.

- [ ] **Step 5: Confirm the signature is byte-identical to Step 1**

```bash
sed -n '/^def build/,/) ->/p' kriko/pack/build.py
```

Compare against what you wrote down. Any difference is a break for both packs.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor(pack): the generic builder becomes a sequence of named stages

300 lines in one function, in the engine, which is the code every pack
author reads to understand what a build does. Extracted one stage at a
time with both shipped packs building after each — drill is the only
check that the generic path still works for a pack with no pipeline/.

The signature is unchanged, verified byte-for-byte; cars and drill both
depend on it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 12: Group the flat drawer

`packs/cars/pipeline/` holds 14 loose modules beside 6 tidy subpackages, so the
directory listing tells you nothing about what is what.

**Files:**
- Create: `packs/cars/pipeline/claims/__init__.py`, `packs/cars/pipeline/util/__init__.py`
- Move: as listed in Step 2
- Modify: every importer

**Interfaces:**
- Produces: same module contents at new dotted paths. No signature changes.

- [ ] **Step 1: Record the current import graph**

```bash
grep -rn "from packs.cars.pipeline import\|from packs.cars.pipeline\." \
  --include='*.py' app kriko packs > /tmp/imports-before.txt
wc -l /tmp/imports-before.txt
```

- [ ] **Step 2: Move the claim-shaping modules**

```bash
mkdir -p packs/cars/pipeline/claims
cat > packs/cars/pipeline/claims/__init__.py <<'PY'
"""Rules that shape a claim after extraction: grounding, tiering, dedup.

These decide what a claim says and whether it survives — as opposed to
``packs.cars.pipeline.ledger``, which decides how evidence is gathered.
"""
PY
git mv packs/cars/pipeline/ground_year_window.py       packs/cars/pipeline/claims/
git mv packs/cars/pipeline/ground_mileage_threshold.py packs/cars/pipeline/claims/
git mv packs/cars/pipeline/consequence_tier.py         packs/cars/pipeline/claims/
git mv packs/cars/pipeline/maintenance.py              packs/cars/pipeline/claims/
git mv packs/cars/pipeline/dedup.py                    packs/cars/pipeline/claims/
```

- [ ] **Step 3: Move the plumbing modules**

```bash
mkdir -p packs/cars/pipeline/util
cat > packs/cars/pipeline/util/__init__.py <<'PY'
"""Plumbing with no car opinion in it: YAML loading and domain names."""
PY
git mv packs/cars/pipeline/yamlutil.py packs/cars/pipeline/util/
git mv packs/cars/pipeline/domains.py  packs/cars/pipeline/util/
```

**`paths.py` stays where it is.** It derives every location from
`PIPELINE_ROOT = Path(__file__).resolve().parent`, so its correctness depends on
the file sitting directly in `pipeline/`. Moving it into `util/` would silently
shift `PIPELINE_ROOT`, `PACK_ROOT` and `REPO_ROOT` one directory down — the kind
of break that imports fine and fails later on a path that does not exist. A
module whose location *is* its meaning belongs at the root of what it measures.

- [ ] **Step 4: Repoint every importer**

```bash
grep -rlE "packs\.cars\.pipeline\.(ground_year_window|ground_mileage_threshold|consequence_tier|maintenance|dedup)" \
  --include='*.py' app kriko packs \
  | xargs sed -i -E 's/packs\.cars\.pipeline\.(ground_year_window|ground_mileage_threshold|consequence_tier|maintenance|dedup)/packs.cars.pipeline.claims.\1/g'

grep -rlE "packs\.cars\.pipeline\.(yamlutil|domains)" \
  --include='*.py' app kriko packs \
  | xargs sed -i -E 's/packs\.cars\.pipeline\.(yamlutil|domains)/packs.cars.pipeline.util.\1/g'
```

Then catch the `from packs.cars.pipeline import X` form, which the above misses:

```bash
grep -rn "from packs.cars.pipeline import" --include='*.py' app kriko packs
```

Fix each by hand.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. An `ImportError` here names the module that was missed.

- [ ] **Step 6: Check the docs for stale paths**

```bash
grep -rnE "pipeline/(yamlutil|domains|dedup|maintenance|consequence_tier|ground_)" docs/ *.md
```

Update each hit.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'EOF'
refactor(cars): group the pipeline's flat drawer

14 loose modules sat beside 6 subpackages, so `ls packs/cars/pipeline`
told you nothing. They divide cleanly: claims/ holds what shapes a claim
after extraction (grounding windows, consequence tiering, maintenance
reclassification, dedup), util/ holds plumbing with no car opinion in it
(yaml loading, domain names). paths.py stays put: it derives every location
from its own __file__, so its directory is part of its meaning.

Moves only; no signature changed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 13: Write the reading map

The deliverable the user actually asked for: a page that makes the tree
investigable without reading it all first.

**Files:**
- Create: `docs/ARCHITECTURE.md`
- Modify: `README.md`, `CLAUDE.md` (documentation map table)

**Interfaces:**
- Consumes: the final state of every earlier task.
- Produces: nothing importable.

- [ ] **Step 1: Regenerate the facts rather than remembering them**

```bash
echo "=== package sizes ==="
for d in app kriko packs; do
  echo -n "$d: "; find $d -name '*.py' -not -path '*/tests/*' | xargs wc -l | tail -1
done
echo "=== entry points ==="
grep -rln "if __name__ == ." --include='*.py' app kriko packs | grep -v /tests/ | sort
echo "=== longest functions ==="
.venv/bin/python - <<'PY'
import ast, pathlib
rows = []
for p in pathlib.Path('.').rglob('*.py'):
    s = str(p)
    if 'node_modules' in s or '/tests/' in s or s.startswith('.venv'):
        continue
    try:
        t = ast.parse(p.read_text())
    except Exception:
        continue
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ln = (n.end_lineno or n.lineno) - n.lineno
            if ln >= 80:
                rows.append((ln, s, n.name))
for ln, s, name in sorted(rows, reverse=True)[:10]:
    print(f"{ln:5d}  {s}  {name}()")
print("done")
PY
```

- [ ] **Step 2: Write `docs/ARCHITECTURE.md`**

One page. It must contain, in this order:

1. **One paragraph** on what Kriko is and the one invariant that explains the
   layout: `kriko/` knows no category, so adding one is a data change.
2. **The fan diagram**, copied from `CLAUDE.md`'s layering principle so the two
   cannot disagree.
3. **A table: package → what it owns → the file to read first.** One row each for
   `app/`, `app/pipeline/`, `kriko/`, `packs/`, `packs/cars/pipeline/`,
   `extension/`.
4. **"Chasing X? read these"** — the section that earns the page. At least these
   entries, each naming 2–3 real files with line anchors where useful:
   - *How a listing becomes risk cards*: `extension/content.js` →
     `app/web/routers/analyze.py` → `kriko/adapters.py` → `kriko/lookup/`
   - *Why a claim did or did not show*: `kriko/lookup/rank.py`,
     `kriko/lookup/conditions.py`, `kriko/gates.py`
   - *What a pack contains*: `docs/PACK_CONTRACT.md`, `packs/drill/`,
     `kriko/pack/manifest.py`
   - *How a pack is built and installed*: `kriko/pack/build.py`,
     `kriko/store/packstore.py`
   - *Where evidence comes from*: `packs/cars/pipeline/ledger/`,
     `kriko/ledger/`, `app/pipeline/ledger_run.py`
   - *What Kriko refuses to store*: `kriko/gates.py`,
     `packs/cars/vocabulary/gates.yaml`, `app/mcp_server.py`
5. **Entry points** — every `python -m` target from Step 1, one line each.
6. **How to run things**: the venv note, the test command, the pack build command.

Write from the Step 1 output, not from memory. Every path must exist.

- [ ] **Step 3: Verify every path in the document resolves**

```bash
.venv/bin/python - <<'PY'
import pathlib, re
doc = pathlib.Path("docs/ARCHITECTURE.md").read_text()
paths = set(re.findall(r'`([a-zA-Z_][\w./-]*\.(?:py|js|md|yaml|toml|json))', doc))
paths |= set(re.findall(r'`((?:app|kriko|packs|docs|extension)/[\w./-]*/)`', doc))
missing = [p for p in sorted(paths) if not pathlib.Path(p).exists()]
print("MISSING:", missing or "none")
PY
```

Expected: `MISSING: none`. Fix any that do not resolve.

- [ ] **Step 4: Link it from `README.md` and `CLAUDE.md`**

Add a row to `CLAUDE.md`'s documentation-map table:

```markdown
| `docs/ARCHITECTURE.md` | Reading map — where to start, what each package owns | current |
| `docs/PACK_CONTRACT.md` | What a pack must contain, and what it may | current |
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -F - <<'EOF'
docs: a reading map for the tree

The architecture docs explained the design; none of them answered "I am
looking at this repo and want to find where X happens". docs/ARCHITECTURE.md
is that page: the fan, a package-to-first-file table, and a "chasing X?
read these three files" index covering the six questions the codebase
actually gets asked.

Written from a regenerated file inventory rather than from memory, and
every path in it is checked to resolve.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 14: Repo tidy and backlog reconciliation

**Files:**
- Delete: `deploy/` (empty)
- Modify: `docs/USAGE.md`, `docs/INTERNALS.md`, `backlog.md`, `done.md`

**Interfaces:**
- Consumes: the completed state of Tasks 1–13.
- Produces: nothing importable.

- [ ] **Step 1: Remove the empty directory**

```bash
find deploy -type f | head
rmdir deploy 2>/dev/null || echo "not empty — inspect before removing"
```

Git does not track empty directories, so this may be a working-tree-only cleanup.

- [ ] **Step 2: Find stale documentation references**

```bash
grep -rnE "knowledge/|apps/|extension_ui/|backend/|ops/" docs/*.md *.md \
  | grep -v docs/historical/ | grep -v docs/superpowers/
```

Every hit outside `docs/historical/` and `docs/superpowers/` is stale — those two
directories are deliberately historical. Fix each hit to the current path, or
delete the sentence if the thing it describes is gone.

- [ ] **Step 3: Verify every command in `docs/USAGE.md` still names a real module**

```bash
grep -oE "python -m [a-z_.]+" docs/USAGE.md | sort -u | while read -r _ _ m; do
  .venv/bin/python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$m') else 1)" \
    2>/dev/null && echo "OK   $m" || echo "GONE $m"
done
```

Fix or remove every `GONE` line.

- [ ] **Step 4: Move the finished items to `done.md`**

Add one entry per task in this plan to `done.md` with today's date and the commit
hash, following the file's existing format. Read the last few entries first and
match them.

- [ ] **Step 5: Update `backlog.md`**

- Mark B33's Phase 6b checkbox as landed with commit `f038df9`.
- Add a note under B33 that the Phase 6c follow-up (the extension manifest's
  hardcoded site list) remains open — this plan did not touch it.
- Add any deferred item this plan surfaced but did not fix.
- **File the long-function residue** as a new P2 backlog item, listing the eight
  functions Step 6's report prints with their current line counts, and noting
  that Tasks 10-11 handled the two the spec scoped. Frame it as a readability
  item, not a bug.

- [ ] **Step 6: Final verification**

```bash
.venv/bin/python -m pytest -q
echo "=== layering checks, all four must print nothing ==="
grep -rnE "^[[:space:]]*(from|import) (backend|app|packs|knowledge)" --include='*.py' kriko/ | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) (backend|app|packs)" --include='*.py' packs/cars/pipeline/ | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) (app|app.pipeline)" --include='*.py' packs/ | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) backend" --include='*.py' app/ | grep -v /pipeline/ | grep -v /tests/
echo "=== every module states what it owns ==="
.venv/bin/python - <<'DOC'
import ast, pathlib
bad = []
for p in pathlib.Path('.').rglob('*.py'):
    s = str(p)
    if 'node_modules' in s or s.startswith('.venv') or '__pycache__' in s:
        continue
    if p.name == '__init__.py' and not p.read_text().strip():
        continue          # a namespace marker owns nothing and needs no docstring
    try:
        tree = ast.parse(p.read_text())
    except Exception:
        continue
    if not ast.get_docstring(tree):
        bad.append(s)
print("\n".join(bad) if bad else "every module has a docstring")
DOC
echo "=== no long functions ==="
.venv/bin/python - <<'PY'
import ast, pathlib
bad = []
for p in pathlib.Path('.').rglob('*.py'):
    s = str(p)
    if 'node_modules' in s or '/tests/' in s or s.startswith('.venv'):
        continue
    try:
        t = ast.parse(p.read_text())
    except Exception:
        continue
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ln = (n.end_lineno or n.lineno) - n.lineno
            if ln > 80:
                bad.append(f"{s}:{n.lineno} {n.name}() {ln} lines")
print("\n".join(bad) if bad else "no function over 80 lines")
PY
```

Expected: suite PASS; all four layering greps silent; every module has a
docstring.

**The function-length check is a report, not a gate.** Tasks 10 and 11 fix the
two functions the spec scoped (457 and 300 lines). Eight others sit between 90
and 194 lines and are outside every task in this plan — `validate_part()` (194),
`process.run()` (153), `process.run_part()` (152), `ledger_run.main()` (144),
`export_all()` (142), `submit_findings()` (128, which Task 7 lengthens),
`lookup()` (119), `build_report()` (114). Print the list, do not fail on it, and
file the residue as a backlog item in Step 5 rather than splitting them here.
Splitting eight unrelated functions with no behaviour test behind them is a
different piece of work than this pass, and pretending otherwise turns a
readability target into an unfunded gate.

Note: the second grep will now match `packs/cars/pipeline/` importing
`packs.cars.pipeline.*` siblings — that is a self-import, not a layering
violation. If `test_repo_invariants.py` flags it, read how that test scopes the
check and match it rather than editing the test.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'EOF'
chore: reconcile docs and backlog with the simplification pass

Stale paths from before the pivot (knowledge/, apps/, extension_ui/,
backend/, ops/) removed from active docs; docs/historical/ and
docs/superpowers/ left alone, since those are deliberately a record of
what was true then. Every `python -m` command in USAGE.md verified to
name a module that still imports.

backlog.md and done.md updated for the fourteen tasks in this pass. The
Phase 6c follow-up — the extension manifest's hardcoded site list — is
noted as still open; it needs a host-permission UX decision, not a
mechanism.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

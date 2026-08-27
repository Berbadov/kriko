# Phase 6b — Split `knowledge/` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `knowledge/` (7,783 lines) into a generic evidence pipeline under `kriko/` and a car-specific one under `packs/cars/pipeline/`, so a second real pack can have a pipeline without duplicating the extraction machinery.

**Architecture:** The blocker was never the file moves — it was one module. `knowledge/stoplists.py` is imported by eight modules including the otherwise-generic ledger, and it derives from the car catalog, so everything that touches it is car-coupled by transitivity. Split `stoplists` first: its language and source-domain filters are genuinely generic and move to `kriko/text.py`; its *judgement* vocabulary (what a mechanic already catches, what counts as generic advice, what a dashboard-light claim looks like) is the cars product principle expressed in Python, and becomes pack-declared rows read through the store. Once that seam exists, `kriko/ledger/` and `kriko/extract/` fall out with no car vocabulary left in them, and the remainder moves down into `packs/cars/pipeline/`.

**Tech Stack:** Python 3.14, SQLite (WAL), pytest, PyYAML. No new dependencies.

**Spec:** `~/.claude/plans/let-s-go-with-the-eager-torvalds.md` (the G6 pivot design, Phase 6); the decision to split rather than move wholesale is HUMAN DECISION #8 in `backlog.md`, resolved 2026-08-27 in favour of the split.

## Global Constraints

- **`kriko/` may import none of `backend`, `ops`, `apps`, `packs`, `knowledge`.** Enforced by `ops/tests/test_repo_invariants.py`. This is the load-bearing invariant of G6.
- **`kriko/` may contain no car vocabulary in an executable position** — no `make`, `engine_code`, `fuel`, `variant`, `gearbox`, `dsg`, `tdi`. Enforced by `kriko/tests/test_core_is_domain_free.py`, which walks the AST. Prose in docstrings is fine; a string literal used as a value is not.
- **A pack is consumed through the store, never imported.** If a core module wants something from a pack, the pack supplies it as a row.
- **No hardcoded car data anywhere**, including in the pack's Python: values that grow with car coverage derive from `packs/cars/data/**/*.yaml`. Fixed engineering categories (fuel types, transmission technologies) may be constants.
- **No human in the data path.** Where a value cannot be derived, fail open: emit nothing, log the gap.
- Run the full suite at every task boundary: `.venv/bin/python -m pytest -q` must exit 0. Baseline at the start of this plan: **570 tests**.
- Commit at the end of every task. Branch: `feat/knowledge-engine-pivot`.

---

## File Structure

**New in `kriko/` (generic — no car vocabulary):**

| File | Responsibility |
|---|---|
| `kriko/text.py` | Language detection, verbose-title and blocked-domain filters, generic code-token shape. Pure functions over strings. |
| `kriko/gates.py` | Evaluates pack-declared gate vocabulary against a claim. Knows *how* to gate, never *what* is worth gating. |
| `kriko/ledger/` | `db, ingest, chunking, cluster, costs, extraction, verdict, parity, eval_verdict` — evidence rows, provenance, dedupe, verdict cache. |
| `kriko/extract/` | `client` (langextract), `grounding`, `dedup`, `title_sim`, `domains`, `consequence_tier`. |

**New in `packs/cars/` (car-specific):**

| File | Responsibility |
|---|---|
| `packs/cars/vocabulary/gates.yaml` | The cars product principle as data: inspection-covered terms, generic-maintenance terms, ambiguous terms, warning-light patterns, specificity signals. |
| `packs/cars/pipeline/catalog/` | `discover, write_variants, identity, doctor, generations, model_state, registry, emissions, repair_missing_stub_scaffold`. |
| `packs/cars/pipeline/parts/`, `fitment/` | Part and fitment YAML validation, search templates. |
| `packs/cars/pipeline/{acquire,export,resolve}.py` | The car-shaped ends of the ledger run. |
| `packs/cars/pipeline/vocabulary.py` | What survives of `stoplists`: sibling codes, foreign-manufacturer detection, catalog-derived code manufacturers. |

**Deleted:** the whole of `knowledge/`.

---

### Task 1: The gate vocabulary becomes pack data

`INSPECTION_COVERED`, `GENERIC_MAINTENANCE_TERMS`, `AMBIGUOUS_INSPECTION_TERMS`, `WARNING_LIGHT_PATTERNS` and `has_specificity_signal` are the cars product principle written as Python constants — "would a buyer learn this from a normal pre-purchase inspection anyway?". CLAUDE.md already says that bar is a property of the category and ships as pack data. This task makes that true, and is what unblocks every later task: five modules import these, and while they are constants in `knowledge/`, nothing importing them can move to `kriko/`.

**Files:**
- Create: `kriko/gates.py`
- Create: `packs/cars/vocabulary/gates.yaml`
- Create: `kriko/tests/test_gates.py`
- Modify: `kriko/pack/build.py` (emit gate rows), `kriko/store/schema.sql` (one table)
- Modify: `kriko/tests/test_pack_build.py`

**Interfaces:**
- Consumes: `kriko.store.db.connect`, the `terms` table pattern from `kriko/pack/build.py`.
- Produces:
  - `kriko.gates.GateVocabulary` — frozen dataclass with fields `covered: frozenset[str]`, `generic: frozenset[str]`, `ambiguous: frozenset[str]`, `noise_patterns: tuple[re.Pattern, ...]`, `specificity_patterns: tuple[re.Pattern, ...]`.
  - `kriko.gates.load_gates(conn, pack_id: str) -> GateVocabulary`
  - `kriko.gates.gate_reason(text: str, vocab: GateVocabulary) -> str | None` — returns the name of the rule that rejects `text`, or `None` to keep.

- [ ] **Step 1: Add the storage table**

In `kriko/store/schema.sql`, after the `terms` table:

```sql
-- ── gate vocabulary — what a pack considers not worth surfacing ──────────
-- This is taste, and taste is a property of the category, so it is pack data
-- and never an engine constant. The engine enforces RANKING; what clears the
-- bar at all is the pack author's call. `kind` names the rule the row feeds;
-- `pattern` is a literal phrase for `kind` in (covered, generic, ambiguous)
-- and a regular expression for (noise, specificity).
CREATE TABLE IF NOT EXISTS gate_terms (
  pack_id TEXT NOT NULL,
  kind    TEXT NOT NULL,   -- covered|generic|ambiguous|noise|specificity
  pattern TEXT NOT NULL,
  note    TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (pack_id, kind, pattern)
);
```

- [ ] **Step 2: Write the failing test**

Create `kriko/tests/test_gates.py`:

```python
"""What a pack considers not worth surfacing.

The engine enforces ranking; it does not have opinions about what is worth
saying. "A mechanic catches this anyway" is true of brake-pad wear on a car
and meaningless for a cordless drill, so the bar belongs to the pack — which
is also why nothing in this file names a car part.
"""

import pytest

from kriko.gates import gate_reason, load_gates
from kriko.store import packstore
from kriko.store.db import connect

VOCAB = [
    ("covered", "brake pad", ""),
    ("generic", "wear and tear is normal", ""),
    ("ambiguous", "oil consumption", ""),
    ("noise", r"\bwarning\s+light\b", ""),
    ("specificity", r"\b[A-Za-z]{1,4}\d[A-Za-z0-9]{0,3}\b", ""),
]


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "s.sqlite")
    with conn:
        packstore.write_pack_row(conn, pack_id="p", name="P", version="1",
                                 content_digest="x")
        for kind, pattern, note in VOCAB:
            conn.execute("INSERT INTO gate_terms VALUES (?,?,?,?)",
                         ("p", kind, pattern, note))
    yield conn
    conn.close()


def test_a_claim_the_pack_calls_routine_is_rejected_by_name(store):
    vocab = load_gates(store, "p")
    assert gate_reason("Brake pad wear at 60,000 km", vocab) == "covered"


def test_a_claim_that_is_true_of_everything_is_rejected(store):
    vocab = load_gates(store, "p")
    assert gate_reason("Wear and tear is normal", vocab) == "generic"


def test_an_ambiguous_term_survives_when_something_makes_it_specific(store):
    """"Oil consumption" is both the routine dipstick check and a documented
    defect in particular engine families. Rejecting it outright killed the
    second along with the first, so the rule is: reject only when nothing in
    the text pins it to a configuration."""
    vocab = load_gates(store, "p")
    assert gate_reason("Oil consumption in EA211 engines", vocab) is None


def test_an_ambiguous_term_with_nothing_specific_about_it_is_rejected(store):
    vocab = load_gates(store, "p")
    assert gate_reason("Oil consumption is worth watching", vocab) == "ambiguous"


def test_a_noise_pattern_is_rejected_however_it_is_phrased(store):
    vocab = load_gates(store, "p")
    assert gate_reason("ESP warning light on the dash", vocab) == "noise"


def test_a_claim_nothing_matches_is_kept(store):
    vocab = load_gates(store, "p")
    assert gate_reason("Mechatronic unit fails above 120,000 km", vocab) is None


def test_a_pack_with_no_gate_rows_rejects_nothing(tmp_path):
    """Fail open. A pack that declares no taste gets every claim through,
    ranked — never an empty result caused by a missing file."""
    conn = connect(tmp_path / "s.sqlite")
    with conn:
        packstore.write_pack_row(conn, pack_id="q", name="Q", version="1",
                                 content_digest="x")
    assert gate_reason("anything at all", load_gates(conn, "q")) is None
    conn.close()


def test_a_malformed_pattern_does_not_take_the_other_rules_down(tmp_path):
    """One bad regex in a third-party pack must not blind the whole gate."""
    conn = connect(tmp_path / "s.sqlite")
    with conn:
        packstore.write_pack_row(conn, pack_id="r", name="R", version="1",
                                 content_digest="x")
        conn.execute("INSERT INTO gate_terms VALUES (?,?,?,?)",
                     ("r", "noise", "[unclosed", ""))
        conn.execute("INSERT INTO gate_terms VALUES (?,?,?,?)",
                     ("r", "generic", "wear and tear is normal", ""))
    vocab = load_gates(conn, "r")
    assert gate_reason("Wear and tear is normal", vocab) == "generic"
    conn.close()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest kriko/tests/test_gates.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kriko.gates'`

- [ ] **Step 4: Implement `kriko/gates.py`**

```python
"""Applying a pack's idea of what is not worth saying.

The engine ranks; it does not have taste. "A mechanic catches this anyway" is
a sharp rule for a used car and meaningless for a cordless drill, so what
clears the bar is the pack author's call and arrives as rows. What lives here
is only the *shape* of the rules — a literal phrase list, a regex list, and
one conditional rule for terms that are ambiguous rather than worthless.

That conditional rule is the interesting one and it was learned the hard way.
Some phrases describe both a routine check and a documented, configuration-
specific defect; rejecting them outright threw away exactly the claims Kriko
exists to surface. So an `ambiguous` term is rejected only when nothing else
in the text pins the claim to a specific configuration — and what counts as
pinning it down is, again, the pack's `specificity` rows.
"""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GateVocabulary:
    covered: frozenset[str] = frozenset()
    generic: frozenset[str] = frozenset()
    ambiguous: frozenset[str] = frozenset()
    noise_patterns: tuple[re.Pattern, ...] = ()
    specificity_patterns: tuple[re.Pattern, ...] = ()


def _compile(patterns) -> tuple[re.Pattern, ...]:
    out = []
    for pattern in patterns:
        try:
            out.append(re.compile(pattern, re.I))
        except re.error:
            continue    # one bad regex must not blind every other rule
    return tuple(out)


def load_gates(conn, pack_id: str) -> GateVocabulary:
    rows: dict[str, list[str]] = {}
    for row in conn.execute(
            "SELECT kind, pattern FROM gate_terms WHERE pack_id = ?", (pack_id,)):
        rows.setdefault(row["kind"], []).append(row["pattern"])

    fold = lambda kind: frozenset(p.casefold() for p in rows.get(kind, ()))
    return GateVocabulary(
        covered=fold("covered"),
        generic=fold("generic"),
        ambiguous=fold("ambiguous"),
        noise_patterns=_compile(rows.get("noise", ())),
        specificity_patterns=_compile(rows.get("specificity", ())),
    )


def is_specific(text: str, vocab: GateVocabulary) -> bool:
    """Does anything in this text pin the claim to one configuration?"""
    return any(p.search(text) for p in vocab.specificity_patterns)


def gate_reason(text: str, vocab: GateVocabulary) -> str | None:
    """The name of the rule that rejects `text`, or None to keep it.

    Returning the rule's name rather than a bool is deliberate: a rejection
    nobody can explain is indistinguishable from a bug, and the coverage
    report needs to say *why* a claim never reached anyone.
    """
    lowered = (text or "").casefold()
    if any(term in lowered for term in vocab.covered):
        return "covered"
    if any(term in lowered for term in vocab.generic):
        return "generic"
    if any(p.search(text or "") for p in vocab.noise_patterns):
        return "noise"
    if any(term in lowered for term in vocab.ambiguous) and not is_specific(text or "", vocab):
        return "ambiguous"
    return None
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest kriko/tests/test_gates.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 6: Teach the builder to emit gate rows**

In `kriko/pack/build.py`, beside the `source_tiers` block:

```python
        for kind, pattern, note in _gate_rows(
                _load_yaml(root / "vocabulary" / "gates.yaml", {})):
            conn.execute("INSERT OR REPLACE INTO gate_terms VALUES (?,?,?,?)",
                         (pack_id, kind, pattern, note))
            row_ids.append(f"gate:{kind}:{pattern}")
```

And the helper, beside `_tier_rows`:

```python
_GATE_KINDS = ("covered", "generic", "ambiguous", "noise", "specificity")


def _gate_rows(spec) -> list[tuple[str, str, str]]:
    """A pack's `vocabulary/gates.yaml`, flattened into rows.

    Each key is a rule kind and holds either a list of phrases or a list of
    `{pattern, note}` mappings — the note is where a pack author records WHY a
    phrase is on the list, which is the difference between a rule someone can
    revise and a rule nobody dares touch.
    """
    if not spec:
        return []
    if not isinstance(spec, dict):
        raise ValueError(
            "vocabulary/gates.yaml must be a mapping of rule kind to term "
            f"list; got {type(spec).__name__}.")

    rows = []
    for kind in _GATE_KINDS:
        for entry in spec.get(kind) or []:
            if isinstance(entry, dict):
                rows.append((kind, str(entry["pattern"]), entry.get("note", "")))
            else:
                rows.append((kind, str(entry), ""))

    unknown = set(spec) - set(_GATE_KINDS)
    if unknown:
        raise ValueError(
            f"vocabulary/gates.yaml has unknown rule kinds {sorted(unknown)}; "
            f"known kinds are {list(_GATE_KINDS)}. Silently ignoring one would "
            "ship a pack whose author believes a gate is running when it is not.")
    return rows
```

- [ ] **Step 7: Write the builder test**

Append to `kriko/tests/test_pack_build.py`:

```python
GATES_YAML = """
covered:
  - {pattern: brake pad, note: the inspector measures pad thickness}
generic:
  - wear and tear is normal
noise:
  - {pattern: "\\\\bwarning\\\\s+light\\\\b", note: true of every car}
"""


def test_gate_vocabulary_ships_as_rows(tmp_path):
    from kriko.store.db import connect
    root = _write(tmp_path)
    (root / "vocabulary" / "gates.yaml").write_text(GATES_YAML, encoding="utf-8")
    out = build.build(root, tmp_path / "p.kpack")

    conn = connect(out)
    rows = {(r["kind"], r["pattern"]) for r in
            conn.execute("SELECT kind, pattern FROM gate_terms")}
    assert ("covered", "brake pad") in rows
    assert ("generic", "wear and tear is normal") in rows
    conn.close()


def test_a_note_on_a_gate_term_survives_into_the_row(tmp_path):
    """Why a phrase is on the list is the difference between a rule someone
    can revise and a rule nobody dares touch."""
    from kriko.store.db import connect
    root = _write(tmp_path)
    (root / "vocabulary" / "gates.yaml").write_text(GATES_YAML, encoding="utf-8")
    out = build.build(root, tmp_path / "p.kpack")
    conn = connect(out)
    note = conn.execute(
        "SELECT note FROM gate_terms WHERE pattern = 'brake pad'").fetchone()["note"]
    assert "pad thickness" in note
    conn.close()


def test_an_unknown_gate_kind_fails_the_build(tmp_path):
    """A typo'd key would otherwise ship a pack whose author believes a gate
    is running when it is not."""
    root = _write(tmp_path)
    (root / "vocabulary" / "gates.yaml").write_text(
        "coverd:\n  - brake pad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown rule kinds"):
        build.build(root, tmp_path / "p.kpack")
```

- [ ] **Step 8: Run the builder tests**

Run: `.venv/bin/python -m pytest kriko/tests/test_pack_build.py -q`
Expected: PASS.

- [ ] **Step 9: Write the cars gate vocabulary**

Create `packs/cars/vocabulary/gates.yaml` by transcribing `knowledge/stoplists.py`'s `INSPECTION_COVERED` (→ `covered`), `GENERIC_MAINTENANCE_TERMS` (→ `generic`), `AMBIGUOUS_INSPECTION_TERMS` (→ `ambiguous`), `WARNING_LIGHT_PATTERNS` (→ `noise`), and the three regexes behind `has_specificity_signal` — `CODE_TOKEN_RE`, `_DISPLACEMENT_RE`, `_MILEAGE_RE` — (→ `specificity`). Carry each block's existing comment across as the `note` on its first entry; those comments record real incidents and must not be lost in the move. Begin the file with:

```yaml
# The cars product principle, as data.
#
# CLAUDE.md's bar — "would a buyer learn this from a normal pre-purchase
# inspection anyway?" — used to live as frozensets in knowledge/stoplists.py,
# which made the engine hold an opinion about brake pads. It is taste, taste is
# a property of the category, and this is where the category's taste lives.
#
# See packs/cars/research/principle.md for the prose version.
```

- [ ] **Step 10: Prove the transcription is complete**

Create `packs/cars/tests/test_gate_vocabulary.py`:

```python
"""The gate vocabulary moved from Python to YAML. This checks nothing was
dropped on the way, and that it still rejects what it used to reject."""

from pathlib import Path

import yaml

from kriko.gates import gate_reason, load_gates
from kriko.store import packstore
from kriko.store.db import connect


def _installed(tmp_path):
    from packs.cars import build
    out, _ = build.build(tmp_path / "cars.kpack")
    conn = connect(tmp_path / "store.sqlite")
    packstore.install(conn, out)
    return conn


def test_the_routine_checks_a_mechanic_already_does_are_still_rejected(tmp_path):
    conn = _installed(tmp_path)
    vocab = load_gates(conn, "org.kriko.cars")
    assert gate_reason("Brake pad wear at 60,000 km", vocab) == "covered"
    assert gate_reason("Injector bench test recommended", vocab) == "covered"
    conn.close()


def test_a_dashboard_light_claim_is_still_rejected_however_phrased(tmp_path):
    conn = _installed(tmp_path)
    vocab = load_gates(conn, "org.kriko.cars")
    for text in ("ABS warning light", "ESP fault indicator",
                 "check engine light comes on"):
        assert gate_reason(text, vocab) == "noise", text
    conn.close()


def test_a_config_specific_oil_consumption_claim_still_survives(tmp_path):
    """The incident this rule exists for: an unconditional reject killed the
    EA211 piston-ring claims along with the generic dipstick advice."""
    conn = _installed(tmp_path)
    vocab = load_gates(conn, "org.kriko.cars")
    assert gate_reason(
        "Oil consumption in the EA211 1.4 TSI above 100,000 km", vocab) is None
    conn.close()


def test_every_phrase_the_python_version_had_is_present(tmp_path):
    """A transcription is only as good as its proof. This reads the YAML and
    asserts the counts the frozensets had, so a dropped line is a failure
    rather than a silently weaker gate."""
    spec = yaml.safe_load(
        Path("packs/cars/vocabulary/gates.yaml").read_text(encoding="utf-8"))
    # Counts taken from knowledge/stoplists.py at the commit before the move.
    # Update them deliberately when the vocabulary changes; never to make a
    # failing test pass.
    assert len(spec["covered"]) == 44
    assert len(spec["generic"]) == 11
    assert len(spec["ambiguous"]) == 3
    assert len(spec["noise"]) == 4
    assert len(spec["specificity"]) == 3
```

These counts were taken from `knowledge/stoplists.py` at commit `ded8113`
(covered 44, generic 11, ambiguous 3, noise 4, specificity 3). Re-check them
before writing the test if the module has changed since:

```bash
.venv/bin/python -c "
from knowledge import stoplists as s
print('covered', len(s.INSPECTION_COVERED))
print('generic', len(s.GENERIC_MAINTENANCE_TERMS))
print('ambiguous', len(s.AMBIGUOUS_INSPECTION_TERMS))
print('noise', len(s.WARNING_LIGHT_PATTERNS))"
```

- [ ] **Step 11: Run the suite**

Run: `.venv/bin/python -m pytest -q`
Expected: exit 0.

- [ ] **Step 12: Commit**

```bash
git add kriko/gates.py kriko/tests/test_gates.py kriko/store/schema.sql \
        kriko/pack/build.py kriko/tests/test_pack_build.py \
        packs/cars/vocabulary/gates.yaml packs/cars/tests/test_gate_vocabulary.py
git commit -m "feat(pivot): Phase 6b/1 — the gate vocabulary becomes pack data

INSPECTION_COVERED and its neighbours were the cars product principle written
as frozensets in the engine's dependency graph: the engine held an opinion
about brake pads, and five modules imported it, so nothing that touched them
could move up. They are now rows, and kriko/gates.py knows only the shape of
the rules.

The ambiguous-term rule survives intact, comment and all — an unconditional
reject once killed the EA211 piston-ring claims along with the generic dipstick
advice, and packs/cars/tests/test_gate_vocabulary.py now pins that."
```

---

### Task 2: The generic text and source filters move to `kriko/text.py`

What is left of `stoplists` after Task 1 divides cleanly. `is_german_text`, `is_likely_non_english`, `title_is_verbose`, `is_blocked_source_domain`, `FORUM_DOMAINS` and `UNRELIABLE_DOMAINS` are about *language and publishing*, not about cars; a drill pack wants all six unchanged. Everything else — sibling codes, foreign-manufacturer detection, catalog-derived manufacturers — is car-shaped and stays behind for Task 5.

**Files:**
- Create: `kriko/text.py`, `kriko/tests/test_text.py`
- Modify: `knowledge/stoplists.py` (re-export from the new home during the move)

**Interfaces:**
- Produces: `kriko.text.is_probably_not_english(text, threshold=0.02) -> bool`, `kriko.text.title_is_verbose(title, max_len=100) -> bool`, `kriko.text.is_blocked_source_domain(url_or_host, blocked: frozenset[str]) -> bool`, `kriko.text.code_tokens(text) -> set[str]`.

**Note on the signature change:** `is_blocked_source_domain` currently closes over a module-level `UNRELIABLE_DOMAINS` constant. In `kriko/` it must take the blocklist as an argument — the set of domains a reader distrusts is pack data and reader configuration, not an engine constant. The `FORUM_DOMAINS` / `UNRELIABLE_DOMAINS` sets themselves move to `packs/cars/pipeline/vocabulary.py` in Task 5 and are passed in.

- [ ] **Step 1: Write the failing test**

Create `kriko/tests/test_text.py`:

```python
"""Language and publishing filters. Nothing here knows what a product is."""

from kriko.text import (code_tokens, is_blocked_source_domain,
                        is_probably_not_english, title_is_verbose)


def test_english_prose_is_not_flagged():
    assert not is_probably_not_english(
        "The tensioner rattles on cold start above 120,000 km.")


def test_text_with_non_english_letters_is_flagged():
    assert is_probably_not_english("Motorun zamanlama zinciri gevşiyor.")


def test_a_blocked_host_is_recognised_by_its_url():
    blocked = frozenset({"spam.example"})
    assert is_blocked_source_domain("https://spam.example/a/b", blocked)


def test_a_subdomain_of_a_blocked_host_is_blocked_too():
    blocked = frozenset({"spam.example"})
    assert is_blocked_source_domain("https://www.spam.example/a", blocked)


def test_a_host_that_merely_ends_in_the_same_letters_is_not_blocked():
    """"notspam.example" is a different site from "spam.example"."""
    blocked = frozenset({"spam.example"})
    assert not is_blocked_source_domain("https://notspam.example/a", blocked)


def test_an_empty_blocklist_blocks_nothing():
    assert not is_blocked_source_domain("https://anything.example", frozenset())


def test_a_long_title_is_verbose():
    assert title_is_verbose("x" * 120)


def test_a_normal_title_is_not():
    assert not title_is_verbose("Timing chain tensioner wear")


def test_code_tokens_finds_short_alphanumeric_identifiers():
    assert code_tokens("The EA211 and DQ200 units") >= {"ea211", "dq200"}


def test_code_tokens_ignores_ordinary_words():
    assert code_tokens("the tensioner rattles") == set()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest kriko/tests/test_text.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kriko.text'`

- [ ] **Step 3: Create `kriko/text.py`**

Move the bodies of `is_german_text`, `is_likely_non_english`, `title_is_verbose`, `is_blocked_source_domain` and `code_tokens` out of `knowledge/stoplists.py`, unchanged except: merge `is_german_text` and `is_likely_non_english` into `is_probably_not_english` (they are the same test with different marker sets), and give `is_blocked_source_domain` a `blocked` parameter instead of the module constant. Carry every existing comment across — `_NON_ENGLISH_CHAR_MARKERS` in particular records which alphabets were seen in real sources.

- [ ] **Step 4: Run the test**

Run: `.venv/bin/python -m pytest kriko/tests/test_text.py -q`
Expected: PASS, 10 tests.

- [ ] **Step 5: Re-point `knowledge/stoplists.py` at the new home**

Replace the moved bodies with imports from `kriko.text`, keeping the old names bound so nothing else breaks yet:

```python
# These moved to kriko/text.py — they are about language and publishing, not
# about cars, and a drill pack wants all of them unchanged. Re-exported here
# only until Tasks 3-5 re-point the callers; this block is deleted in Task 6.
from kriko.text import (code_tokens, is_probably_not_english,  # noqa: F401
                        title_is_verbose)
```

`is_blocked_source_domain` keeps a thin wrapper here that supplies `UNRELIABLE_DOMAINS`, since its callers do not pass one yet.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add kriko/text.py kriko/tests/test_text.py knowledge/stoplists.py
git commit -m "feat(pivot): Phase 6b/2 — language and source filters move to kriko/text.py

is_blocked_source_domain gains a blocklist parameter: which domains a reader
distrusts is pack data and reader configuration, and closing over a module
constant was how it became neither."
```

---

### Task 3: `kriko/ledger/` — the generic ledger moves up

With Tasks 1 and 2 done, `db, ingest, chunking, cluster, costs, extraction, verdict, parity, eval_verdict` have no car vocabulary left. `resolve.py` does not move — it calls `catalog_code_manufacturers()` and belongs to the pack (Task 5).

**Files:**
- Create: `kriko/ledger/{__init__,db,ingest,chunking,cluster,costs,extraction,verdict,parity,eval_verdict}.py`
- Move: `knowledge/tests/test_ledger_{db,ingest,chunking,cluster,costs,extraction,verdict,parity}.py` → `kriko/tests/`
- Modify: `ops/{ledger_run,panel,remediate}.py` imports

**Interfaces:**
- Consumes: `kriko.gates.load_gates`, `kriko.gates.gate_reason`, `kriko.text.*`.
- Produces: the existing public functions of each module, unchanged names, under `kriko.ledger.*`.

- [ ] **Step 1: Move the modules with git so history follows**

```bash
mkdir -p kriko/ledger
for m in __init__ db ingest chunking cluster costs extraction verdict parity eval_verdict; do
  git mv knowledge/ledger/$m.py kriko/ledger/$m.py
done
```

- [ ] **Step 2: Rewrite the imports inside them**

```bash
sed -i 's/from knowledge\.ledger/from kriko.ledger/g; s/from knowledge\.stoplists import/from kriko.text import/g' kriko/ledger/*.py
```

Then fix by hand the two that need the new seam:
- `kriko/ledger/extraction.py`: replace `GENERIC_MAINTENANCE_TERMS, WARNING_LIGHT_PATTERNS, has_specificity_signal` with a `GateVocabulary` parameter threaded from its caller, and call `gate_reason`.
- `kriko/ledger/verdict.py`: `sibling_codes_for` and `title_has_dtc_code` are car-shaped. Take them as injected callables — `verdict(..., siblings_of=..., is_noise=...)` — defaulting to `lambda *_: frozenset()` and `lambda _: False`, so the engine fails open and the pack supplies the real ones in Task 5.

- [ ] **Step 3: Move the tests and re-point them**

```bash
for t in db ingest chunking cluster costs extraction verdict parity; do
  git mv knowledge/tests/test_ledger_$t.py kriko/tests/test_ledger_$t.py
done
sed -i 's/from knowledge\.ledger/from kriko.ledger/g; s/knowledge\.ledger/kriko.ledger/g' kriko/tests/test_ledger_*.py
```

- [ ] **Step 4: Add the tests that make the injection real**

`gate_product_value(evidence_titles, v)` currently calls the module-level `title_has_dtc_code`. It gains a third parameter, `is_noise`, defaulting to a function that never matches. Append to `kriko/tests/test_ledger_verdict.py`:

```python
from kriko.ledger.verdict import gate_product_value


def test_a_high_value_verdict_is_downgraded_when_the_pack_calls_it_noise():
    """The reason this rule exists: handed a raw fault-code litany, the verdict
    model launders the codes out of its rewritten title and still returns
    product_value="high". The downgrade is deterministic and one-directional —
    it never raises the model's judgement, only lowers it."""
    got = gate_product_value(
        ["P0401 P0402 P2002 fault codes explained"],
        {"product_value": "high"},
        is_noise=lambda title: "P04" in title)
    assert got == "low"


def test_the_downgrade_never_raises_a_verdict():
    got = gate_product_value(
        ["P0401 fault codes explained"],
        {"product_value": "low"},
        is_noise=lambda title: True)
    assert got == "low"


def test_the_engine_downgrades_nothing_when_no_pack_supplies_a_noise_rule():
    """Fail open. An engine that suppresses a claim because nobody told it how
    to suppress claims is worse than one that says too much — the coverage
    report can see the second, and a reader can see it too."""
    got = gate_product_value(
        ["P0401 P0402 fault codes explained"], {"product_value": "high"})
    assert got == "high"


def test_a_verdict_with_no_product_value_survives_the_gate():
    assert gate_product_value(["anything"], {}) is None
```

The corresponding implementation change in `kriko/ledger/verdict.py`:

```python
def _never(title: str) -> bool:
    return False


def gate_product_value(evidence_titles, v: dict, is_noise=_never) -> str | None:
    """Deterministic downgrade of the model's self-reported product_value.

    The verdict model is unreliable on product value (the gold eval catches
    it): handed a raw fault-code litany it launders the codes out of its
    rewritten title and still returns product_value="high".

    What counts as a litany is the pack's call — a fault-code format is
    category vocabulary — so it arrives as `is_noise` rather than as an import.
    The default never matches, which means a caller that forgets to wire the
    pack in gets MORE claims through, not fewer: visible in the coverage
    report rather than silently missing from someone's answer.
    """
    pv = v.get("product_value")
    if pv == "high" and any(is_noise(t or "") for t in evidence_titles):
        return "low"
    return pv
```

`cluster_payload` and `pending_clusters` both call `sibling_codes_for(cl["component_id"])` at lines 67 and 257. Both gain a `siblings_of` parameter with the same fail-open default, `lambda _: frozenset()`.

- [ ] **Step 5: Re-point `ops/`**

```bash
sed -i 's/from knowledge\.ledger/from kriko.ledger/g; s/knowledge\.ledger/kriko.ledger/g' ops/*.py
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: exit 0. Then check the invariant explicitly:

```bash
grep -rnE "^[[:space:]]*(from|import) (backend|ops|apps|packs|knowledge)" --include='*.py' kriko/ | grep -v /tests/
```
Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat(pivot): Phase 6b/3 — the generic ledger moves into kriko/

extraction and verdict take their gate vocabulary as an argument rather than
importing it. The defaults keep claims: an engine that suppresses a claim
because nobody told it how to suppress claims is worse than one that says too
much, and the coverage report can see the second."
```

---

### Task 4: `kriko/extract/` — grounded extraction moves up

**Files:**
- Create: `kriko/extract/{__init__,client,grounding,dedup,title_sim,domains,consequence_tier}.py`
- Move: `knowledge/tests/test_{langextract_client,extract_claims,consequence_tier}.py` → `kriko/tests/`

**Interfaces:**
- Produces: `kriko.extract.grounding.extract(...)`, `kriko.extract.client.*` (the langextract wrapper), `kriko.extract.dedup.*`, `kriko.extract.domains.*`.

- [ ] **Step 1: Move with git**

```bash
mkdir -p kriko/extract && touch kriko/extract/__init__.py
git mv knowledge/langextract_client.py kriko/extract/client.py
git mv knowledge/extract.py           kriko/extract/grounding.py
git mv knowledge/dedup.py             kriko/extract/dedup.py
git mv knowledge/title_sim.py         kriko/extract/title_sim.py
git mv knowledge/domains.py           kriko/extract/domains.py
git mv knowledge/consequence_tier.py  kriko/extract/consequence_tier.py
```

- [ ] **Step 2: Check `domains.py` for car vocabulary before it moves**

```bash
grep -nEi "\b(engine|transmission|gearbox|emissions|fuel|suspension|brakes)\b" kriko/extract/domains.py
```

If `domains.py` enumerates *car* subsystems (engine, transmission, emissions…), it does **not** move — subsystem taxonomy is category vocabulary and already exists as `terms` rows with `role='domain'`. In that case: delete it, and re-point its callers at the pack's domain terms through the store. Decide this from the grep output, not from the filename.

- [ ] **Step 3: Rewrite imports**

```bash
sed -i 's/from knowledge\.langextract_client/from kriko.extract.client/g;
        s/from knowledge\.extract/from kriko.extract.grounding/g;
        s/from knowledge\.dedup/from kriko.extract.dedup/g;
        s/from knowledge\.title_sim/from kriko.extract.title_sim/g;
        s/from knowledge\.consequence_tier/from kriko.extract.consequence_tier/g' \
    kriko/extract/*.py kriko/ledger/*.py ops/*.py knowledge/**/*.py
```

- [ ] **Step 4: Move and re-point the tests**

```bash
for t in langextract_client extract_claims consequence_tier; do
  git mv knowledge/tests/test_$t.py kriko/tests/test_$t.py
done
```
Then rewrite their imports the same way.

- [ ] **Step 5: Run the full suite and the two invariants**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest kriko/tests/test_core_is_domain_free.py -q
grep -rnE "^[[:space:]]*(from|import) (backend|ops|apps|packs|knowledge)" --include='*.py' kriko/ | grep -v /tests/
```
Expected: exit 0, exit 0, no output.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(pivot): Phase 6b/4 — grounded extraction moves into kriko/extract/"
```

---

### Task 5: `packs/cars/pipeline/` — the rest moves down

Everything left in `knowledge/` is the cars pipeline. It moves under the pack, where its car-shapedness stops being a problem.

**Files:**
- Move: `knowledge/catalog/` → `packs/cars/pipeline/catalog/`; `knowledge/parts/`, `knowledge/fitment/` → `packs/cars/pipeline/`; `knowledge/ledger/{acquire,export,resolve}.py` → `packs/cars/pipeline/`; `knowledge/{scaffold,maintenance,ground_mileage_threshold,ground_year_window}.py` → `packs/cars/pipeline/`; `knowledge/sources/` → `packs/cars/pipeline/sources/`; `knowledge/agent/` → `packs/cars/pipeline/agent/`
- Create: `packs/cars/pipeline/vocabulary.py` (what survives of `stoplists`)
- Move: the remaining 26 files of `knowledge/tests/` → `packs/cars/tests/`

- [ ] **Step 1: Move everything with git**

```bash
mkdir -p packs/cars/pipeline
git mv knowledge/catalog  packs/cars/pipeline/catalog
git mv knowledge/parts    packs/cars/pipeline/parts
git mv knowledge/fitment  packs/cars/pipeline/fitment
git mv knowledge/sources  packs/cars/pipeline/sources
git mv knowledge/agent    packs/cars/pipeline/agent
for m in acquire export resolve; do
  git mv knowledge/ledger/$m.py packs/cars/pipeline/$m.py
done
for m in scaffold maintenance ground_mileage_threshold ground_year_window; do
  git mv knowledge/$m.py packs/cars/pipeline/$m.py
done
git mv knowledge/stoplists.py packs/cars/pipeline/vocabulary.py
git mv knowledge/yamlutil.py  packs/cars/pipeline/yamlutil.py
```

- [ ] **Step 2: Strip the re-export block from `vocabulary.py`**

Delete the `from kriko.text import ...` compatibility block added in Task 2 Step 5, and import the four functions directly where they are used. `UNRELIABLE_DOMAINS` and `FORUM_DOMAINS` stay here and are now passed into `kriko.text.is_blocked_source_domain` explicitly at each call site.

- [ ] **Step 3: Rewrite every remaining `knowledge.` import**

```bash
grep -rln "knowledge\." --include='*.py' . | grep -v '\.venv' | \
  xargs sed -i 's/knowledge\.catalog/packs.cars.pipeline.catalog/g;
                s/knowledge\.parts/packs.cars.pipeline.parts/g;
                s/knowledge\.fitment/packs.cars.pipeline.fitment/g;
                s/knowledge\.sources/packs.cars.pipeline.sources/g;
                s/knowledge\.agent/packs.cars.pipeline.agent/g;
                s/knowledge\.stoplists/packs.cars.pipeline.vocabulary/g;
                s/knowledge\.scaffold/packs.cars.pipeline.scaffold/g;
                s/knowledge\.maintenance/packs.cars.pipeline.maintenance/g;
                s/knowledge\.ground_/packs.cars.pipeline.ground_/g;
                s/knowledge\.yamlutil/packs.cars.pipeline.yamlutil/g;
                s/knowledge\.ledger\.acquire/packs.cars.pipeline.acquire/g;
                s/knowledge\.ledger\.export/packs.cars.pipeline.export/g;
                s/knowledge\.ledger\.resolve/packs.cars.pipeline.resolve/g'
```

Run it, then `grep -rn "knowledge\." --include='*.py' . | grep -v '\.venv'` and fix what is left by hand.

- [ ] **Step 4: Supply the pack's rules to the engine's injection points**

`kriko/ledger/verdict.py` and `kriko/ledger/extraction.py` now take callables. Wire them at the driver level in `ops/ledger_run.py`:

```python
from kriko.gates import load_gates
from packs.cars.pipeline.vocabulary import sibling_codes_for, title_has_dtc_code

vocab = load_gates(store, "org.kriko.cars")
verdict.run(..., siblings_of=sibling_codes_for, is_noise=title_has_dtc_code)
```

`ops/` may import both `kriko/` and `packs/`, so this is the correct place for the wiring — it is exactly what `ops/` is for.

- [ ] **Step 5: Move the remaining tests**

```bash
git mv knowledge/tests/test_*.py packs/cars/tests/
```
Then re-point their imports with the same sed as Step 3, and delete `knowledge/tests/__init__.py`.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: exit 0, 570+ tests.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat(pivot): Phase 6b/5 — the cars pipeline moves under the cars pack

knowledge/ was never a generic layer; it was this. Under packs/cars/pipeline/
its car-shapedness stops being a problem, and ops/ does the wiring — which is
what ops/ is for."
```

---

### Task 6: Delete `knowledge/`, and ratchet it shut

**Files:**
- Delete: `knowledge/`
- Modify: `ops/tests/test_repo_invariants.py`, `CLAUDE.md`, `docs/INTERNALS.md`

- [ ] **Step 1: Confirm nothing is left**

```bash
find knowledge -type f -not -name '*.pyc' | grep -v __pycache__
```
Expected: no output. Anything listed has not been decided about — decide, do not delete.

- [ ] **Step 2: Delete it**

```bash
git rm -r knowledge/
```

- [ ] **Step 3: Write the ratchet test**

In `ops/tests/test_repo_invariants.py`, beside the existing `backend/` ratchet:

```python
def test_knowledge_stays_deleted():
    """`knowledge/` was the cars pipeline wearing a generic name, and the name
    is what made it collect car code for a year. Recreating it — even as a
    convenience package — restores the ambiguity that Phase 6b spent five
    commits removing. Generic pipeline code belongs in kriko/; car pipeline
    code belongs in packs/cars/pipeline/.
    """
    assert not Path("knowledge").exists(), (
        "knowledge/ is deleted. Generic pipeline code goes in kriko/ "
        "(ledger, extract); car-specific pipeline code goes in "
        "packs/cars/pipeline/.")
```

- [ ] **Step 4: Update the layering contract**

In `CLAUDE.md`'s layering principle, replace the four-package fan with three, and replace the four greps with:

```bash
grep -rnE "^[[:space:]]*(from|import) (backend|ops|apps|packs|knowledge)" --include='*.py' kriko/ | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) (ops|apps)"                        --include='*.py' packs/ | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) (backend|ops|knowledge)"           --include='*.py' apps/  | grep -v /tests/
```

Add the sentence that Phase 6b earned: *"`knowledge/` is deleted. It was the cars pipeline under a generic name, and the name is what let car code accumulate in it unnoticed for a year — a package named after a layer will collect whatever its authors believe belongs to that layer."*

- [ ] **Step 5: Run everything**

```bash
.venv/bin/python -m pytest -q && npm test
```
Expected: pytest exit 0; 36 JS tests pass.

- [ ] **Step 6: Update the backlog**

Mark Phase 6b done in `backlog.md` with the date and commit, record that HUMAN DECISION #8 was resolved in favour of the split, and note what the split bought: a second real pack can now ship a pipeline by supplying gate rows and search templates, without a line of extraction machinery.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat(pivot): Phase 6b/6 — knowledge/ is deleted, and ratcheted shut

Four packages become three. The engine has a ledger and an extractor and knows
no category; the cars pack has a pipeline and knows nothing else. A second real
pack now needs gate rows and search templates, not a copy of the machinery —
which was the whole argument for splitting rather than moving."
```

---

## Verification

After Task 6, all of these must hold:

```bash
.venv/bin/python -m pytest -q                  # exit 0
npm test                                       # 36 pass
.venv/bin/python -m packs.cars.build --out /tmp/cars.kpack
.venv/bin/python -m apps.cli --store /tmp/s.db install /tmp/cars.kpack
.venv/bin/python -m ops.ledger_run --help      # the pipeline drivers still run
grep -rn "knowledge" --include='*.py' . | grep -v '\.venv' | grep -v 'knowledge engine'
```

The last grep should return only prose matches ("knowledge engine", "knowledge pack"), never an import.

## Risks

1. **`ops/ledger_run.py` and `ops/remediate.py` are the real integration test and they have thin coverage.** Their imports change in Tasks 3 and 5. Mitigation: run each driver's `--help` and, if the ledger DB is present, one `--dry-run` pass at the end of Tasks 3, 5 and 6 — not only at the end.
2. **The gate transcription in Task 1 is where meaning gets lost.** Frozensets carry comments that record real incidents; YAML `note:` fields must carry them across. `test_every_phrase_the_python_version_had_is_present` catches a dropped line but not a dropped *reason*. Read the diff for Task 1 with that specifically in mind.
3. **`verdict.py`'s injected defaults change behaviour if a caller forgets to wire them.** Failing open means a forgotten wire shows up as *more* claims, not fewer — visible in the coverage report rather than silent. That is the right direction, but it does mean Task 5 Step 4 is not optional and a missed call site will not fail a test. Grep for every `verdict.run(` and `extraction.run(` call after Task 5.

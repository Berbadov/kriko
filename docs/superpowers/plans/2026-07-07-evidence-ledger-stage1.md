> TL;DR (archived 2026-09-25): Stage-1 build of the append-only evidence ledger (spec `2026-07-07-evidence-ledger-pipeline-design.md`): SQLite `knowledge/ledger.db`, backfill, chunked keyword-gated ministral-8b extraction, deterministic resolution/clustering, one Haiku-batch verdict per cluster, YAML export with human-approved parity gate (Task 11).
> Serving plane untouched; every LLM call cached by content hash with `--max-usd` Budget abort. 12 tasks + gated retirement (Task 12). Price table: ministral 0.10/0.10, haiku 1.00/5.00, haiku-batch 0.50/2.50 (USD/MTok). Full file dumps trimmed below — see git history.

# Evidence-Ledger Pipeline (Stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the append-only evidence ledger (spec: `docs/superpowers/specs/2026-07-07-evidence-ledger-pipeline-design.md`, §6 stage 1): SQLite ledger, backfill, chunked keyword-gated extraction, deterministic resolution/clustering, one Haiku-batch verdict per cluster, YAML export with parity check, and hard token-cost controls.

**Architecture:** New package `knowledge/ledger/` writes documents and evidence append-only to `knowledge/ledger.db`; resolution, clustering, verdicts, and export are derived, recomputable, and cached by content hash. Export produces claim YAML in the existing schema into `knowledge/ledger_export/` — the serving plane and `backend/data/**` are untouched until the parity gate (Task 11) is approved by a human.

**Tech Stack:** Python 3.13, stdlib `sqlite3` (no ORM), existing `knowledge.langextract_client` (ministral-8b) for extraction, `anthropic` SDK (`claude-haiku-4-5`, Message Batches API) for verdicts, PyYAML, pytest.

## Global Constraints

- **Serving plane untouched.** Nothing under `backend/` is created or modified by this plan. Export goes to `knowledge/ledger_export/` only.
- **`documents` and `evidence` tables are append-only** — enforced by SQL triggers, not convention.
- **Every LLM call is (a) preceded by a deterministic filter, (b) cached by content hash so re-runs are free, (c) charged to a `Budget` that aborts on `--max-usd`.**
- Extraction model stays `ministral-8b-latest` via `knowledge.langextract_client.extract_grounded` (do not change it). Verdict model is `claude-haiku-4-5`; price table (USD/MTok): ministral 0.10/0.10, haiku 1.00/5.00, haiku batch 0.50/2.50.
- All tests run offline — every test that touches an LLM client mocks it (`monkeypatch`). Only Task 11's manual acceptance commands spend real tokens.
- New runtime dependency: `anthropic` (added to `knowledge/requirements.txt` in Task 8). Env var `ANTHROPIC_API_KEY`.
- `knowledge/ledger.db` and `knowledge/ledger_export/` are gitignored.
- Tests live in `knowledge/tests/` (exists), named `test_ledger_*.py`. Run from repo root: `python -m pytest knowledge/tests/<file> -v`.
- No hand-authored car-data constants: component identity, aliases, and manufacturers are derived from `backend/data/**` via `knowledge/stoplists.py` helpers (`code_tokens`, `catalog_code_manufacturers`, `sibling_codes_for`).
- Commit after every task with the trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Ledger schema and `db.py`

**Files:**
- Create: `knowledge/ledger/__init__.py` (empty)
- Create: `knowledge/ledger/db.py`
- Modify: `.gitignore` (append two lines)
- Test: `knowledge/tests/test_ledger_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `LEDGER_PATH: Path`, `connect(path=LEDGER_PATH) -> sqlite3.Connection`, `text_hash(text: str) -> str`, `insert_document(conn, *, url, source_type, raw_text, site_or_channel="", lang="", target_hint="") -> int` (dedups by text hash, returns existing id), `insert_evidence(conn, *, doc_id, claim: dict, span_start, span_end, extractor_version) -> int`, `flag_low_value(conn, evidence_id, reason) -> None`. All later tasks connect through `connect()` with a tmp path in tests.

- [ ] **Step 1: Write the failing tests**

```python
# knowledge/tests/test_ledger_db.py
import sqlite3
import pytest
from knowledge.ledger import db

@pytest.fixture
def conn(tmp_path):
```
*[... 47 lines trimmed - see git history]*
```python
def test_connect_is_idempotent(tmp_path):
    p = tmp_path / "l.db"
    db.connect(p).close()
    db.connect(p).close()  # schema re-run must not fail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest knowledge/tests/test_ledger_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'knowledge.ledger'`

- [ ] **Step 3: Implement**

Create empty `knowledge/ledger/__init__.py`, then:

```python
# knowledge/ledger/db.py
"""Append-only evidence ledger — SQLite, no ORM.

`documents` and `evidence` are append-only (SQL triggers). Everything else
(resolutions, clusters, verdicts, flags, runs) is derived and freely
recomputable. This file is a build cache with provenance, NOT a serving
database — the serving plane never reads it.
"""
```
*[... 150 lines trimmed - see git history]*
```python
        "INSERT OR REPLACE INTO evidence_flags (evidence_id, reason) VALUES (?,?)",
        (evidence_id, reason),
    )
    conn.commit()
```

Append to `.gitignore`:

```
knowledge/ledger.db
knowledge/ledger_export/
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest knowledge/tests/test_ledger_db.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/ledger/__init__.py knowledge/ledger/db.py knowledge/tests/test_ledger_db.py .gitignore
git commit -m "feat(ledger): append-only SQLite evidence ledger schema"
```

---

### Task 2: Cost accounting and budget enforcement (`costs.py`)

**Files:**
- Create: `knowledge/ledger/costs.py`
- Test: `knowledge/tests/test_ledger_costs.py`

**Interfaces:**
- Consumes: `db.connect` (for `log_stage`).
- Produces: `PRICES_USD_PER_MTOK: dict[str, tuple[float, float]]`, `BudgetExceeded(RuntimeError)`, `Budget(max_usd: float | None)` with `.charge(model, tokens_in, tokens_out) -> float`, `.precheck(est_usd: float) -> None` (raises before spending), `.total_usd: float`, `.report() -> str`; `estimate_cost(model, tokens_in, tokens_out) -> float`; `log_stage(conn, stage, model, calls, tokens_in, tokens_out, usd) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# knowledge/tests/test_ledger_costs.py
import pytest
from knowledge.ledger import costs, db

def test_charge_accumulates_and_reports():
    b = costs.Budget(max_usd=None)
    usd = b.charge("ministral-8b-latest", 1_000_000, 0)
    assert usd == pytest.approx(0.10)
    b.charge("claude-haiku-4-5#batch", 1_000_000, 1_000_000)
    assert b.total_usd == pytest.approx(0.10 + 0.50 + 2.50)
    assert "ministral-8b-latest" in b.report()
```
*[... 16 lines trimmed - see git history]*
```python

def test_log_stage_writes_runs_row(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    costs.log_stage(conn, "verdict", "claude-haiku-4-5", 3, 100, 50, 0.01)
    row = conn.execute("SELECT * FROM runs").fetchone()
    assert row["stage"] == "verdict" and row["calls"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest knowledge/tests/test_ledger_costs.py -v`
Expected: FAIL — `cannot import name 'costs'`

- [ ] **Step 3: Implement**

```python
# knowledge/ledger/costs.py
"""Token/cost accounting. Every LLM stage charges a Budget; --max-usd aborts
cleanly (BudgetExceeded) with the ledger intact and resumable."""

from datetime import datetime, timezone

# USD per million tokens: (input, output). "#batch" = Batch API discount.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
```
*[... 54 lines trimmed - see git history]*
```python
        (datetime.now(timezone.utc).isoformat(timespec="seconds"),
         stage, model, calls, tokens_in, tokens_out, usd),
    )
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest knowledge/tests/test_ledger_costs.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/ledger/costs.py knowledge/tests/test_ledger_costs.py
git commit -m "feat(ledger): budget enforcement and per-stage cost accounting"
```

---

### Task 3: Chunking with deterministic keyword gate (`chunking.py`)

**Files:**
- Create: `knowledge/ledger/chunking.py`
- Test: `knowledge/tests/test_ledger_chunking.py`

**Interfaces:**
- Consumes: `knowledge.stoplists.code_tokens`.
- Produces: `CHUNK_CHARS = 4000`, `CHUNK_OVERLAP = 400`, `Chunk(index: int, start: int, end: int, text: str)` (frozen dataclass), `chunk_text(text: str) -> list[Chunk]`, `chunk_has_signal(text: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# knowledge/tests/test_ledger_chunking.py
from knowledge.ledger.chunking import (
    CHUNK_CHARS, CHUNK_OVERLAP, chunk_has_signal, chunk_text,
)

def test_chunks_cover_full_text_with_overlap():
    text = "x" * 10_000
    chunks = chunk_text(text)
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
    for a, b in zip(chunks, chunks[1:]):
```
*[... 7 lines trimmed - see git history]*
```python

def test_signal_gate_turkish_english_and_codes():
    assert chunk_has_signal("bu motorda kronik termostat arıza var")   # TR lexicon
    assert chunk_has_signal("the timing chain is a known failure")     # EN lexicon
    assert chunk_has_signal("the EA888 uses a different tensioner")    # code token
    assert not chunk_has_signal("today we unbox the new infotainment") # filler
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest knowledge/tests/test_ledger_chunking.py -v`
Expected: FAIL — `No module named 'knowledge.ledger.chunking'`

- [ ] **Step 3: Implement**

```python
# knowledge/ledger/chunking.py
"""Full-document chunking + the deterministic pre-LLM chunk gate.

Replaces extract.py's doc.text[:6000] cap: the WHOLE document is chunked, but
a chunk only reaches the extraction LLM if it contains failure-lexicon signal
or an engine/transmission code token — transcripts are mostly filler, and this
gate is where 50-70% of extraction tokens are saved at zero cost."""

```
*[... 45 lines trimmed - see git history]*
```python
    lowered = text.lower()
    if any(stem in lowered for stem in FAILURE_LEXICON):
        return True
    return bool(code_tokens(text))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest knowledge/tests/test_ledger_chunking.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/ledger/chunking.py knowledge/tests/test_ledger_chunking.py
git commit -m "feat(ledger): full-document chunking with deterministic signal gate"
```

---

### Task 4: Backfill ingestion (`ingest.py`)

**Files:**
- Create: `knowledge/ledger/ingest.py`
- Test: `knowledge/tests/test_ledger_ingest.py`

**Interfaces:**
- Consumes: `db.insert_document`, `db.insert_evidence`; `knowledge.sources.base.Document`.
- Produces: `ingest_document(conn, doc: Document, source_type: str, target_hint: str) -> int`; `backfill_cache_dir(conn, cache_dir: Path) -> tuple[int, int]` (docs, evidence added); `backfill_claims_dir(conn, claims_dir: Path) -> tuple[int, int]`. Backfilled evidence uses `extractor_version=0` (meaning: not re-extractable output, provenance-only seed).

Cache JSON shape (verified against `knowledge/cache/part_dq381_transmission_candidates.json`): a JSON list of `{"claim": {title, domain, severity, rationale, inspection_advice, quote, engine_or_variant_hint}, "doc": {"text": ..., "url": ..., "site_or_channel": ...}}` — `url`/`site_or_channel` may be absent. Target hint = filename stem with `part_` prefix and `_candidates` suffix stripped (e.g. `part_dq381_transmission_candidates.json` → `dq381_transmission`).

Claims YAML shape: list of claims per `docs/INTERNALS.md` §Data Formats — each has `title, domain, severity, rationale, inspection_advice, status, sources: [{source_url, site_or_channel, quote}]`. Each source becomes a document whose `raw_text` is its quote (`source_type="backfill_yaml"`); target hint = filename stem.

- [ ] **Step 1: Write the failing tests**

```python
# knowledge/tests/test_ledger_ingest.py
import json
import yaml
from knowledge.ledger import db, ingest
from knowledge.sources.base import Document

def test_ingest_document_stores_hint_not_attribution(tmp_path):
```
*[... 42 lines trimmed - see git history]*
```python
    }]))
    docs, ev = ingest.backfill_claims_dir(conn, claims)
    assert (docs, ev) == (1, 1)
    assert ingest.backfill_claims_dir(conn, claims) == (0, 0)  # idempotent
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest knowledge/tests/test_ledger_ingest.py -v`
Expected: FAIL — `cannot import name 'ingest'`

- [ ] **Step 3: Implement**

```python
# knowledge/ledger/ingest.py
"""Ledger ingestion: live fetches (Document) and one-time backfill seeds.

Backfill makes day one start from today's knowledge instead of an empty
ledger: extraction-cache JSONs carry full source text + extracted claims;
claims YAMLs carry claim + per-source quotes (quote text stands in for the
long-gone page). Backfilled evidence gets extractor_version=0; idempotency
comes from documents' text-hash dedup — a (doc, title) pair already present
```
*[... 75 lines trimmed - see git history]*
```python
                )
                ev_added += 1
    docs_after = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return docs_after - docs_before, ev_added
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest knowledge/tests/test_ledger_ingest.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/ledger/ingest.py knowledge/tests/test_ledger_ingest.py
git commit -m "feat(ledger): document ingestion and cache/YAML backfill"
```

---

### Task 5: Chunked, cached extraction (`extraction.py`)

**Files:**
- Create: `knowledge/ledger/extraction.py`
- Test: `knowledge/tests/test_ledger_extraction.py`

**Interfaces:**
- Consumes: `chunking.chunk_text/chunk_has_signal`, `db.insert_evidence/flag_low_value`, `costs.Budget`, `knowledge.langextract_client.extract_grounded(text) -> list[dict]` (mocked in tests), `knowledge.stoplists.WARNING_LIGHT_PATTERNS/GENERIC_MAINTENANCE_TERMS/has_specificity_signal`.
- Produces: `EXTRACTOR_VERSION = 2`, `EXTRACTION_MODEL = "ministral-8b-latest"`, `estimate_chunk_tokens(text) -> tuple[int, int]`, `extract_document(conn, doc_id, budget) -> int`, `extract_pending(conn, budget) -> int` (all docs with `source_type` in `("page", "youtube")` that have un-extracted chunks), `pending_extraction_estimate(conn) -> tuple[int, float]` (chunks, est USD — used by `--dry-run`).

- [ ] **Step 1: Write the failing tests**

```python
# knowledge/tests/test_ledger_extraction.py
import pytest
from knowledge.ledger import costs, db, extraction

@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "l.db")
```
*[... 65 lines trimmed - see git history]*
```python
    with pytest.raises(costs.BudgetExceeded):
        extraction.extract_document(conn, doc_id, costs.Budget(max_usd=0.000001))
    done = conn.execute("SELECT COUNT(*) FROM extraction_done").fetchone()[0]
    assert done >= 1  # settled chunks stay cached; rerun resumes, not restarts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest knowledge/tests/test_ledger_extraction.py -v`
Expected: FAIL — `cannot import name 'extraction'`

- [ ] **Step 3: Implement**

```python
# knowledge/ledger/extraction.py
"""Chunked, cached, keyword-gated extraction over ledger documents.

Versioning: v0 = backfill seed rows, v1 = the retired [:6000] single-shot
extractor, v2 = this chunked extractor. A (text_hash, chunk_index,
extractor_version) row in extraction_done means that chunk is settled for
this extractor — re-runs cost zero tokens (pipeline_postmortem #3).

```
*[... 101 lines trimmed - see git history]*
```python
            tin, tout = estimate_chunk_tokens(chunk.text)
            n += 1
            usd += estimate_cost(EXTRACTION_MODEL, tin, tout)
    return n, usd
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest knowledge/tests/test_ledger_extraction.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/ledger/extraction.py knowledge/tests/test_ledger_extraction.py
git commit -m "feat(ledger): chunked cached extraction with budget enforcement"
```

---

### Task 6: Entity resolution (`resolve.py`)

**Files:**
- Create: `knowledge/ledger/resolve.py`
- Test: `knowledge/tests/test_ledger_resolve.py`

**Interfaces:**
- Consumes: `knowledge.stoplists.code_tokens`, `catalog_code_manufacturers`, `mentions_foreign_manufacturer_code` (all catalog-derived — no hardcoded car data).
- Produces: `RESOLVER_VERSION = 1`, `component_registry() -> dict[str, str]` (uppercase CODE → lowercase component id, from `backend/data/parts/**/*.yaml` part_ids with power suffix stripped; `lru_cache`d with `.cache_clear()` for tests), `resolve_all(conn) -> dict[str, int]` (counts by method; idempotent — only unresolved evidence rows are processed). Resolution rules, in order: (1) evidence own text (title+rationale+quote+component_hint) names exactly one registered component → that component, method `alias` — **this is the sibling reroute**; (2) names several, and exactly one matches the doc's target-hint component → that one, method `alias`; (3) names none but `mentions_foreign_manufacturer_code` fires against the hint's manufacturers → `foreign`; (4) otherwise fall back to the hint's component (or the raw hint string), method `hint` — the verdict call confirms these.

- [ ] **Step 1: Write the failing tests**

```python
# knowledge/tests/test_ledger_resolve.py
import pytest
from knowledge.ledger import db, resolve

@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "l.db")
```
*[... 50 lines trimmed - see git history]*
```python
    _evidence(conn, "DQ200 dry-clutch pressure failure")
    resolve.resolve_all(conn)
    counts = resolve.resolve_all(conn)
    assert sum(counts.values()) == 0  # nothing left to resolve
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest knowledge/tests/test_ledger_resolve.py -v`
Expected: FAIL — `cannot import name 'resolve'`

- [ ] **Step 3: Implement**

```python
# knowledge/ledger/resolve.py
"""Entity resolution: which component does this evidence describe?

Attribution comes from the evidence's OWN text against catalog-derived codes
(never from the search query that found the document — design_flaws.md
Flaw 1). target_hint participates only to disambiguate genuine multi-code
comparisons and as a last-resort fallback that the verdict call re-checks."""

```
*[... 82 lines trimmed - see git history]*
```python
        )
        counts[method] += 1
    conn.commit()
    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest knowledge/tests/test_ledger_resolve.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/ledger/resolve.py knowledge/tests/test_ledger_resolve.py
git commit -m "feat(ledger): own-text entity resolution with sibling reroute"
```

---

### Task 7: Clustering (`cluster.py`)

**Files:**
- Create: `knowledge/ledger/cluster.py`
- Test: `knowledge/tests/test_ledger_cluster.py`

**Interfaces:**
- Consumes: resolutions + evidence tables; excludes `foreign`/`unresolved` components and `evidence_flags` rows.
- Produces: `CLUSTER_VERSION = 1`, `jaccard(a: str, b: str) -> float`, `rebuild_clusters(conn) -> int` (returns cluster count; wipes and rebuilds `clusters`/`cluster_members` — they are derived tables, allowed to be rebuilt; threshold 0.4 matching `dedup.same_claim`).

- [ ] **Step 1: Write the failing tests**

```python
# knowledge/tests/test_ledger_cluster.py
import pytest
from knowledge.ledger import cluster, db

@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "l.db")
```
*[... 46 lines trimmed - see git history]*
```python
    rows1 = conn.execute("SELECT * FROM cluster_members ORDER BY 1,2").fetchall()
    second = cluster.rebuild_clusters(conn)
    rows2 = conn.execute("SELECT * FROM cluster_members ORDER BY 1,2").fetchall()
    assert first == second and [tuple(r) for r in rows1] == [tuple(r) for r in rows2]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest knowledge/tests/test_ledger_cluster.py -v`
Expected: FAIL — `cannot import name 'cluster'`

- [ ] **Step 3: Implement**

```python
# knowledge/ledger/cluster.py
"""Deterministic evidence clustering per component.

Greedy single-pass in evidence-id order (stable, deterministic): an evidence
row joins the first existing cluster in the same domain whose representative
text has word-Jaccard >= 0.4 (same threshold as knowledge.dedup.same_claim),
else it founds a new cluster. clusters/cluster_members are derived tables —
rebuilt wholesale, never migrated."""
```
*[... 52 lines trimmed - see git history]*
```python
                reps.append((cid, row["domain"], text))
                total += 1
    conn.commit()
    return total
```

Note: `rebuild_clusters` deliberately does NOT touch the `verdicts` table. Verdicts are content-addressed by `input_hash` (see the `verdicts` schema in Task 1), so wiping and rebuilding clusters — which reassigns cluster ids — never evicts a cached verdict. Task 8's `run_verdicts` recomputes each cluster's `input_hash` and skips any cluster whose hash already has a stored verdict, so an unchanged cluster costs $0 on rerun regardless of the id it was rebuilt under. This also removes the earlier `cluster_id`-keyed design's foreign-key crash (verdicts FK-referencing a table being wiped).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest knowledge/tests/test_ledger_cluster.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/ledger/cluster.py knowledge/tests/test_ledger_cluster.py
git commit -m "feat(ledger): deterministic per-component evidence clustering"
```

---

### Task 8: Verdicts — one strong-model call per cluster (`verdict.py`)

**Files:**
- Create: `knowledge/ledger/verdict.py`
- Modify: `knowledge/requirements.txt` (add `anthropic`)
- Test: `knowledge/tests/test_ledger_verdict.py`

**Interfaces:**
- Consumes: clusters/evidence/documents tables, `costs.Budget`, `knowledge.stoplists.sibling_codes_for`, `anthropic` SDK (mocked in tests).
- Produces: `VERDICT_MODEL = "claude-haiku-4-5"`, `PROMPT_VERSION = 1`, `REQUIRED_KEYS`, `cluster_payload(conn, cluster_id) -> dict`, `input_hash(payload) -> str` (sha256 of canonical JSON + prompt version), `build_prompt(payload) -> str`, `parse_verdict(text) -> dict` (raises `ValueError` on bad/missing keys), `pending_clusters(conn) -> list[tuple[int, dict, str]]` (clusters with no verdict for their current input hash — **the verdict cache**), `pending_verdict_estimate(conn) -> tuple[int, float]`, `run_verdicts(conn, budget, use_batch=True) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# knowledge/tests/test_ledger_verdict.py
import json
import pytest
from knowledge.ledger import costs, db, verdict

@pytest.fixture
def conn(tmp_path):
```
*[... 70 lines trimmed - see git history]*
```python
    monkeypatch.setattr(verdict, "_client",
                        lambda: (_ for _ in ()).throw(AssertionError("must not connect")))
    with pytest.raises(costs.BudgetExceeded):
        verdict.run_verdicts(conn, costs.Budget(max_usd=0.0000001), use_batch=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest knowledge/tests/test_ledger_verdict.py -v`
Expected: FAIL — `cannot import name 'verdict'`

- [ ] **Step 3: Install dependency and implement**

Run: `pip install anthropic` and append `anthropic` on its own line to `knowledge/requirements.txt`.

```python
# knowledge/ledger/verdict.py
"""One strong-model verdict per claim-cluster.

Replaces judge.py's five ministral gates and promote.py's bypass/veto stack
(design_flaws.md Flaw 5): a single claude-haiku-4-5 call sees the whole
cluster, the component, its sibling codes, and the product principle, and
answers attribution + support + value + severity + TR/EN copy in one JSON
object. Verdicts are cached by input hash — unchanged evidence never pays
```
*[... 185 lines trimmed - see git history]*
```python
                messages=[{"role": "user", "content": build_prompt(payload)}])
            saved += _store(conn, budget, VERDICT_MODEL, cid, h, m.content[0].text,
                            m.usage.input_tokens, m.usage.output_tokens)
    return saved
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest knowledge/tests/test_ledger_verdict.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/ledger/verdict.py knowledge/tests/test_ledger_verdict.py knowledge/requirements.txt
git commit -m "feat(ledger): single Haiku batch verdict per cluster, hash-cached"
```

---

### Task 9: Aggregation and export (`export.py`)

**Files:**
- Create: `knowledge/ledger/export.py`
- Test: `knowledge/tests/test_ledger_export.py`

**Interfaces:**
- Consumes: verdicts/clusters/evidence/documents tables; `knowledge.stoplists.title_has_dtc_code/title_is_verbose/is_likely_non_english`.
- Produces: `ExportError(RuntimeError)`, `slug(title) -> str`, `independent_source_count(conn, cluster_id) -> int` (distinct URL netlocs / channels), `disposition(verdict: dict, n_independent: int, has_structured: bool) -> str | None` (`"verified"`/`"review"`/None per spec §2.5: high severity always review; verified needs ≥2 independent or structured corroboration), `export_all(conn, out_dir: Path) -> list[Path]` (one YAML per component to a gitignored build dir, deterministic ordering; skips clusters whose verdict attribution disagrees with the cluster's component — logged as contamination catches). Export **fails** (`ExportError`) on any English-copy violation: non-English `title_en`, DTC code in title, title > 100 chars, bad severity/domain.

  **Schema note (scope):** each written file is a *claims list* whose entries carry the served per-part claim fields (`claim_key`, `title`, `kind`, `domain`, `severity`, `confidence`, `status`, `rationale`, `inspection_advice`, `sources[source_url/source_domain/site_or_channel/quote/independent]`) plus the ledger's own additions — `id`/`version`/`is_current` (claim versioning) and `title_tr`/`rationale_tr`/`inspection_advice_tr` (inline bilingual copy that replaces the retired separate translate step). This is a *Stage-1 intermediate* consumed by the Task 11 parity diff (which matches on component-stem + domain + title Jaccard, not exact fields), NOT a drop-in serving file: it deliberately does not read or write `backend/data/parts` and so omits the per-part wrapper (`part_id`/`part_type`/`display_name`/`manufacturer`/`code_family`/`known_also_as`). Wrapping these claims into the real per-part file and reconciling id/version is the Stage-2 serving-plane wiring, out of scope here.

- [ ] **Step 1: Write the failing tests**

```python
# knowledge/tests/test_ledger_export.py
import json
import pytest
import yaml
from knowledge.ledger import db, export

def _verdict(**over):
```
*[... 73 lines trimmed - see git history]*
```python
def test_export_error_on_bad_copy(populated, tmp_path):
    _add_verdict(populated, _verdict(title_en="P17BF P189C fault code litany"))
    with pytest.raises(export.ExportError):
        export.export_all(populated, tmp_path / "out")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest knowledge/tests/test_ledger_export.py -v`
Expected: FAIL — `cannot import name 'export'`

- [ ] **Step 3: Implement**

```python
# knowledge/ledger/export.py
"""Export: claims as a deterministic view over verdicts.

Writes the existing claims-YAML schema (docs/INTERNALS.md §Data Formats) to a
build directory. The purge_* scripts' invariants live here as hard assertions:
bad copy fails the export instead of shipping and being mopped up later.
Nothing here deletes ledger data — an unexported cluster is retained, just
not servable."""
```
*[... 137 lines trimmed - see git history]*
```python
        path.write_text(yaml.dump(sorted(claims, key=lambda c: c["claim_key"]),
                                  allow_unicode=True, sort_keys=False))
        paths.append(path)
    return paths
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest knowledge/tests/test_ledger_export.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/ledger/export.py knowledge/tests/test_ledger_export.py
git commit -m "feat(ledger): disposition aggregation and validated YAML export"
```

---

### Task 10: Orchestrator CLI (`run.py`)

**Files:**
- Create: `knowledge/ledger/run.py`
- Test: `knowledge/tests/test_ledger_run.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `python -m knowledge.ledger.run <command>` with commands `backfill | extract | resolve | cluster | verdict | export | report | all` and flags `--db PATH` (default `db.LEDGER_PATH`), `--max-usd FLOAT`, `--dry-run` (extract/verdict/all: print planned calls + estimated USD, spend nothing), `--no-batch`. `main(argv) -> int` for testability. `report` prints cumulative spend from the `runs` table. Each LLM stage logs to `runs` via `costs.log_stage` and prints `budget.report()`. On `BudgetExceeded`: print the report, exit code 2 (ledger intact, rerun resumes).

- [ ] **Step 1: Write the failing tests**

```python
# knowledge/tests/test_ledger_run.py
from knowledge.ledger import db, run

def test_dry_run_spends_nothing(tmp_path, capsys, monkeypatch):
    dbp = tmp_path / "l.db"
    conn = db.connect(dbp)
    db.insert_document(conn, url="https://x.test/a", source_type="page",
```
*[... 50 lines trimmed - see git history]*
```python
                 " tokens_out, usd) VALUES ('t','verdict','m',1,10,5,0.01)")
    conn.commit(); conn.close()
    assert run.main(["report", "--db", str(dbp)]) == 0
    assert "verdict" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest knowledge/tests/test_ledger_run.py -v`
Expected: FAIL — `cannot import name 'run'`

- [ ] **Step 3: Implement**

```python
# knowledge/ledger/run.py
"""Ledger pipeline CLI.

    python -m knowledge.ledger.run all --max-usd 2.0
    python -m knowledge.ledger.run extract --dry-run
    python -m knowledge.ledger.run report

Every stage is resumable: extraction and verdicts are content-hash cached, so
```
*[... 92 lines trimmed - see git history]*
```python

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest knowledge/tests/test_ledger_run.py -v`
Expected: 3 PASS. Also run the full ledger suite: `python -m pytest knowledge/tests/test_ledger_*.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add knowledge/ledger/run.py knowledge/tests/test_ledger_run.py
git commit -m "feat(ledger): resumable pipeline CLI with dry-run and cost report"
```

---

### Task 11: Acceptance — parity diff, verdict eval, real backfill run

**Files:**
- Create: `knowledge/ledger/parity.py`
- Create: `knowledge/ledger/eval_verdict.py`
- Test: `knowledge/tests/test_ledger_parity.py`

**Interfaces:**
- Consumes: `cluster.jaccard`, existing `backend/data/parts/**/*.yaml` claim lists and `backend/data/claims/*.yaml`, `knowledge/gold/gold.yaml` (11 entries, fields: `title, domain, severity, rationale, quote, verdict: correct|incorrect`).
- Produces: `parity.compare(existing_dirs: list[Path], export_dir: Path) -> str` (human-readable diff: claims only-in-existing, only-in-export, matched — matched = same component file stem + domain + title Jaccard ≥ 0.4); `eval_verdict.main() -> int` (builds one single-evidence cluster payload per gold entry, calls `verdict` sync, prints per-entry outcome; **exit 1 if any `verdict: incorrect` gold entry comes back `supported=True` + `product_value="high"`**).

- [ ] **Step 1: Write the failing test (parity matching logic only — eval is manual)**

```python
# knowledge/tests/test_ledger_parity.py
import yaml
from knowledge.ledger import parity

def test_compare_reports_matched_and_missing(tmp_path):
    old = tmp_path / "old"; old.mkdir()
    new = tmp_path / "new"; new.mkdir()
    # existing backend part files are a dict with a `claims:` list; the ledger
    # export is a bare list — _load must read both (dict shape covered here).
    (old / "dq381.yaml").write_text(yaml.dump({
        "part_id": "dq381", "part_type": "transmission",
```
*[... 5 lines trimmed - see git history]*
```python
    (new / "dq381.yaml").write_text(yaml.dump([
        {"title": "Mechatronic solenoid wear on DQ381", "domain": "transmission"},
    ]))
    report = parity.compare([old], new)
    assert "matched: 1" in report
    assert "DQ200 hydraulic pressure failure" in report  # only-in-existing, listed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest knowledge/tests/test_ledger_parity.py -v`
Expected: FAIL — `cannot import name 'parity'`

- [ ] **Step 3: Implement both tools**

```python
# knowledge/ledger/parity.py
"""Golden-export regression: diff existing claim YAMLs against the ledger
export. Every difference must be an explainable improvement (e.g. DQ200
claims leaving dq381.yaml) — reviewed by a human once, then the export
becomes the new golden set."""

from pathlib import Path

```
*[... 47 lines trimmed - see git history]*
```python
        [root / "backend" / "data" / "claims", root / "backend" / "data" / "parts"],
        Path(sys.argv[1]) if len(sys.argv) > 1
        else Path(__file__).parent.parent / "ledger_export",
    ))
```

```python
# knowledge/ledger/eval_verdict.py
"""Verdict-quality eval over knowledge/gold/gold.yaml (11 hand-judged entries).

Acceptance bar before judge.py's gates may be retired: every gold entry with
verdict: incorrect must NOT come back supported + product_value=high. Prints
per-entry outcomes; exit 1 on any must-catch failure. Costs ~11 sync Haiku
calls (~$0.02)."""

```
*[... 46 lines trimmed - see git history]*
```python

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest knowledge/tests/test_ledger_parity.py -v`
Expected: 1 PASS

- [ ] **Step 5: Commit the tools**

```bash
git add knowledge/ledger/parity.py knowledge/ledger/eval_verdict.py knowledge/tests/test_ledger_parity.py
git commit -m "feat(ledger): parity diff and gold-set verdict eval"
```

- [ ] **Step 6: MANUAL ACCEPTANCE RUN (spends real tokens — needs `MISTRAL_API_KEY` + `ANTHROPIC_API_KEY`)**

```bash
python -m knowledge.ledger.run backfill
python -m knowledge.ledger.run all --dry-run          # inspect planned spend first
python -m knowledge.ledger.run all --max-usd 5.0      # backfilled evidence: verdicts only, no extraction
python -m knowledge.ledger.run report
python -m knowledge.ledger.eval_verdict               # must exit 0
python -m knowledge.ledger.parity                     # review the diff by hand
```

Expected: dry-run estimates ≪ $5 (backfill needs no extraction — evidence already exists at v0; the spend is one batch verdict per cluster over today's ~15 part files). Eval exits 0. Parity diff: every "only in existing YAML" line is explainable (contamination catches like DQ200-in-dq381, generic items the product principle drops); no genuine claim silently lost. **STOP and get human sign-off on the parity report before Task 12.**

---

### Task 12: Retirement (GATED — only after Task 11 human sign-off)

**Files:**
- Delete: `knowledge/purge_forums.py`, `knowledge/purge_german.py`, `knowledge/purge_invalid_severity.py`, `knowledge/purge_offtopic_contamination.py`, `knowledge/downgrade_unsourced_claims.py`, `knowledge/normalize_domains.py` (keep `knowledge/domains.py` — extraction still uses `normalize_domain`), `knowledge/find_cross_file_duplicates.py`, `knowledge/fix_sibling_contamination.py`, `knowledge/translate_claims.py`
- Modify: `docs/INTERNALS.md` (knowledge-plane section: describe the ledger flow; note `judge.py`/`promote.py` remain only for the legacy `process.py` path until stage 2 rewires `auto.py`)

Do **not** delete `judge.py`, `promote.py`, or `dedup.py` yet — `process.py`/`auto.py` still import them; rewiring those entry points onto the ledger is stage 2 work (spec §6). This task removes only the post-hoc mop-up scripts whose invariants now live in `export.py`'s validation.

- [ ] **Step 1: Verify nothing imports the scripts being deleted**

Run: `grep -rn "purge_forums\|purge_german\|purge_invalid\|purge_offtopic\|downgrade_unsourced\|normalize_domains\|find_cross_file\|fix_sibling_contamination\|translate_claims" knowledge/ backend/ --include=*.py | grep -v "^knowledge/purge\|^knowledge/downgrade\|^knowledge/normalize_domains\|^knowledge/find_cross\|^knowledge/fix_sibling\|^knowledge/translate_claims"`
Expected: only matches inside the files being deleted themselves (and their tests, if any — delete `knowledge/tests/test_translate_claims.py` alongside).

- [ ] **Step 2: Delete the files, update `docs/INTERNALS.md`**

```bash
git rm knowledge/purge_forums.py knowledge/purge_german.py \
  knowledge/purge_invalid_severity.py knowledge/purge_offtopic_contamination.py \
  knowledge/downgrade_unsourced_claims.py knowledge/normalize_domains.py \
  knowledge/find_cross_file_duplicates.py knowledge/fix_sibling_contamination.py \
  knowledge/translate_claims.py knowledge/tests/test_translate_claims.py
```

- [ ] **Step 3: Run the FULL test suite (knowledge + backend)**

Run: `python -m pytest knowledge/tests/ backend/tests/ -v`
Expected: all PASS (no survivor imports the deleted modules).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(ledger): retire post-hoc purge scripts superseded by export validation"
```

---

## Self-Review Notes

- **Spec coverage:** ledger schema+append-only (T1), cost model §3 (T2, enforced in T5/T8/T10), chunk gate §2.3 (T3, T5), backfill §2.3 (T4), full-length extraction cache (T5), two-tier attribution/sibling reroute §2.4 (T6), clustering (T7), single verdict call + translation folding (T8), aggregation/dispositions/export assertions §2.5 (T9), CLI + `--max-usd`/`--dry-run`/report §3.3 (T10), golden parity + judge eval §5 (T11), retirement §4 (T12, correctly narrowed: gates/`promote.py` retire in stage 2 when `auto.py` is rewired — spec's "retired once export parity is proven" applies to the mop-up scripts now, the gate stack after the entry points move). Structured feeds §2.2 and coverage-gap acquisition §2.6 are stage 2/3 — out of scope here by design.
- **Interfaces cross-checked:** `db.insert_evidence(claim=...)` dict shape matches `extract_grounded`'s output keys everywhere; `costs.Budget.charge/precheck` used consistently in T5/T8; `cluster.jaccard` reused by `parity`; `VALID`/`_FakeMsg` imported from the T8 test in the T10 test intentionally.


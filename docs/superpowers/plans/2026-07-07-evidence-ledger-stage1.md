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
    return db.connect(tmp_path / "ledger.db")


def _doc(conn, text="EA888 timing chain stretch", url="https://x.test/a"):
    return db.insert_document(conn, url=url, source_type="page", raw_text=text)


def test_insert_document_dedups_by_text_hash(conn):
    a = _doc(conn)
    b = _doc(conn, url="https://different.test/b")  # same text
    assert a == b
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_documents_and_evidence_are_append_only(conn):
    doc_id = _doc(conn)
    ev_id = db.insert_evidence(
        conn, doc_id=doc_id,
        claim={"title": "t", "domain": "engine", "severity": "medium",
               "rationale": "r", "inspection_advice": "i", "quote": "q",
               "engine_or_variant_hint": "EA888", "quote_grounded": True},
        span_start=0, span_end=5, extractor_version=2,
    )
    for stmt in (
        "DELETE FROM documents", "UPDATE documents SET url='x'",
        "DELETE FROM evidence", f"UPDATE evidence SET title='x' WHERE id={ev_id}",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(stmt)


def test_low_value_flag_lives_outside_evidence(conn):
    doc_id = _doc(conn)
    ev_id = db.insert_evidence(
        conn, doc_id=doc_id,
        claim={"title": "warning light", "domain": "general", "severity": "low",
               "rationale": "", "inspection_advice": "", "quote": "",
               "engine_or_variant_hint": None, "quote_grounded": False},
        span_start=None, span_end=None, extractor_version=2,
    )
    db.flag_low_value(conn, ev_id, "warning-light pattern")
    row = conn.execute(
        "SELECT reason FROM evidence_flags WHERE evidence_id=?", (ev_id,)
    ).fetchone()
    assert row["reason"] == "warning-light pattern"


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

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

LEDGER_PATH = Path(__file__).parent.parent / "ledger.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    source_type TEXT NOT NULL,          -- page | youtube | structured | backfill_cache | backfill_yaml
    site_or_channel TEXT NOT NULL DEFAULT '',
    lang TEXT NOT NULL DEFAULT '',
    target_hint TEXT NOT NULL DEFAULT '',  -- search context that found it: a HINT, never attribution
    raw_text TEXT NOT NULL,
    text_hash TEXT NOT NULL UNIQUE,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    doc_id INTEGER NOT NULL REFERENCES documents(id),
    span_start INTEGER, span_end INTEGER,
    quote TEXT NOT NULL DEFAULT '',
    quote_grounded INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    domain TEXT NOT NULL,
    severity TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    inspection_advice TEXT NOT NULL DEFAULT '',
    component_hint TEXT,                -- extractor's own-text reading (engine_or_variant_hint)
    extractor_version INTEGER NOT NULL,
    extracted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_flags (      -- derived: deterministic low-value marks
    evidence_id INTEGER PRIMARY KEY REFERENCES evidence(id),
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extraction_done (     -- cache: this chunk was extracted by this extractor
    text_hash TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    extractor_version INTEGER NOT NULL,
    PRIMARY KEY (text_hash, chunk_index, extractor_version)
);
CREATE TABLE IF NOT EXISTS resolutions (
    evidence_id INTEGER PRIMARY KEY REFERENCES evidence(id),
    component_id TEXT NOT NULL,         -- catalog component | 'foreign' | 'unresolved'
    method TEXT NOT NULL,               -- alias | foreign | hint
    resolver_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    component_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    cluster_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cluster_members (
    cluster_id INTEGER NOT NULL REFERENCES clusters(id),
    evidence_id INTEGER NOT NULL REFERENCES evidence(id),
    PRIMARY KEY (cluster_id, evidence_id)
);
-- Content-addressed verdict cache: keyed on the payload input_hash, NOT the
-- cluster id. Clusters are wiped/rebuilt wholesale with reassigned ids every
-- run, so a cluster_id key both crashed rebuild (FK into a wiped table) and
-- lost the cache when ids shifted (onboarding a 2nd car re-judged the 1st
-- car's unchanged clusters). By hash, an unchanged cluster hits cache under
-- its new id and rebuild never touches this table. A cluster maps to its
-- verdict by recomputing verdict.input_hash — no cluster_id column needed.
CREATE TABLE IF NOT EXISTS verdicts (
    input_hash TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    verdict_json TEXT NOT NULL,
    tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL, usd REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    stage TEXT NOT NULL,
    model TEXT NOT NULL,
    calls INTEGER NOT NULL,
    tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL, usd REAL NOT NULL
);
"""

_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS documents_no_delete BEFORE DELETE ON documents
BEGIN SELECT RAISE(ABORT, 'documents is append-only'); END;
CREATE TRIGGER IF NOT EXISTS documents_no_update BEFORE UPDATE ON documents
BEGIN SELECT RAISE(ABORT, 'documents is append-only'); END;
CREATE TRIGGER IF NOT EXISTS evidence_no_delete BEFORE DELETE ON evidence
BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END;
CREATE TRIGGER IF NOT EXISTS evidence_no_update BEFORE UPDATE ON evidence
BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def connect(path: Path | str = LEDGER_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.executescript(_TRIGGERS)
    return conn


def insert_document(conn, *, url: str, source_type: str, raw_text: str,
                    site_or_channel: str = "", lang: str = "",
                    target_hint: str = "") -> int:
    h = text_hash(raw_text)
    row = conn.execute("SELECT id FROM documents WHERE text_hash=?", (h,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO documents (url, source_type, site_or_channel, lang, target_hint,"
        " raw_text, text_hash, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
        (url, source_type, site_or_channel, lang, target_hint, raw_text, h, _now()),
    )
    conn.commit()
    return cur.lastrowid


def insert_evidence(conn, *, doc_id: int, claim: dict,
                    span_start: int | None, span_end: int | None,
                    extractor_version: int) -> int:
    cur = conn.execute(
        "INSERT INTO evidence (doc_id, span_start, span_end, quote, quote_grounded,"
        " title, domain, severity, rationale, inspection_advice, component_hint,"
        " extractor_version, extracted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (doc_id, span_start, span_end,
         claim.get("quote") or "", int(bool(claim.get("quote_grounded"))),
         claim["title"], claim["domain"], claim["severity"],
         claim.get("rationale") or "", claim.get("inspection_advice") or "",
         claim.get("engine_or_variant_hint"), extractor_version, _now()),
    )
    conn.commit()
    return cur.lastrowid


def flag_low_value(conn, evidence_id: int, reason: str) -> None:
    conn.execute(
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


def test_charge_raises_when_budget_exceeded():
    b = costs.Budget(max_usd=0.05)
    with pytest.raises(costs.BudgetExceeded):
        b.charge("claude-haiku-4-5", 100_000, 0)  # $0.10 > $0.05
    # the spend is still recorded so the report is honest
    assert b.total_usd == pytest.approx(0.10)


def test_precheck_blocks_before_spending():
    b = costs.Budget(max_usd=1.0)
    b.precheck(0.5)  # fine
    with pytest.raises(costs.BudgetExceeded):
        b.precheck(1.5)


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
    "ministral-8b-latest": (0.10, 0.10),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-4-5#batch": (0.50, 2.50),
}


class BudgetExceeded(RuntimeError):
    pass


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    p_in, p_out = PRICES_USD_PER_MTOK[model]
    return tokens_in * p_in / 1e6 + tokens_out * p_out / 1e6


class Budget:
    def __init__(self, max_usd: float | None = None):
        self.max_usd = max_usd
        self._by_model: dict[str, tuple[int, int, int, float]] = {}  # calls, tin, tout, usd

    @property
    def total_usd(self) -> float:
        return sum(v[3] for v in self._by_model.values())

    def charge(self, model: str, tokens_in: int, tokens_out: int) -> float:
        usd = estimate_cost(model, tokens_in, tokens_out)
        c, ti, to, u = self._by_model.get(model, (0, 0, 0, 0.0))
        self._by_model[model] = (c + 1, ti + tokens_in, to + tokens_out, u + usd)
        if self.max_usd is not None and self.total_usd > self.max_usd:
            raise BudgetExceeded(
                f"spent ${self.total_usd:.2f} > --max-usd ${self.max_usd:.2f}"
            )
        return usd

    def precheck(self, est_usd: float) -> None:
        """Raise BEFORE an unabortable spend (e.g. submitting a message batch)."""
        if self.max_usd is not None and self.total_usd + est_usd > self.max_usd:
            raise BudgetExceeded(
                f"planned +${est_usd:.2f} would exceed --max-usd ${self.max_usd:.2f}"
            )

    def report(self) -> str:
        lines = ["model                      calls   tok_in   tok_out      usd"]
        for m, (c, ti, to, u) in sorted(self._by_model.items()):
            lines.append(f"{m:<26} {c:>5} {ti:>8} {to:>9} {u:>8.4f}")
        lines.append(f"{'TOTAL':<26} {'':>5} {'':>8} {'':>9} {self.total_usd:>8.4f}")
        return "\n".join(lines)


def log_stage(conn, stage: str, model: str, calls: int,
              tokens_in: int, tokens_out: int, usd: float) -> None:
    conn.execute(
        "INSERT INTO runs (started_at, stage, model, calls, tokens_in, tokens_out, usd)"
        " VALUES (?,?,?,?,?,?,?)",
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
        assert b.start == a.end - CHUNK_OVERLAP  # overlap preserved
    assert all(len(c.text) <= CHUNK_CHARS for c in chunks)


def test_short_text_is_single_chunk():
    assert len(chunk_text("short")) == 1


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

from dataclasses import dataclass

from knowledge.stoplists import code_tokens

CHUNK_CHARS = 4000
CHUNK_OVERLAP = 400

# Substring stems, not whole words: Turkish agglutination means "bozul" must
# match bozuldu/bozulması/bozulan. Lowercased match. Genuinely closed
# vocabulary (fixed engineering/failure words), so a constant is allowed per
# CLAUDE.md's scalability-principle exception.
FAILURE_LEXICON: frozenset[str] = frozenset({
    # Turkish
    "arıza", "ariza", "sorun", "kronik", "bozul", "patla", "sızdır", "sizdir",
    "kaçır", "kacir", "değiş", "degis", "yaptırdım", "yaptirdim", "garanti",
    # English
    "fail", "fault", "problem", "issue", "broke", "broken", "defect",
    "recall", "leak", "wear", "worn", "replace", "repair", "chronic",
    "stretch", "rattle", "shudder", "judder", "misfire", "clog",
})


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int
    end: int
    text: str


def chunk_text(text: str) -> list[Chunk]:
    step = CHUNK_CHARS - CHUNK_OVERLAP
    chunks: list[Chunk] = []
    i, start = 0, 0
    while start < len(text) or not chunks:
        end = min(start + CHUNK_CHARS, len(text))
        chunks.append(Chunk(index=i, start=start, end=end, text=text[start:end]))
        if end == len(text):
            break
        start += step
        i += 1
    return chunks


def chunk_has_signal(text: str) -> bool:
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
    conn = db.connect(tmp_path / "l.db")
    doc = Document(text="DQ200 accumulator fails", url="https://x.test/dsg",
                   site_or_channel="x.test")
    doc_id = ingest.ingest_document(conn, doc, "page", target_hint="dq381")
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert row["target_hint"] == "dq381"
    assert row["raw_text"] == "DQ200 accumulator fails"


def test_backfill_cache_dir(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "part_dq381_transmission_candidates.json").write_text(json.dumps([{
        "claim": {"title": "DQ200 hydraulic pressure failure", "domain": "transmission",
                  "severity": "high", "rationale": "r", "inspection_advice": "i",
                  "quote": "q", "engine_or_variant_hint": "DQ200"},
        "doc": {"text": "full page text about DSG", "url": "https://x.test/dsg",
                "site_or_channel": "x.test"},
    }]))
    docs, ev = ingest.backfill_cache_dir(conn, cache)
    assert (docs, ev) == (1, 1)
    row = conn.execute(
        "SELECT e.component_hint, d.target_hint FROM evidence e"
        " JOIN documents d ON d.id=e.doc_id"
    ).fetchone()
    assert row["component_hint"] == "DQ200"
    assert row["target_hint"] == "dq381_transmission"
    # idempotent: re-run adds nothing
    assert ingest.backfill_cache_dir(conn, cache) == (0, 0)


def test_backfill_claims_dir(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / "renault_megane_4.yaml").write_text(yaml.dump([{
        "claim_key": "megane4_k9k_injectors", "title": "K9K injector fouling",
        "domain": "engine", "severity": "medium", "rationale": "r",
        "inspection_advice": "i", "status": "verified",
        "sources": [{"source_url": "https://s.test/a", "site_or_channel": "s.test",
                     "quote": "K9K injectors foul at high mileage"}],
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
is skipped."""

import json
from pathlib import Path

import yaml

from knowledge.ledger import db
from knowledge.sources.base import Document


def ingest_document(conn, doc: Document, source_type: str, target_hint: str) -> int:
    return db.insert_document(
        conn, url=doc.url, source_type=source_type, raw_text=doc.text,
        site_or_channel=doc.site_or_channel, target_hint=target_hint,
    )


def _evidence_exists(conn, doc_id: int, title: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM evidence WHERE doc_id=? AND title=?", (doc_id, title)
    ).fetchone() is not None


def backfill_cache_dir(conn, cache_dir: Path) -> tuple[int, int]:
    docs_before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    ev_added = 0
    for path in sorted(cache_dir.glob("*_candidates.json")):
        hint = path.stem.removeprefix("part_").removesuffix("_candidates")
        for item in json.loads(path.read_text()):
            claim, doc = item.get("claim") or {}, item.get("doc") or {}
            text = doc.get("text") or ""
            if not text or not claim.get("title"):
                continue
            doc_id = db.insert_document(
                conn, url=doc.get("url") or f"backfill:{path.name}",
                source_type="backfill_cache",
                site_or_channel=doc.get("site_or_channel") or "",
                target_hint=hint, raw_text=text,
            )
            if _evidence_exists(conn, doc_id, claim["title"]):
                continue
            db.insert_evidence(conn, doc_id=doc_id, claim=claim,
                               span_start=None, span_end=None, extractor_version=0)
            ev_added += 1
    docs_after = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return docs_after - docs_before, ev_added


def backfill_claims_dir(conn, claims_dir: Path) -> tuple[int, int]:
    docs_before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    ev_added = 0
    for path in sorted(claims_dir.glob("*.yaml")):
        for claim in yaml.safe_load(path.read_text()) or []:
            for src in claim.get("sources") or []:
                quote = src.get("quote") or ""
                if not quote or not claim.get("title"):
                    continue
                doc_id = db.insert_document(
                    conn, url=src.get("source_url") or f"backfill:{path.name}",
                    source_type="backfill_yaml",
                    site_or_channel=src.get("site_or_channel") or "",
                    target_hint=path.stem, raw_text=quote,
                )
                if _evidence_exists(conn, doc_id, claim["title"]):
                    continue
                db.insert_evidence(
                    conn, doc_id=doc_id,
                    claim={"title": claim["title"], "domain": claim.get("domain", "general"),
                           "severity": claim.get("severity", "medium"),
                           "rationale": claim.get("rationale", ""),
                           "inspection_advice": claim.get("inspection_advice", ""),
                           "quote": quote,
                           "engine_or_variant_hint": None, "quote_grounded": False},
                    span_start=None, span_end=None, extractor_version=0,
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


def _page(conn, text, hint="dq381"):
    return db.insert_document(conn, url="https://x.test/a", source_type="page",
                              raw_text=text, target_hint=hint)


def test_extracts_only_signal_chunks_and_caches(conn, monkeypatch):
    calls = []
    def fake_extract(text):
        calls.append(text)
        return [{"title": "DQ200 accumulator failure", "domain": "transmission",
                 "severity": "high", "rationale": "hydraulic pressure loss",
                 "inspection_advice": "scan for P189C", "quote": text[:30],
                 "engine_or_variant_hint": "DQ200", "quote_grounded": True}]
    monkeypatch.setattr(extraction, "extract_grounded", fake_extract)

    filler = "unboxing the infotainment today " * 200        # no signal
    signal = " the DQ200 accumulator is a chronic failure " * 100
    doc_id = _page(conn, filler + signal)
    budget = costs.Budget()

    added = extraction.extract_document(conn, doc_id, budget)
    assert added >= 1
    n_first = len(calls)
    assert 0 < n_first  # signal chunks called
    # filler-only leading chunk was skipped: fewer calls than total chunks
    from knowledge.ledger.chunking import chunk_text
    assert n_first < len(chunk_text(filler + signal))

    # second run: fully cached, zero LLM calls, zero new evidence
    assert extraction.extract_document(conn, doc_id, budget) == 0
    assert len(calls) == n_first


def test_span_mapped_to_full_document(conn, monkeypatch):
    text = ("padding " * 50) + "the EA888 timing chain stretches early" + (" tail" * 50)
    quote = "EA888 timing chain stretches"
    monkeypatch.setattr(extraction, "extract_grounded", lambda t: [{
        "title": "EA888 chain stretch", "domain": "engine", "severity": "high",
        "rationale": "known failure", "inspection_advice": "listen cold start",
        "quote": quote, "engine_or_variant_hint": "EA888", "quote_grounded": True}])
    doc_id = _page(conn, text)
    extraction.extract_document(conn, doc_id, costs.Budget())
    row = conn.execute("SELECT span_start, span_end FROM evidence").fetchone()
    assert row["span_start"] == text.find(quote)
    assert row["span_end"] == text.find(quote) + len(quote)


def test_deterministic_low_value_flagging(conn, monkeypatch):
    monkeypatch.setattr(extraction, "extract_grounded", lambda t: [{
        "title": "ABS warning light comes on", "domain": "electrical",
        "severity": "low", "rationale": "dashboard warning light appears",
        "inspection_advice": "", "quote": "arıza lambası", "quote_grounded": True,
        "engine_or_variant_hint": None}])
    doc_id = _page(conn, "kronik arıza lambası sorunu " * 100)
    extraction.extract_document(conn, doc_id, costs.Budget())
    assert conn.execute("SELECT COUNT(*) FROM evidence_flags").fetchone()[0] == 1


def test_budget_abort_leaves_ledger_resumable(conn, monkeypatch):
    monkeypatch.setattr(extraction, "extract_grounded", lambda t: [])
    # leading filler chunk (settled free, cached) then signal chunks (charged)
    text = ("unboxing video intro " * 300) + ("chronic failure text " * 2000)
    doc_id = _page(conn, text)
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

Token accounting is estimated (len//4 input, flat 350 output per chunk):
langextract does not surface Mistral usage numbers. Estimates are charged
to the Budget so --max-usd still binds."""

import re

from knowledge.langextract_client import extract_grounded
from knowledge.ledger import db
from knowledge.ledger.chunking import chunk_has_signal, chunk_text
from knowledge.ledger.costs import Budget, estimate_cost
from knowledge.stoplists import (
    GENERIC_MAINTENANCE_TERMS, WARNING_LIGHT_PATTERNS, has_specificity_signal,
)

EXTRACTOR_VERSION = 2
EXTRACTION_MODEL = "ministral-8b-latest"
_OUT_TOKENS_PER_CHUNK = 350


def estimate_chunk_tokens(text: str) -> tuple[int, int]:
    return len(text) // 4, _OUT_TOKENS_PER_CHUNK


def _deterministic_low_value_reason(claim: dict) -> str | None:
    text = f"{claim.get('title', '')} {claim.get('rationale', '')}".lower()
    for pat in WARNING_LIGHT_PATTERNS:
        if pat.search(text):
            return "warning-light pattern"
    hit = next((kw for kw in GENERIC_MAINTENANCE_TERMS if kw in text), None)
    if hit and not has_specificity_signal(text):
        return f"generic maintenance: {hit!r}"
    return None


def _chunk_done(conn, text_hash: str, chunk_index: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM extraction_done WHERE text_hash=? AND chunk_index=?"
        " AND extractor_version=?", (text_hash, chunk_index, EXTRACTOR_VERSION),
    ).fetchone() is not None


def extract_document(conn, doc_id: int, budget: Budget) -> int:
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    text, h = doc["raw_text"], doc["text_hash"]
    added = 0
    for chunk in chunk_text(text):
        if _chunk_done(conn, h, chunk.index):
            continue
        if not chunk_has_signal(chunk.text):
            # settled without an LLM call — gate result is cached too
            conn.execute("INSERT INTO extraction_done VALUES (?,?,?)",
                         (h, chunk.index, EXTRACTOR_VERSION))
            conn.commit()
            continue
        tin, tout = estimate_chunk_tokens(chunk.text)
        budget.charge(EXTRACTION_MODEL, tin, tout)  # raises BudgetExceeded → resumable
        for claim in extract_grounded(chunk.text):
            quote = claim.get("quote") or ""
            pos = text.find(quote, chunk.start) if quote else -1
            if pos < 0:
                pos = text.find(quote) if quote else -1
            ev_id = db.insert_evidence(
                conn, doc_id=doc_id, claim=claim,
                span_start=pos if pos >= 0 else None,
                span_end=pos + len(quote) if pos >= 0 else None,
                extractor_version=EXTRACTOR_VERSION,
            )
            reason = _deterministic_low_value_reason(claim)
            if reason:
                db.flag_low_value(conn, ev_id, reason)
            added += 1
        conn.execute("INSERT INTO extraction_done VALUES (?,?,?)",
                     (h, chunk.index, EXTRACTOR_VERSION))
        conn.commit()
    return added


def _pending_docs(conn) -> list:
    return conn.execute(
        "SELECT id FROM documents WHERE source_type IN ('page','youtube') ORDER BY id"
    ).fetchall()


def extract_pending(conn, budget: Budget) -> int:
    total = 0
    for row in _pending_docs(conn):
        total += extract_document(conn, row["id"], budget)
    return total


def pending_extraction_estimate(conn) -> tuple[int, float]:
    """(chunks that would call the LLM, estimated USD) — for --dry-run."""
    n, usd = 0, 0.0
    for row in _pending_docs(conn):
        doc = conn.execute("SELECT raw_text, text_hash FROM documents WHERE id=?",
                           (row["id"],)).fetchone()
        for chunk in chunk_text(doc["raw_text"]):
            if _chunk_done(conn, doc["text_hash"], chunk.index):
                continue
            if not chunk_has_signal(chunk.text):
                continue
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


@pytest.fixture
def registry(monkeypatch):
    # Registry is normally derived from backend/data/parts/**; pin it here so
    # the test doesn't depend on which cars are currently onboarded.
    monkeypatch.setattr(resolve, "component_registry",
                        lambda: {"DQ200": "dq200", "DQ381": "dq381", "K9K": "k9k"})


def _evidence(conn, title, rationale="", hint=None, target_hint="dq381_transmission"):
    doc_id = db.insert_document(conn, url=f"https://x.test/{title[:8]}",
                                source_type="page", raw_text=title + rationale,
                                target_hint=target_hint)
    return db.insert_evidence(conn, doc_id=doc_id, claim={
        "title": title, "domain": "transmission", "severity": "high",
        "rationale": rationale, "inspection_advice": "", "quote": "",
        "engine_or_variant_hint": hint, "quote_grounded": False,
    }, span_start=None, span_end=None, extractor_version=2)


def _resolution(conn, ev_id):
    return conn.execute("SELECT * FROM resolutions WHERE evidence_id=?",
                        (ev_id,)).fetchone()


def test_sibling_reroute_own_text_beats_search_context(conn, registry):
    # The design_flaws.md Flaw 1 canary: DQ200 claim found while researching DQ381.
    ev = _evidence(conn, "DQ200 dry-clutch pressure failure",
                   "the DQ200 accumulator loses pressure", hint="DQ200")
    resolve.resolve_all(conn)
    r = _resolution(conn, ev)
    assert r["component_id"] == "dq200" and r["method"] == "alias"


def test_no_code_falls_back_to_hint(conn, registry):
    ev = _evidence(conn, "Mechatronic unit failure", "gearbox jerks when hot")
    resolve.resolve_all(conn)
    r = _resolution(conn, ev)
    assert r["component_id"] == "dq381" and r["method"] == "hint"


def test_multiple_codes_disambiguated_by_hint(conn, registry):
    ev = _evidence(conn, "DQ200 vs DQ381 clutch comparison",
                   "the DQ381 wet clutch avoids DQ200 issues")
    resolve.resolve_all(conn)
    assert _resolution(conn, ev)["component_id"] == "dq381"


def test_resolve_all_is_idempotent(conn, registry):
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

import re
from functools import lru_cache
from pathlib import Path

import yaml

from knowledge.ledger import db  # noqa: F401  (shared connection conventions)
from knowledge.stoplists import (
    catalog_code_manufacturers, code_tokens, mentions_foreign_manufacturer_code,
)

RESOLVER_VERSION = 1
_PARTS_DIR = Path(__file__).parent.parent.parent / "backend" / "data" / "parts"
_POWER_SUFFIX_RE = re.compile(r"_\d+$")


@lru_cache(maxsize=1)
def component_registry() -> dict[str, str]:
    """Uppercase CODE -> lowercase component id, derived from part YAMLs.

    Same derive-from-catalog pattern as stoplists.catalog_code_manufacturers:
    a new part is covered the moment its stub exists. Power-tune suffixes
    (ea888_220) collapse onto the engineering identity (ea888)."""
    reg: dict[str, str] = {}
    for path in _PARTS_DIR.glob("**/*.yaml"):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        part_id = data.get("part_id")
        if not part_id:
            continue
        base = _POWER_SUFFIX_RE.sub("", str(part_id))
        for code in code_tokens(base):
            reg[code] = base.lower()
    return reg


def _hint_components(target_hint: str, reg: dict[str, str]) -> set[str]:
    base = _POWER_SUFFIX_RE.sub("", target_hint or "")
    return {reg[t] for t in code_tokens(base) if t in reg}


def resolve_all(conn) -> dict[str, int]:
    reg = component_registry()
    counts = {"alias": 0, "foreign": 0, "hint": 0}
    rows = conn.execute(
        "SELECT e.id, e.title, e.rationale, e.quote, e.component_hint, d.target_hint"
        " FROM evidence e JOIN documents d ON d.id = e.doc_id"
        " LEFT JOIN resolutions r ON r.evidence_id = e.id"
        " WHERE r.evidence_id IS NULL ORDER BY e.id"
    ).fetchall()
    for row in rows:
        own_text = " ".join(filter(None, (
            row["title"], row["rationale"], row["quote"], row["component_hint"])))
        named = {reg[t] for t in code_tokens(own_text) if t in reg}
        hinted = _hint_components(row["target_hint"], reg)

        if len(named) == 1:
            comp, method = next(iter(named)), "alias"
        elif len(named) > 1:
            inter = named & hinted
            if len(inter) == 1:
                comp, method = next(iter(inter)), "alias"
            else:
                comp, method = "unresolved", "hint"
        else:
            own_makes: set[str] = set()
            for c in hinted:
                own_makes |= catalog_code_manufacturers().get(c.upper(), frozenset())
            if own_makes and mentions_foreign_manufacturer_code(own_text, own_makes):
                comp, method = "foreign", "foreign"
            elif len(hinted) == 1:
                comp, method = next(iter(hinted)), "hint"
            else:
                comp = (row["target_hint"] or "unresolved").lower() or "unresolved"
                method = "hint"

        conn.execute(
            "INSERT INTO resolutions (evidence_id, component_id, method,"
            " resolver_version) VALUES (?,?,?,?)",
            (row["id"], comp, method, RESOLVER_VERSION),
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


def _resolved_evidence(conn, title, rationale, component="ea888",
                       domain="engine", flagged=False, url=None):
    doc_id = db.insert_document(conn, url=url or f"https://x.test/{title[:12]}",
                                source_type="page", raw_text=title)
    ev_id = db.insert_evidence(conn, doc_id=doc_id, claim={
        "title": title, "domain": domain, "severity": "high",
        "rationale": rationale, "inspection_advice": "", "quote": "",
        "engine_or_variant_hint": None, "quote_grounded": False,
    }, span_start=None, span_end=None, extractor_version=2)
    conn.execute("INSERT INTO resolutions VALUES (?,?,?,?)",
                 (ev_id, component, "alias", 1))
    if flagged:
        db.flag_low_value(conn, ev_id, "test flag")
    conn.commit()
    return ev_id


def test_similar_claims_cluster_together(conn):
    a = _resolved_evidence(conn, "EA888 timing chain tensioner failure",
                           "timing chain tensioner wears causing chain stretch")
    b = _resolved_evidence(conn, "Timing chain stretch on EA888 engines",
                           "tensioner failure lets the timing chain stretch")
    _resolved_evidence(conn, "EA888 excessive oil consumption",
                       "piston rings allow oil burning at high mileage")
    n = cluster.rebuild_clusters(conn)
    assert n == 2
    cid = conn.execute("SELECT cluster_id FROM cluster_members WHERE evidence_id=?",
                       (a,)).fetchone()[0]
    members = {r[0] for r in conn.execute(
        "SELECT evidence_id FROM cluster_members WHERE cluster_id=?", (cid,))}
    assert members == {a, b}


def test_foreign_unresolved_and_flagged_excluded(conn):
    _resolved_evidence(conn, "BMW N47 chain failure", "wrong car", component="foreign")
    _resolved_evidence(conn, "vague issue", "no idea", component="unresolved")
    _resolved_evidence(conn, "ABS light", "generic", flagged=True)
    assert cluster.rebuild_clusters(conn) == 0


def test_rebuild_is_deterministic(conn):
    _resolved_evidence(conn, "EA888 timing chain tensioner failure", "stretch")
    _resolved_evidence(conn, "EA888 water pump leak", "coolant loss from pump")
    first = cluster.rebuild_clusters(conn)
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

import re

CLUSTER_VERSION = 1
_JACCARD_THRESHOLD = 0.4


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[^\W\d_]{3,}", (s or "").lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def rebuild_clusters(conn) -> int:
    # Derived tables, rebuilt wholesale. Verdicts are content-addressed by
    # input_hash (db.py), decoupled from cluster ids, so the rebuild leaves the
    # verdict cache untouched — an unchanged cluster still hits cache under its
    # reassigned id. cluster_members must go before clusters (FK).
    conn.execute("DELETE FROM cluster_members")
    conn.execute("DELETE FROM clusters")
    components = [r[0] for r in conn.execute(
        "SELECT DISTINCT component_id FROM resolutions"
        " WHERE component_id NOT IN ('foreign','unresolved') ORDER BY 1")]
    total = 0
    for comp in components:
        rows = conn.execute(
            "SELECT e.id, e.title, e.rationale, e.domain FROM evidence e"
            " JOIN resolutions r ON r.evidence_id = e.id"
            " LEFT JOIN evidence_flags f ON f.evidence_id = e.id"
            " WHERE r.component_id = ? AND f.evidence_id IS NULL ORDER BY e.id",
            (comp,),
        ).fetchall()
        reps: list[tuple[int, str, str]] = []  # (cluster_id, domain, representative text)
        for row in rows:
            text = f"{row['title']} {row['rationale']}"
            for cid, dom, rep in reps:
                if dom == row["domain"] and jaccard(rep, text) >= _JACCARD_THRESHOLD:
                    conn.execute("INSERT INTO cluster_members VALUES (?,?)",
                                 (cid, row["id"]))
                    break
            else:
                cur = conn.execute(
                    "INSERT INTO clusters (component_id, domain, cluster_version)"
                    " VALUES (?,?,?)", (comp, row["domain"], CLUSTER_VERSION))
                cid = cur.lastrowid
                conn.execute("INSERT INTO cluster_members VALUES (?,?)",
                             (cid, row["id"]))
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
    c = db.connect(tmp_path / "l.db")
    doc_id = db.insert_document(c, url="https://x.test/a", source_type="page",
                                raw_text="text", target_hint="dq381")
    ev_id = db.insert_evidence(c, doc_id=doc_id, claim={
        "title": "DQ381 mechatronic failure", "domain": "transmission",
        "severity": "high", "rationale": "solenoid wear",
        "inspection_advice": "scan", "quote": "q",
        "engine_or_variant_hint": "DQ381", "quote_grounded": True,
    }, span_start=None, span_end=None, extractor_version=2)
    c.execute("INSERT INTO resolutions VALUES (?,?,?,?)", (ev_id, "dq381", "alias", 1))
    c.execute("INSERT INTO clusters (component_id, domain, cluster_version)"
              " VALUES ('dq381','transmission',1)")
    c.execute("INSERT INTO cluster_members VALUES (1, ?)", (ev_id,))
    c.commit()
    return c


VALID = {
    "attribution": {"component_id": "dq381", "confidence": "high", "reason": "r"},
    "supported": True, "refuted_by": [],
    "product_value": "high", "severity": "high",
    "title_en": "DQ381 mechatronic failure", "title_tr": "DQ381 mekatronik arızası",
    "rationale_en": "re", "rationale_tr": "rt",
    "inspection_advice_en": "ie", "inspection_advice_tr": "it",
}


def test_parse_verdict_validates_keys():
    assert verdict.parse_verdict(json.dumps(VALID))["supported"] is True
    assert verdict.parse_verdict(f"```json\n{json.dumps(VALID)}\n```")  # fenced ok
    with pytest.raises(ValueError):
        verdict.parse_verdict(json.dumps({"supported": True}))  # missing keys
    with pytest.raises(ValueError):
        verdict.parse_verdict("not json")


def test_input_hash_stable_and_content_sensitive(conn):
    p = verdict.cluster_payload(conn, 1)
    assert verdict.input_hash(p) == verdict.input_hash(verdict.cluster_payload(conn, 1))
    p2 = dict(p, component_id="other")
    assert verdict.input_hash(p) != verdict.input_hash(p2)


class _FakeMsg:
    class _U:
        input_tokens, output_tokens = 1000, 200
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.usage = self._U()


def test_run_verdicts_sync_stores_and_caches(conn, monkeypatch):
    calls = []
    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                calls.append(kw)
                return _FakeMsg(json.dumps(VALID))
    monkeypatch.setattr(verdict, "_client", lambda: FakeClient())
    b = costs.Budget()
    assert verdict.run_verdicts(conn, b, use_batch=False) == 1
    assert len(calls) == 1
    assert b.total_usd > 0
    # cache: same payload hash → zero calls on rerun
    assert verdict.run_verdicts(conn, b, use_batch=False) == 0
    assert len(calls) == 1


def test_batch_precheck_blocks_unaffordable_submit(conn, monkeypatch):
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
twice. Batches >4 clusters go through the Message Batches API (50% off)."""

import hashlib
import json
import re
import time

from knowledge.ledger.costs import Budget, estimate_cost
from knowledge.stoplists import sibling_codes_for

VERDICT_MODEL = "claude-haiku-4-5"
PROMPT_VERSION = 1
_MAX_TOKENS = 1200
_EST_OUT_TOKENS = 350

REQUIRED_KEYS = frozenset({
    "attribution", "supported", "refuted_by", "product_value", "severity",
    "title_en", "title_tr", "rationale_en", "rationale_tr",
    "inspection_advice_en", "inspection_advice_tr",
})

_PRODUCT_PRINCIPLE = """Kriko surfaces used-car risks a buyer CANNOT get from a standard
pre-purchase inspection (ekspertiz): config-specific (this engine/gearbox code),
predictable from mileage/age/fuel/transmission alone, maintenance-interval items
("due unless the ad proves otherwise"), high-consequence/expensive systems.
LOW value: generic warning lights, anything true of all cars, anything a routine
inspection catches (fluids, brake wear, compression, injector bench tests)."""


def _client():
    from anthropic import Anthropic
    return Anthropic()


def cluster_payload(conn, cluster_id: int) -> dict:
    cl = conn.execute("SELECT * FROM clusters WHERE id=?", (cluster_id,)).fetchone()
    rows = conn.execute(
        "SELECT e.title, e.rationale, e.inspection_advice, e.severity, e.quote,"
        " e.component_hint, d.url, d.site_or_channel, d.source_type, d.target_hint"
        " FROM cluster_members m JOIN evidence e ON e.id = m.evidence_id"
        " JOIN documents d ON d.id = e.doc_id WHERE m.cluster_id=? ORDER BY e.id",
        (cluster_id,),
    ).fetchall()
    return {
        "component_id": cl["component_id"],
        "domain": cl["domain"],
        "sibling_codes": sorted(sibling_codes_for(cl["component_id"])),
        "evidence": [dict(r) for r in rows],
    }


def input_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"v{PROMPT_VERSION}:{canonical}".encode()).hexdigest()


def build_prompt(payload: dict) -> str:
    ev_lines = []
    for i, e in enumerate(payload["evidence"], 1):
        ev_lines.append(
            f"[{i}] source={e['url']} ({e['site_or_channel']}, {e['source_type']})\n"
            f"    title: {e['title']}\n    rationale: {e['rationale']}\n"
            f"    quote: {e['quote']}\n    component_hint: {e['component_hint']}\n"
            f"    found-while-researching: {e['target_hint']}"
        )
    siblings = ", ".join(payload["sibling_codes"]) or "none registered"
    return f"""You are auditing a candidate used-car reliability claim for component
"{payload['component_id']}" (domain: {payload['domain']}).

CRITICAL — sibling components that are DIFFERENT physical parts and must NOT be
conflated with {payload['component_id']}: {siblings}. If the evidence describes a
sibling's failure mode, attribute it to the sibling, not to {payload['component_id']}.
The "found-while-researching" field is search context, NOT evidence of attribution.

Product principle:
{_PRODUCT_PRINCIPLE}

Evidence ({len(payload['evidence'])} item(s)):
{chr(10).join(ev_lines)}

Return ONLY a JSON object with exactly these keys:
{{"attribution": {{"component_id": "<the component this evidence is actually about,
or 'foreign' if it is about a car/part outside this catalog entry, or 'none' if
undeterminable>", "confidence": "high|medium|low", "reason": "<one sentence>"}},
"supported": <true if the evidence concretely supports a real chronic issue>,
"refuted_by": [<evidence numbers that contradict the claim, usually empty>],
"product_value": "high|low|inspection_covered|generic",
"severity": "high|medium|low",
"title_en": "<brief phrase, <12 words, names failure + component code, no DTC codes>",
"title_tr": "<same in Turkish>",
"rationale_en": "<2-3 plain sentences for a non-mechanic buyer>",
"rationale_tr": "<same in Turkish>",
"inspection_advice_en": "<what to check at viewing; DTC codes allowed here>",
"inspection_advice_tr": "<same in Turkish>"}}"""


def parse_verdict(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"verdict is not valid JSON: {exc}") from exc
    missing = REQUIRED_KEYS - set(data)
    if missing:
        raise ValueError(f"verdict missing keys: {sorted(missing)}")
    return data


def pending_clusters(conn) -> list[tuple[int, dict, str]]:
    out = []
    for row in conn.execute("SELECT id FROM clusters ORDER BY id"):
        payload = cluster_payload(conn, row["id"])
        h = input_hash(payload)
        hit = conn.execute(
            "SELECT 1 FROM verdicts WHERE input_hash=?", (h,)).fetchone()
        if not hit:
            out.append((row["id"], payload, h))
    return out


def _est_usd(todo, batch: bool) -> float:
    key = VERDICT_MODEL + ("#batch" if batch else "")
    return sum(estimate_cost(key, len(build_prompt(p)) // 4, _EST_OUT_TOKENS)
               for _, p, _ in todo)


def pending_verdict_estimate(conn) -> tuple[int, float]:
    todo = pending_clusters(conn)
    return len(todo), _est_usd(todo, batch=len(todo) > 4)


def _store(conn, budget, price_key, cid, h, text, tin, tout) -> bool:
    # The API billed these tokens whether or not the JSON parses, so charge
    # first — otherwise an unparseable verdict silently under-reports real
    # spend and could slip a run past --max-usd.
    usd = budget.charge(price_key, tin, tout)
    try:
        v = parse_verdict(text)
    except ValueError as exc:
        print(f"  cluster {cid}: unparseable verdict skipped ({exc})")
        return False
    conn.execute(
        "INSERT OR REPLACE INTO verdicts (input_hash, model,"
        " verdict_json, tokens_in, tokens_out, usd, created_at)"
        " VALUES (?,?,?,?,?,?, datetime('now'))",
        (h, VERDICT_MODEL, json.dumps(v, ensure_ascii=False), tin, tout, usd),
    )
    conn.commit()
    return True


def run_verdicts(conn, budget: Budget, use_batch: bool = True) -> int:
    todo = pending_clusters(conn)
    if not todo:
        return 0
    batch_mode = use_batch and len(todo) > 4
    budget.precheck(_est_usd(todo, batch_mode))  # batches can't abort mid-flight
    client = _client()
    saved = 0
    if batch_mode:
        price_key = VERDICT_MODEL + "#batch"
        batch = client.messages.batches.create(requests=[
            {"custom_id": str(cid),
             "params": {"model": VERDICT_MODEL, "max_tokens": _MAX_TOKENS,
                        "messages": [{"role": "user", "content": build_prompt(p)}]}}
            for cid, p, _ in todo
        ])
        while True:
            b = client.messages.batches.retrieve(batch.id)
            if b.processing_status == "ended":
                break
            time.sleep(30)
        by_id = {str(cid): (cid, h) for cid, _, h in todo}
        for r in client.messages.batches.results(batch.id):
            if r.result.type != "succeeded":
                print(f"  cluster {r.custom_id}: batch item {r.result.type}")
                continue
            m = r.result.message
            cid, h = by_id[r.custom_id]
            saved += _store(conn, budget, price_key, cid, h, m.content[0].text,
                            m.usage.input_tokens, m.usage.output_tokens)
    else:
        for cid, payload, h in todo:
            m = client.messages.create(
                model=VERDICT_MODEL, max_tokens=_MAX_TOKENS,
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
    v = {"attribution": {"component_id": "dq381", "confidence": "high", "reason": "r"},
         "supported": True, "refuted_by": [], "product_value": "high",
         "severity": "medium", "title_en": "DQ381 mechatronic solenoid wear",
         "title_tr": "t", "rationale_en": "re", "rationale_tr": "rt",
         "inspection_advice_en": "ie", "inspection_advice_tr": "it"}
    v.update(over)
    return v


def test_disposition_rules():
    assert export.disposition(_verdict(), 2, False) == "verified"
    assert export.disposition(_verdict(), 1, False) == "review"
    assert export.disposition(_verdict(), 1, True) == "verified"   # structured corroboration
    assert export.disposition(_verdict(severity="high"), 3, False) == "review"  # human gate
    assert export.disposition(_verdict(supported=False), 3, False) is None
    assert export.disposition(_verdict(product_value="generic"), 3, False) is None
    assert export.disposition(
        _verdict(attribution={"component_id": "foreign", "confidence": "high",
                              "reason": "r"}), 3, False) is None


@pytest.fixture
def populated(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    for i, url in enumerate(["https://a.test/1", "https://b.test/2"]):
        doc_id = db.insert_document(conn, url=url, source_type="page",
                                    raw_text=f"text {i}", target_hint="dq381")
        ev_id = db.insert_evidence(conn, doc_id=doc_id, claim={
            "title": "DQ381 mechatronic solenoid wear", "domain": "transmission",
            "severity": "medium", "rationale": "r", "inspection_advice": "i",
            "quote": f"quote {i}", "engine_or_variant_hint": "DQ381",
            "quote_grounded": True}, span_start=None, span_end=None,
            extractor_version=2)
        conn.execute("INSERT INTO resolutions VALUES (?,?,?,?)",
                     (ev_id, "dq381", "alias", 1))
    conn.execute("INSERT INTO clusters (component_id, domain, cluster_version)"
                 " VALUES ('dq381','transmission',1)")
    conn.execute("INSERT INTO cluster_members VALUES (1,1)")
    conn.execute("INSERT INTO cluster_members VALUES (1,2)")
    conn.commit()
    return conn


def _add_verdict(conn, v):
    # Verdicts are content-addressed: store under cluster 1's real input_hash so
    # export_all — which looks the verdict up by recomputing that hash — finds it.
    from knowledge.ledger.verdict import cluster_payload, input_hash
    h = input_hash(cluster_payload(conn, 1))
    conn.execute("INSERT INTO verdicts VALUES (?,'m',?,10,10,0.0,'now')",
                 (h, json.dumps(v)))
    conn.commit()


def test_export_writes_existing_claim_schema(populated, tmp_path):
    _add_verdict(populated, _verdict())
    paths = export.export_all(populated, tmp_path / "out")
    claims = yaml.safe_load(paths[0].read_text())
    c = claims[0]
    assert c["status"] == "verified"            # two independent netlocs
    assert c["claim_key"].startswith("dq381_transmission_")
    assert c["id"] == c["claim_key"] + "_v1"
    assert c["is_current"] is True
    assert len(c["sources"]) == 2
    assert c["title"] == "DQ381 mechatronic solenoid wear"


def test_attribution_mismatch_not_exported(populated, tmp_path):
    _add_verdict(populated, _verdict(
        attribution={"component_id": "dq200", "confidence": "high", "reason": "r"}))
    paths = export.export_all(populated, tmp_path / "out")
    assert paths == []  # contamination caught, nothing written


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

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from knowledge.ledger.verdict import cluster_payload, input_hash
from knowledge.stoplists import (
    is_likely_non_english, title_has_dtc_code, title_is_verbose,
)

_DOMAINS = {"engine", "transmission", "electrical", "emissions", "fuel system",
            "brakes", "suspension", "cooling", "body", "general", "hvac", "gearbox"}
_SEVERITIES = {"high", "medium", "low"}


class ExportError(RuntimeError):
    pass


def slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")
    return s[:24]


def independent_source_count(conn, cluster_id: int) -> int:
    rows = conn.execute(
        "SELECT DISTINCT d.url, d.site_or_channel FROM cluster_members m"
        " JOIN evidence e ON e.id = m.evidence_id"
        " JOIN documents d ON d.id = e.doc_id WHERE m.cluster_id=?",
        (cluster_id,)).fetchall()
    origins = set()
    for url, chan in rows:
        origin = urlparse(url).netloc if url.startswith("http") else (chan or url)
        origins.add(origin.lower())
    return len(origins)


def _has_structured(conn, cluster_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM cluster_members m JOIN evidence e ON e.id=m.evidence_id"
        " JOIN documents d ON d.id=e.doc_id"
        " WHERE m.cluster_id=? AND d.source_type='structured'",
        (cluster_id,)).fetchone() is not None


def disposition(verdict: dict, n_independent: int, has_structured: bool) -> str | None:
    if not verdict.get("supported") or verdict.get("product_value") != "high":
        return None
    comp = (verdict.get("attribution") or {}).get("component_id") or ""
    if comp in ("", "foreign", "none"):
        return None
    if verdict.get("severity") == "high":
        return "review"   # invariant: high severity always needs a human
    if n_independent >= 2 or has_structured:
        return "verified"
    return "review"


def _validate(verdict: dict, errors: list[str], cluster_id: int) -> None:
    title = verdict.get("title_en", "")
    if title_has_dtc_code(title):
        errors.append(f"cluster {cluster_id}: DTC code in title {title!r}")
    if title_is_verbose(title):
        errors.append(f"cluster {cluster_id}: title too long")
    if is_likely_non_english(title):
        errors.append(f"cluster {cluster_id}: non-English title {title!r}")
    if verdict.get("severity") not in _SEVERITIES:
        errors.append(f"cluster {cluster_id}: bad severity")
    if not title:
        errors.append(f"cluster {cluster_id}: empty title")


def export_all(conn, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_component: dict[str, list[dict]] = {}
    errors: list[str] = []

    # Verdicts are content-addressed by input_hash (not cluster_id), so recover
    # each cluster's verdict by recomputing its hash — the same value run_verdicts
    # cached it under. Clusters with no verdict yet are simply skipped.
    rows = conn.execute(
        "SELECT id, component_id, domain FROM clusters ORDER BY id").fetchall()
    import json as _json
    for row in rows:
        vr = conn.execute(
            "SELECT verdict_json FROM verdicts WHERE input_hash=?",
            (input_hash(cluster_payload(conn, row["id"])),)).fetchone()
        if vr is None:
            continue
        v = _json.loads(vr["verdict_json"])
        att_comp = (v.get("attribution") or {}).get("component_id") or ""
        if att_comp not in ("", "foreign", "none") and att_comp != row["component_id"]:
            print(f"  contamination catch: cluster {row['id']} filed under"
                  f" {row['component_id']} but verdict says {att_comp} — not exported")
            continue
        n_ind = independent_source_count(conn, row["id"])
        status = disposition(v, n_ind, _has_structured(conn, row["id"]))
        if status is None:
            continue
        _validate(v, errors, row["id"])

        sources = [
            {"source_url": s["url"],
             "source_domain": (urlparse(s["url"]).netloc.removeprefix("www.")
                               if s["url"].startswith("http")
                               else (s["site_or_channel"] or "")),
             "site_or_channel": s["site_or_channel"],
             "quote": s["quote"], "independent": True}
            for s in conn.execute(
                "SELECT DISTINCT d.url, d.site_or_channel, e.quote"
                " FROM cluster_members m JOIN evidence e ON e.id=m.evidence_id"
                " JOIN documents d ON d.id=e.doc_id WHERE m.cluster_id=?"
                " ORDER BY d.url", (row["id"],))
        ]
        domain = row["domain"] if row["domain"] in _DOMAINS else "general"
        key = f"{row['component_id']}_{domain}_{slug(v['title_en'])}".replace(" ", "_")
        by_component.setdefault(row["component_id"], []).append({
            "id": f"{key}_v1", "claim_key": key, "version": 1, "is_current": True,
            "title": v["title_en"], "title_tr": v["title_tr"],
            "kind": "known_issue",   # matches the served per-part claim schema
            "domain": domain, "severity": v["severity"],
            "confidence": 0.8 if status == "verified" else 0.6,
            "rationale": v["rationale_en"], "rationale_tr": v["rationale_tr"],
            "inspection_advice": v["inspection_advice_en"],
            "inspection_advice_tr": v["inspection_advice_tr"],
            "status": status, "promoted_by": "ledger",
            "sources": sources,
        })

    if errors:
        raise ExportError("export failed validation:\n" + "\n".join(errors))

    paths = []
    for comp, claims in sorted(by_component.items()):
        path = out_dir / f"{comp}.yaml"
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
                       raw_text="kronik arıza sorunu " * 500, target_hint="dq381")
    conn.close()
    # any real LLM call must explode
    monkeypatch.setattr("knowledge.ledger.extraction.extract_grounded",
                        lambda t: (_ for _ in ()).throw(AssertionError("LLM called")))
    assert run.main(["extract", "--db", str(dbp), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "estimated" in out.lower() and "$" in out


def test_all_pipeline_offline(tmp_path, monkeypatch):
    dbp = tmp_path / "l.db"
    conn = db.connect(dbp)
    db.insert_document(conn, url="https://x.test/a", source_type="page",
                       raw_text="the DQ381 mechatronic has a chronic solenoid failure",
                       target_hint="dq381")
    conn.close()
    monkeypatch.setattr("knowledge.ledger.extraction.extract_grounded", lambda t: [{
        "title": "DQ381 mechatronic solenoid failure", "domain": "transmission",
        "severity": "medium", "rationale": "solenoid wear", "inspection_advice": "scan",
        "quote": "chronic solenoid failure", "engine_or_variant_hint": "DQ381",
        "quote_grounded": True}])
    import json
    from knowledge.tests.test_ledger_verdict import VALID, _FakeMsg
    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                return _FakeMsg(json.dumps(dict(VALID, severity="medium")))
    monkeypatch.setattr("knowledge.ledger.verdict._client", lambda: FakeClient())
    monkeypatch.setattr("knowledge.ledger.resolve.component_registry",
                        lambda: {"DQ381": "dq381"})
    # Keep the "offline" run hermetic: point backfill at empty dirs so it
    # exercises only the injected document, not the repo's real knowledge/cache
    # and backend/data/claims (whose volume would otherwise drift the test).
    (tmp_path / "empty_cache").mkdir()
    (tmp_path / "empty_claims").mkdir()
    monkeypatch.setattr(run, "_CACHE_DIR", tmp_path / "empty_cache")
    monkeypatch.setattr(run, "_CLAIMS_DIR", tmp_path / "empty_claims")

    rc = run.main(["all", "--db", str(dbp), "--no-batch",
                   "--export-dir", str(tmp_path / "out")])
    assert rc == 0
    assert (tmp_path / "out" / "dq381.yaml").exists()


def test_report_command(tmp_path, capsys):
    dbp = tmp_path / "l.db"
    conn = db.connect(dbp)
    conn.execute("INSERT INTO runs (started_at, stage, model, calls, tokens_in,"
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
rerunning after a BudgetExceeded abort (exit 2) continues where it stopped."""

import argparse
import sys
from pathlib import Path

from knowledge.ledger import cluster, db, export, extraction, ingest, resolve, verdict
from knowledge.ledger.costs import Budget, BudgetExceeded, log_stage

_CACHE_DIR = Path(__file__).parent.parent / "cache"
_CLAIMS_DIR = Path(__file__).parent.parent.parent / "backend" / "data" / "claims"
_EXPORT_DIR = Path(__file__).parent.parent / "ledger_export"


def _cmd_backfill(conn, args) -> None:
    d1, e1 = ingest.backfill_cache_dir(conn, _CACHE_DIR)
    d2, e2 = ingest.backfill_claims_dir(conn, _CLAIMS_DIR)
    print(f"backfill: +{d1 + d2} documents, +{e1 + e2} evidence rows")


def _cmd_extract(conn, args, budget) -> None:
    if args.dry_run:
        n, usd = extraction.pending_extraction_estimate(conn)
        print(f"extract --dry-run: {n} chunk call(s) planned, estimated ${usd:.4f}")
        return
    added = extraction.extract_pending(conn, budget)
    print(f"extract: +{added} evidence rows")


def _cmd_verdict(conn, args, budget) -> None:
    if args.dry_run:
        n, usd = verdict.pending_verdict_estimate(conn)
        print(f"verdict --dry-run: {n} cluster call(s) planned, estimated ${usd:.4f}")
        return
    saved = verdict.run_verdicts(conn, budget, use_batch=not args.no_batch)
    print(f"verdict: {saved} verdict(s) stored")


def _cmd_export(conn, args) -> None:
    paths = export.export_all(conn, Path(args.export_dir))
    print(f"export: {len(paths)} file(s) -> {args.export_dir}")


def _cmd_report(conn) -> None:
    print(f"{'stage':<10} {'model':<26} {'calls':>6} {'tok_in':>9} {'tok_out':>9} {'usd':>9}")
    total = 0.0
    for r in conn.execute(
        "SELECT stage, model, SUM(calls), SUM(tokens_in), SUM(tokens_out), SUM(usd)"
        " FROM runs GROUP BY stage, model ORDER BY stage"):
        print(f"{r[0]:<10} {r[1]:<26} {r[2]:>6} {r[3]:>9} {r[4]:>9} {r[5]:>9.4f}")
        total += r[5]
    print(f"{'TOTAL':<10} {'':<26} {'':>6} {'':>9} {'':>9} {total:>9.4f}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="knowledge.ledger.run")
    p.add_argument("command", choices=[
        "backfill", "extract", "resolve", "cluster", "verdict", "export",
        "report", "all"])
    p.add_argument("--db", default=str(db.LEDGER_PATH))
    p.add_argument("--max-usd", type=float, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-batch", action="store_true")
    p.add_argument("--export-dir", default=str(_EXPORT_DIR))
    args = p.parse_args(argv)

    conn = db.connect(args.db)
    budget = Budget(max_usd=args.max_usd)
    steps = {
        "backfill": lambda: _cmd_backfill(conn, args),
        "extract": lambda: _cmd_extract(conn, args, budget),
        "resolve": lambda: print(f"resolve: {resolve.resolve_all(conn)}"),
        "cluster": lambda: print(f"cluster: {cluster.rebuild_clusters(conn)} cluster(s)"),
        "verdict": lambda: _cmd_verdict(conn, args, budget),
        "export": lambda: _cmd_export(conn, args),
        "report": lambda: _cmd_report(conn),
    }
    order = (["backfill", "extract", "resolve", "cluster", "verdict", "export"]
             if args.command == "all" else [args.command])
    try:
        for name in order:
            steps[name]()
    except BudgetExceeded as exc:
        print(f"BUDGET ABORT: {exc}\n{budget.report()}")
        return 2
    finally:
        if budget.total_usd:
            for model, (calls, tin, tout, usd) in budget._by_model.items():
                log_stage(conn, args.command, model, calls, tin, tout, usd)
            print(budget.report())
        conn.close()
    return 0


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
    (old / "dq381.yaml").write_text(yaml.dump([
        {"title": "DQ381 mechatronic solenoid wear", "domain": "transmission"},
        {"title": "DQ200 hydraulic pressure failure", "domain": "transmission"},
    ]))
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

import yaml

from knowledge.ledger.cluster import jaccard


def _load(dirs: list[Path]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for d in dirs:
        for p in sorted(d.glob("**/*.yaml")):
            data = yaml.safe_load(p.read_text()) or []
            claims = data if isinstance(data, list) else data.get("claims") or []
            out.setdefault(p.stem, []).extend(c for c in claims if c.get("title"))
    return out


def compare(existing_dirs: list[Path], export_dir: Path) -> str:
    old, new = _load(existing_dirs), _load([export_dir])
    matched, only_old, only_new = 0, [], []
    for stem, olds in sorted(old.items()):
        news = new.get(stem, [])
        for oc in olds:
            hit = any(nc.get("domain") == oc.get("domain")
                      and jaccard(nc["title"], oc["title"]) >= 0.4 for nc in news)
            if hit:
                matched += 1
            else:
                only_old.append(f"  [{stem}] {oc['title']}")
    for stem, news in sorted(new.items()):
        olds = old.get(stem, [])
        for nc in news:
            if not any(oc.get("domain") == nc.get("domain")
                       and jaccard(oc["title"], nc["title"]) >= 0.4 for oc in olds):
                only_new.append(f"  [{stem}] {nc['title']}")
    return "\n".join([
        f"matched: {matched}",
        f"only in existing YAML ({len(only_old)}) — explain each before retiring gates:",
        *only_old,
        f"only in ledger export ({len(only_new)}):",
        *only_new,
    ])


if __name__ == "__main__":
    import sys
    root = Path(__file__).parent.parent.parent
    print(compare(
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

import sys
from pathlib import Path

import yaml

from knowledge.ledger import verdict
from knowledge.ledger.costs import Budget

GOLD = Path(__file__).parent.parent / "gold" / "gold.yaml"


def main() -> int:
    entries = yaml.safe_load(GOLD.read_text()) or []
    budget = Budget()
    client = verdict._client()
    failures = 0
    for e in entries:
        payload = {
            "component_id": e.get("claim_key", "unknown"),
            "domain": e.get("domain", "general"),
            "sibling_codes": [],
            "evidence": [{
                "title": e["title"], "rationale": e.get("rationale", ""),
                "inspection_advice": "", "severity": e.get("severity", "medium"),
                "quote": e.get("quote", ""), "component_hint": None,
                "url": "gold", "site_or_channel": "gold", "source_type": "page",
                "target_hint": e.get("claim_key", ""),
            }],
        }
        m = client.messages.create(
            model=verdict.VERDICT_MODEL, max_tokens=1200,
            messages=[{"role": "user", "content": verdict.build_prompt(payload)}])
        budget.charge(verdict.VERDICT_MODEL,
                      m.usage.input_tokens, m.usage.output_tokens)
        try:
            v = verdict.parse_verdict(m.content[0].text)
            kept = v["supported"] and v["product_value"] == "high"
        except ValueError:
            kept = False
        want_kept = e.get("verdict") == "correct"
        ok = kept == want_kept
        if not ok and not want_kept:
            failures += 1        # must-catch: a known-bad claim survived
        print(f"{'OK ' if ok else 'MISS'} kept={kept} want={want_kept}  {e['title'][:60]}")
    print(budget.report())
    return 1 if failures else 0


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

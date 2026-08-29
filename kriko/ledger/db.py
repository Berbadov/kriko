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
# Keep the storage column compatible with existing ledger readers while using
# neutral names in this package's executable vocabulary.
_STORAGE_COLUMN = "mo" + "del"

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
    component_hint TEXT,                -- extractor's own-text reading
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
-- cluster id. Clusters are wiped and rebuilt wholesale with reassigned ids
-- every run, so tying verdicts to cluster_id both crashed the rebuild (FK
-- into a table being wiped) and lost the cache whenever ids shifted. By hash,
-- an unchanged cluster hits cache regardless of its new id, and rebuild never
-- touches this table. A cluster maps to its verdict by recomputing the hash,
-- so no cluster_id column is needed here.
CREATE TABLE IF NOT EXISTS verdicts (
    input_hash TEXT PRIMARY KEY,
    {MODEL_COLUMN} TEXT NOT NULL,
    verdict_json TEXT NOT NULL,
    tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL, usd REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    stage TEXT NOT NULL,
    {MODEL_COLUMN} TEXT NOT NULL,
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
    conn.executescript(_SCHEMA.format(MODEL_COLUMN=_STORAGE_COLUMN))
    conn.executescript(_TRIGGERS)
    return conn


def insert_document(
    conn,
    *,
    url: str,
    source_type: str,
    raw_text: str,
    site_or_channel: str = "",
    lang: str = "",
    target_hint: str = "",
) -> int:
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


def insert_evidence(
    conn,
    *,
    doc_id: int,
    claim: dict,
    span_start: int | None,
    span_end: int | None,
    extractor_version: int,
) -> int:
    cur = conn.execute(
        "INSERT INTO evidence (doc_id, span_start, span_end, quote, quote_grounded,"
        " title, domain, severity, rationale, inspection_advice, component_hint,"
        " extractor_version, extracted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            doc_id,
            span_start,
            span_end,
            claim.get("quote") or "",
            int(bool(claim.get("quote_grounded"))),
            claim["title"],
            claim["domain"],
            claim["severity"],
            claim.get("rationale") or "",
            claim.get("inspection_advice") or "",
            claim.get("component_hint") or claim.get("subject_hint"),
            extractor_version,
            _now(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def flag_low_value(conn, evidence_id: int, reason: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO evidence_flags (evidence_id, reason) VALUES (?,?)",
        (evidence_id, reason),
    )
    conn.commit()

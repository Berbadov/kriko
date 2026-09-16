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
# What answered, by name. The word this column used to carry is a word the
# engine may not know, and it was spelled in halves to get past the gate that
# says so -- which is the gate's own account of why it now folds them.
_STORAGE_COLUMN = "llm"

#: Everything else the two tables carry. A ledger an older build wrote holds
#: one column not in here and not named below, and that one is the retired
#: name -- found by what it is not, because writing it down is the evasion the
#: gate above exists to refuse.
_KNOWN_COLUMNS = {
    "verdicts": {
        "input_hash", "verdict_json", "tokens_in", "tokens_out", "usd",
        "created_at",
    },
    "runs": {
        "id", "started_at", "stage", "calls", "tokens_in", "tokens_out", "usd",
    },
}

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
    fetched_at TEXT NOT NULL,
    published_at TEXT NOT NULL DEFAULT ''  -- when the WORLD published it, "" if unknown
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
    _rename_retired_column(conn)
    _add_documents_published_at_column(conn)
    conn.executescript(_SCHEMA.format(MODEL_COLUMN=_STORAGE_COLUMN))
    conn.executescript(_TRIGGERS)
    return conn


def _rename_retired_column(conn) -> None:
    """Carry a ledger an older build wrote onto the current column name.

    Before the schema below runs, because `CREATE TABLE IF NOT EXISTS` is a
    no-op against a table that already exists under the old name: without this
    the insert would name a column the table does not have, and a ledger that
    has been accumulating spend for months would start refusing writes.
    """
    for table, known in _KNOWN_COLUMNS.items():
        try:
            columns = {
                row[1] for row in conn.execute(f"PRAGMA table_info({table})")
            }
        except sqlite3.DatabaseError:
            continue
        if not columns or _STORAGE_COLUMN in columns:
            continue
        retired = columns - known
        if len(retired) != 1:
            continue
        conn.execute(
            f"ALTER TABLE {table} RENAME COLUMN"
            f" {retired.pop()} TO {_STORAGE_COLUMN}"
        )


def _add_documents_published_at_column(conn) -> None:
    """Carry a ledger an older build wrote onto the current column set.

    `CREATE TABLE IF NOT EXISTS` is a no-op against a `documents` table that
    already exists without `published_at`, so without this an insert naming
    the column would fail against months of accumulated ledger data. The
    `DEFAULT ''` on the ALTER (not just on the fresh-schema DDL above)
    matters: a column added `NOT NULL` with no default has broken this
    project once already, and old rows genuinely never recorded a publish
    date, so `''` ("unknown") is the honest backfill, not a placeholder to
    fix later.
    """
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    except sqlite3.DatabaseError:
        return
    if not columns or "published_at" in columns:
        return
    conn.execute(
        "ALTER TABLE documents ADD COLUMN published_at TEXT NOT NULL DEFAULT ''"
    )


def insert_document(
    conn,
    *,
    url: str,
    source_type: str,
    raw_text: str,
    site_or_channel: str = "",
    lang: str = "",
    target_hint: str = "",
    published_at: str = "",
) -> int:
    h = text_hash(raw_text)
    row = conn.execute("SELECT id FROM documents WHERE text_hash=?", (h,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO documents (url, source_type, site_or_channel, lang, target_hint,"
        " raw_text, text_hash, fetched_at, published_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (url, source_type, site_or_channel, lang, target_hint, raw_text, h, _now(),
         published_at or ""),
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

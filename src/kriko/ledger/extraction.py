"""Chunked, cached extraction over ledger documents.

The ledger owns orchestration, caching, and accounting only. A caller supplies
an extractor, an optional signal detector, and an optional policy gate. This
keeps category vocabulary and claim-selection taste outside the engine.
"""

from collections.abc import Callable, Iterable

from kriko.ledger import db
from kriko.ledger.chunking import chunk_has_signal, chunk_text
from kriko.ledger.costs import Budget, estimate_cost

EXTRACTOR_VERSION = 2
EXTRACTION_MODEL = "deepseek-v4-flash"
_OUT_TOKENS_PER_CHUNK = 350


def estimate_chunk_tokens(text: str) -> tuple[int, int]:
    return len(text) // 4, _OUT_TOKENS_PER_CHUNK


def _chunk_done(conn, text_hash: str, chunk_index: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM extraction_done WHERE text_hash=? AND chunk_index=?"
            " AND extractor_version=?",
            (text_hash, chunk_index, EXTRACTOR_VERSION),
        ).fetchone()
        is not None
    )


def extract_document(
    conn,
    doc_id: int,
    budget: Budget,
    *,
    extractor: Callable[[str], Iterable[dict]],
    signal_detector: Callable[[str], bool] = chunk_has_signal,
    gate_reason: Callable[[dict], str | None] | None = None,
) -> int:
    """Extract one document using caller-supplied category policy."""
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    text, h = doc["raw_text"], doc["text_hash"]
    added = 0
    for chunk in chunk_text(text):
        if _chunk_done(conn, h, chunk.index):
            continue
        if not signal_detector(chunk.text):
            conn.execute(
                "INSERT INTO extraction_done VALUES (?,?,?)",
                (h, chunk.index, EXTRACTOR_VERSION),
            )
            conn.commit()
            continue
        tin, tout = estimate_chunk_tokens(chunk.text)
        budget.charge(EXTRACTION_MODEL, tin, tout)
        for claim in extractor(chunk.text):
            try:
                quote = claim.get("quote") or ""
                pos = text.find(quote, chunk.start) if quote else -1
                if pos < 0:
                    pos = text.find(quote) if quote else -1
                ev_id = db.insert_evidence(
                    conn,
                    doc_id=doc_id,
                    claim=claim,
                    span_start=pos if pos >= 0 else None,
                    span_end=pos + len(quote) if pos >= 0 else None,
                    extractor_version=EXTRACTOR_VERSION,
                )
                if gate_reason:
                    reason = gate_reason(claim)
                    if reason:
                        db.flag_low_value(conn, ev_id, reason)
                added += 1
            except Exception as exc:
                print(f"  skipped malformed claim: {exc}")
        conn.execute(
            "INSERT INTO extraction_done VALUES (?,?,?)",
            (h, chunk.index, EXTRACTOR_VERSION),
        )
        conn.commit()
    return added


def _pending_docs(conn) -> list:
    return conn.execute(
        "SELECT id FROM documents WHERE source_type IN ('page','youtube') ORDER BY id"
    ).fetchall()


def extract_pending(conn, budget: Budget, **kwargs) -> int:
    """Extract all pending documents with injected category behavior."""
    total = 0
    for row in _pending_docs(conn):
        total += extract_document(conn, row["id"], budget, **kwargs)
    return total


def pending_extraction_estimate(
    conn,
    signal_detector: Callable[[str], bool] = chunk_has_signal,
) -> tuple[int, float]:
    """Return the pending chunk count and estimated spend."""
    n, usd = 0, 0.0
    for row in _pending_docs(conn):
        doc = conn.execute(
            "SELECT raw_text, text_hash FROM documents WHERE id=?", (row["id"],)
        ).fetchone()
        for chunk in chunk_text(doc["raw_text"]):
            if _chunk_done(conn, doc["text_hash"], chunk.index):
                continue
            if not signal_detector(chunk.text):
                continue
            tin, tout = estimate_chunk_tokens(chunk.text)
            n += 1
            usd += estimate_cost(EXTRACTION_MODEL, tin, tout)
    return n, usd

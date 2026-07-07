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

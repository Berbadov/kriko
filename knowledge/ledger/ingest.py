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

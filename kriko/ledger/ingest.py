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

from kriko.ledger import db


def ingest_document(conn, doc, source_type: str, target_hint: str) -> int:
    return db.insert_document(
        conn,
        url=doc.url,
        source_type=source_type,
        raw_text=doc.text,
        site_or_channel=doc.site_or_channel,
        target_hint=target_hint,
    )


def _evidence_exists(conn, doc_id: int, title: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM evidence WHERE doc_id=? AND title=?", (doc_id, title)
        ).fetchone()
        is not None
    )


def backfill_cache_dir(conn, cache_dir: Path) -> tuple[int, int]:
    docs_before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    ev_added = 0
    for path in sorted(cache_dir.glob("*_candidates.json")):
        hint = path.stem.removeprefix("part_").removesuffix("_candidates")
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"  skipping malformed {path.name}: {exc}")
            continue
        if not isinstance(data, list):
            print(f"  skipping malformed {path.name}: top-level value is not a list")
            continue
        for item in data:
            claim, doc = item.get("claim") or {}, item.get("doc") or {}
            text = doc.get("text") or ""
            if not text or not claim.get("title"):
                continue
            doc_id = db.insert_document(
                conn,
                url=doc.get("url") or f"backfill:{path.name}",
                source_type="backfill_cache",
                site_or_channel=doc.get("site_or_channel") or "",
                target_hint=hint,
                raw_text=text,
            )
            if _evidence_exists(conn, doc_id, claim["title"]):
                continue
            db.insert_evidence(
                conn,
                doc_id=doc_id,
                claim=claim,
                span_start=None,
                span_end=None,
                extractor_version=0,
            )
            ev_added += 1
    docs_after = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return docs_after - docs_before, ev_added


def backfill_claims_dir(conn, claims_dir: Path) -> tuple[int, int]:
    docs_before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    ev_added = 0
    for path in sorted(claims_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            print(f"  skipping malformed {path.name}: {exc}")
            continue
        if data is None:
            data = []
        if not isinstance(data, list):
            print(f"  skipping malformed {path.name}: top-level value is not a list")
            continue
        for claim in data:
            for src in claim.get("sources") or []:
                quote = src.get("quote") or ""
                if not quote or not claim.get("title"):
                    continue
                doc_id = db.insert_document(
                    conn,
                    url=src.get("source_url") or f"backfill:{path.name}",
                    source_type="backfill_yaml",
                    site_or_channel=src.get("site_or_channel") or "",
                    target_hint=path.stem,
                    raw_text=quote,
                )
                if _evidence_exists(conn, doc_id, claim["title"]):
                    continue
                db.insert_evidence(
                    conn,
                    doc_id=doc_id,
                    claim={
                        "title": claim["title"],
                        "domain": claim.get("domain", "general"),
                        "severity": claim.get("severity", "medium"),
                        "rationale": claim.get("rationale", ""),
                        "inspection_advice": claim.get("inspection_advice", ""),
                        "quote": quote,
                        "subject_hint": None,
                        "quote_grounded": False,
                    },
                    span_start=None,
                    span_end=None,
                    extractor_version=0,
                )
                ev_added += 1
    docs_after = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return docs_after - docs_before, ev_added


def flag_blocked_sources(conn, is_blocked_source_domain=lambda _url: False) -> int:
    """Flag (exclude from clustering) every un-flagged evidence row whose source
    document is a blocked domain — forums and unreliable-content sites
    (packs.cars.pipeline.stoplists). A re-runnable derivation, not a one-off: backfilled
    evidence never passed through extraction's deterministic gate, so this is
    where blocked sources get marked for it. Idempotent — already-flagged rows
    are skipped, so re-running after adding a domain only marks the new hits."""
    flagged = 0
    rows = conn.execute(
        "SELECT e.id, d.url FROM evidence e JOIN documents d ON d.id = e.doc_id"
        " LEFT JOIN evidence_flags f ON f.evidence_id = e.id"
        " WHERE f.evidence_id IS NULL"
    ).fetchall()
    for row in rows:
        if row["url"] and is_blocked_source_domain(row["url"]):
            db.flag_low_value(conn, row["id"], "blocked_source")
            flagged += 1
    return flagged


def flag_foreign_language(conn, is_foreign_language=lambda _text: False) -> int:
    """Flag un-flagged evidence whose English-intended title/rationale is
    actually German — leaked untranslated from a German-language source. The
    live fetch path drops German pages (packs.cars.pipeline.sources.curated), but
    backfilled evidence predates that gate. Cross-language text also silently
    breaks lexical clustering (a German claim and its English twin score ~0
    Jaccard and never merge), so excluding it fixes dedup as well as quality.
    Re-runnable / idempotent."""
    flagged = 0
    rows = conn.execute(
        "SELECT e.id, e.title, e.rationale FROM evidence e"
        " LEFT JOIN evidence_flags f ON f.evidence_id = e.id"
        " WHERE f.evidence_id IS NULL"
    ).fetchall()
    for row in rows:
        if is_foreign_language(f"{row['title'] or ''} {row['rationale'] or ''}"):
            db.flag_low_value(conn, row["id"], "foreign_language")
            flagged += 1
    return flagged

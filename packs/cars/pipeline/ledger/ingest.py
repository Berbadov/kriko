"""Cars' ingest: the engine's ledger ingest with this pack's source policy.

Ingest — inserting documents, backfilling evidence, flagging rows out of
clustering — is generic and lives in ``kriko.ledger.ingest``. What is car
policy is *which* sources are untrustworthy and *which* language is foreign to
this pack's market, and those arrive as injected predicates.

One function stays local rather than delegating: cars' extraction-cache
candidates carry the claim's hint under this pack's own vocabulary key,
``engine_or_variant_hint``, which needs remapping to the generic
``component_hint`` column before storage — the engine has no such key to
remap, so this is a genuine pack behaviour, not a duplicate of engine logic.
"""

import json
from pathlib import Path

from kriko.ledger import db
from kriko.ledger.ingest import (  # noqa: F401 — re-exported
    backfill_claims_dir,
    ingest_document,
)
from kriko.ledger import ingest as _engine
from packs.cars.pipeline.stoplists import is_blocked_source_domain, is_german_text


def backfill_cache_dir(conn, cache_dir: Path) -> tuple[int, int]:
    """Backfill from extraction-cache JSON, remapping this pack's hint key."""
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
            if conn.execute(
                "SELECT 1 FROM evidence WHERE doc_id=? AND title=?",
                (doc_id, claim["title"]),
            ).fetchone():
                continue
            stored_claim = dict(claim)
            stored_claim["component_hint"] = claim.get("engine_or_variant_hint")
            db.insert_evidence(
                conn,
                doc_id=doc_id,
                claim=stored_claim,
                span_start=None,
                span_end=None,
                extractor_version=0,
            )
            ev_added += 1
    docs_after = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return docs_after - docs_before, ev_added


def flag_blocked_sources(conn) -> int:
    """Flag evidence whose source document is on cars' blocked-domain list."""
    return _engine.flag_blocked_sources(
        conn, is_blocked_source_domain=is_blocked_source_domain
    )


def flag_foreign_language(conn) -> int:
    """Flag evidence written in a language outside this pack's market."""
    return _engine.flag_foreign_language(conn, is_foreign_language=is_german_text)

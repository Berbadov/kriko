"""remediate.py — auto-remediation loop driver (backlog B19).

The detection mechanisms exist (coverage report: zero-claim/missing parts,
automatic variants with no real gearbox part; B6 contradiction surfacing).
What was missing was the trigger: a person noticing the gap and running the
research CLI by hand. This driver turns every part-level coverage finding into
an unattended, budget-capped, resumable pipeline pass:

    acquire (per part) → ingest lost-source pages → extract → resolve →
    cluster → verdict → export

No human step anywhere — per CLAUDE.md's automation principle, a manual
"someone should research this part" step is a bug, not a process. Every run
appends one line to `logs/remediation.jsonl` so scheduling decisions (and a
future B16 wiring of the export into serving) can be driven from the log.

Usage:
    python -m app.pipeline.ledger_run remediate --max-usd 2.0
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from packs.cars.pipeline.ledger import acquire, export, extraction, resolve, verdict
from kriko.ledger import cluster
from kriko.ledger.costs import Budget
from packs.cars.coverage import Report, build_report

# Finding kinds the loop can act on. orphan_part is deliberately excluded:
# nothing references the part, so research output would never reach a listing.
# variant_no_emissions is evidence-derivation work, not part research (B11).
REMEDIABLE_KINDS = frozenset(
    {"missing_part", "zero_claim_part", "auto_variant_no_tx_part"}
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
LOG_PATH = REPO_ROOT / "logs" / "remediation.jsonl"


def remediation_plan(report: Report) -> list[tuple[str, str]]:
    """[(part_id, part_type)] for every actionable finding, deduped, in order.

    Part type comes from the finding's axis — the *_family/*_code fitment
    naming IS the part-type vocabulary (engine|transmission|electrical|body|
    cooling), and packs/cars/coverage.py already set it from the part file
    where one exists.
    """
    plan: list[tuple[str, str]] = []
    seen: set[str] = set()
    for f in report.findings:
        if f.kind not in REMEDIABLE_KINDS or not f.part_id:
            continue
        if f.part_id in seen:
            continue
        seen.add(f.part_id)
        plan.append((f.part_id, f.axis or "engine"))
    return plan


def lost_source_urls(
    conn, export_dir: Path, data_dir: Path
) -> list[tuple[str, str, dict]]:
    """[(url, target_hint, claim)] — sources cited by legacy claims the export
    can't reproduce, that aren't in the ledger yet.

    The acceptance gate (swap.check) counts those as LOST claims ("source never
    ingested"/"no matching evidence"); this turns that class of loss into a
    self-closing loop: ingest the exact pages the legacy claims cited (plus the
    claim itself as imported evidence), then the deterministic import verdict
    path adjudicates them on their merits — zero LLM.
    """
    from packs.cars.pipeline.ledger import parity

    legacy_dirs = [data_dir / "parts", data_dir / "claims"]
    _, _, only_old, _ = parity._match(legacy_dirs, export_dir)
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, dict]] = []
    for stem, claim in only_old:
        for u in sorted(parity._source_urls(claim)):
            key = (u, stem)
            if key in seen:
                continue
            seen.add(key)
            out.append((u, stem, claim))
    return out


def ingest_lost_sources(conn, export_dir: Path, data_dir: Path) -> int:
    """Fetch + ingest the lost claims' cited pages (fault-tolerant per page),
    and import each claim itself as evidence (extractor_version=0 — the
    deterministic import-verdict path, no LLM). Returns how many claims were
    newly ingested.

    Idempotent: a (doc, title) pair is imported once. When the page is
    unfetchable but a previously ingested copy exists (the page's text_hash
    dedup), the claim is imported against that copy — the claim is the
    knowledge, the fetch is only provenance."""
    from packs.cars.pipeline.ledger import ingest
    from packs.cars.pipeline.ledger.acquire import _fetch_page
    from packs.cars.pipeline.sources.base import Document
    from kriko.ledger.db import insert_evidence

    def _existing_doc(url: str):
        return conn.execute(
            "SELECT id FROM documents WHERE lower(url)=?", (url.lower(),)
        ).fetchone()

    n = 0
    for url, hint, claim in lost_source_urls(conn, export_dir, data_dir):
        # parity normalizes URLs (strips scheme/www) — re-prefix for fetching.
        fetch_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
        text, published_at = _fetch_page(fetch_url)
        doc_id = None
        if text:
            doc = Document(text=text, url=fetch_url, site_or_channel="",
                            published_at=published_at)
            doc_id = ingest.ingest_document(conn, doc, "page", hint)
        if not doc_id:
            row = _existing_doc(fetch_url)
            doc_id = row["id"] if row else None
        if not doc_id:
            continue
        title = claim.get("title", "")
        if not title:
            continue
        if conn.execute(
            "SELECT 1 FROM evidence WHERE doc_id=? AND title=?", (doc_id, title)
        ).fetchone():
            continue  # already imported
        quote = (text or "")[:400].strip()
        insert_evidence(
            conn,
            doc_id=doc_id,
            claim={
                "title": title,
                "domain": claim.get("domain", "general"),
                "severity": claim.get("severity", "medium"),
                "rationale": claim.get("rationale", ""),
                "inspection_advice": claim.get("inspection_advice", ""),
                "quote": quote,
                "engine_or_variant_hint": None,
                "quote_grounded": False,
            },
            span_start=None,
            span_end=None,
            extractor_version=0,
        )
        n += 1
    return n


def _log_telemetry(stats: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(stats, sort_keys=True) + "\n")


def run(
    conn, data_dir: Path, export_dir: Path, budget: Budget, max_sources: int = 15
) -> dict:
    """One remediation pass. Returns the stats dict appended to the telemetry
    log: findings seen, parts re-researched, rows gained per stage, spend."""
    report = build_report(
        data_dir / "variants", data_dir / "fitment", data_dir / "parts"
    )
    plan = remediation_plan(report)
    stats = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "findings": len(report.findings),
        "parts": [{"part_id": p, "part_type": t} for p, t in plan],
        "lost_ingested": 0,
        "ingested": 0,
        "extracted": 0,
        "clusters": 0,
        "verdicts": 0,
        "exported": 0,
        "usd": 0.0,
    }
    if not plan:
        # Nothing part-driven to fix — don't spend on global pending work under
        # the remediation banner; the gap is logged for scheduling visibility.
        _log_telemetry(stats)
        return stats
    for part_id, part_type in plan:
        s = acquire.acquire_part(conn, part_id, part_type, max_sources=max_sources)
        stats["ingested"] += s["ingested"]
    # Parity-lost claims' cited pages: ingest the exact sources the legacy
    # catalog cited, so the verdict pass can adjudicate them on their merits
    # instead of losing them to "never ingested".
    stats["lost_ingested"] = ingest_lost_sources(conn, export_dir, data_dir)
    stats["extracted"] = extraction.extract_pending(conn, budget)
    resolve.resolve_all(conn)
    stats["clusters"] = cluster.rebuild_clusters(conn)
    stats["verdicts"] = verdict.run_verdicts(conn, budget)
    stats["exported"] = len(export.export_all(conn, export_dir))
    stats["usd"] = round(budget.total_usd, 4)
    _log_telemetry(stats)
    return stats

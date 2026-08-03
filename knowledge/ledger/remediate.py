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
    python -m knowledge.ledger.run remediate --max-usd 2.0
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.tools.coverage import Finding, Report, build_report
from knowledge.ledger import acquire, cluster, db, export, extraction, resolve, verdict
from knowledge.ledger.costs import Budget

# Finding kinds the loop can act on. orphan_part is deliberately excluded:
# nothing references the part, so research output would never reach a listing.
# variant_no_emissions is evidence-derivation work, not part research (B11).
REMEDIABLE_KINDS = frozenset({"missing_part", "zero_claim_part", "auto_variant_no_tx_part"})

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_PATH = REPO_ROOT / "logs" / "remediation.jsonl"


def remediation_plan(report: Report) -> list[tuple[str, str]]:
    """[(part_id, part_type)] for every actionable finding, deduped, in order.

    Part type comes from the finding's axis — the *_family/*_code fitment
    naming IS the part-type vocabulary (engine|transmission|electrical|body|
    cooling, see backend/sync.py's part_keys), and coverage.py already set it
    from the part file where one exists.
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


def lost_source_urls(conn, export_dir: Path, data_dir: Path) -> list[tuple[str, str]]:
    """[(url, target_hint)] — sources cited by legacy claims the export can't
    reproduce, that aren't in the ledger yet.

    The acceptance gate (swap.check) counts those as LOST claims ("source never
    ingested"/"no matching evidence"); this turns that class of loss into a
    self-closing loop: ingest the exact pages the legacy claims cited, then the
    regular extract/cluster/verdict pass decides them on their merits.
    """
    from knowledge.ledger import parity
    legacy_dirs = [data_dir / "parts", data_dir / "claims"]
    _, _, only_old, _ = parity._match(legacy_dirs, export_dir)
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for stem, claim in only_old:
        for u in sorted(parity._source_urls(claim)):
            key = (u, stem)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def ingest_lost_sources(conn, export_dir: Path, data_dir: Path) -> int:
    """Fetch + ingest the lost claims' cited pages (fault-tolerant per page).
    Returns how many pages were newly ingested."""
    from knowledge.ledger.acquire import _fetch_page_text
    from knowledge.ledger import ingest
    from knowledge.sources.base import Document

    n = 0
    for url, hint in lost_source_urls(conn, export_dir, data_dir):
        # parity normalizes URLs (strips scheme/www) — re-prefix for fetching.
        fetch_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
        text = _fetch_page_text(fetch_url)
        if not text:
            continue
        doc = Document(text=text, url=fetch_url, site_or_channel="")
        n += ingest.ingest_document(conn, doc, "page", hint)
    return n


def _log_telemetry(stats: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as fh:
        fh.write(json.dumps(stats, sort_keys=True) + "\n")


def run(conn, data_dir: Path, export_dir: Path, budget: Budget,
        max_sources: int = 15) -> dict:
    """One remediation pass. Returns the stats dict appended to the telemetry
    log: findings seen, parts re-researched, rows gained per stage, spend."""
    report = build_report(data_dir / "variants", data_dir / "fitment", data_dir / "parts")
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

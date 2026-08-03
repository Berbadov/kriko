"""remediate.py — auto-remediation loop driver (backlog B19).

The detection mechanisms exist (coverage report: zero-claim/missing parts,
automatic variants with no real gearbox part; B6 contradiction surfacing).
What was missing was the trigger: a person noticing the gap and running the
research CLI by hand. This driver turns every part-level coverage finding into
an unattended, budget-capped, resumable pipeline pass:

    acquire (per part) → extract → resolve → cluster → verdict → export

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
    stats["extracted"] = extraction.extract_pending(conn, budget)
    resolve.resolve_all(conn)
    stats["clusters"] = cluster.rebuild_clusters(conn)
    stats["verdicts"] = verdict.run_verdicts(conn, budget)
    stats["exported"] = len(export.export_all(conn, export_dir))
    stats["usd"] = round(budget.total_usd, 4)
    _log_telemetry(stats)
    return stats

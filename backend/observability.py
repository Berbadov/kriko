"""Full-payload /analyze logging — append-only JSONL, no browser/DB client needed.

docs/design_flaws.md "Observability gap": AnalysisLog (backend/db/models.py) stores
only claim IDs and counts, not the listing context that drove gating or the response
actually shown — reconstructing "what did the buyer see and why" needs manual joins
and isn't possible at all for a bad match (nothing to replay). This module logs the
full request + derived context + full response for each analysis, one JSON object per
line, so both a human and an agent can read recent analyses without a DB client, and a
fix can be verified by replaying a logged request (see ops/reports/replay.py).

Writing here must never break the serve path — every call is best-effort.
"""

import json
import logging
from pathlib import Path

from backend import config

log = logging.getLogger(__name__)


def log_analysis_jsonl(record: dict, path: Path | None = None) -> None:
    path = path or config.ANALYSES_LOG_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        log.warning("Failed to write analyses.jsonl", exc_info=True)


def load_records(path: Path) -> tuple[list[dict], int]:
    """Read a JSONL analyses log into ``(records, malformed_skipped)``.

    The single reader every log consumer (read_recent, read_by_id, the demand
    miner) shares — so the log's line-level tolerances live in exactly one place.
    "Malformed" is both a JSON syntax error and well-formed JSON that isn't an
    object (a bare ``42``/``null``/``"str"``/``[...]``): every consumer assumes
    dict records and would crash on ``rec.get(...)`` with ``AttributeError``, so
    a non-object line is as unusable as invalid JSON and is skipped and counted
    the same way. Blank lines are skipped but not counted. Never raises.
    """
    records: list[dict] = []
    skipped = 0
    if not path.exists():
        return records, skipped
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(rec, dict):
                skipped += 1
                continue
            records.append(rec)
    return records, skipped


def read_recent(limit: int = 20, model: str | None = None, path: Path | None = None) -> list[dict]:
    """Most-recent-first records, optionally filtered by (case-insensitive substring) model."""
    path = path or config.ANALYSES_LOG_PATH
    records, _ = load_records(path)
    matched = [
        rec for rec in records
        if not model
        or model.lower() in str(rec.get("ad_metadata", {}).get("model", "")).lower()
    ]
    matched.reverse()
    return matched[:limit]


def read_by_id(analysis_id: str, path: Path | None = None) -> dict | None:
    path = path or config.ANALYSES_LOG_PATH
    records, _ = load_records(path)
    for rec in records:
        if rec.get("id") == analysis_id:
            return rec
    return None

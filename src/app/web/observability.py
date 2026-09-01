"""Append-only JSONL log of everything the browser plane was asked.

This file is where two things come from that nothing else provides:

  * the demand signal — which subjects people look up that no installed pack
    covers yet
  * the replay corpus — real listings a parity gate was built on, and the raw
    material for the next one

A knowledge base with no record of what it was asked cannot tell which gaps
matter. Losing it would have been the quiet kind of regression: nothing breaks,
and six months later there is no way to prioritise anything.

Writing here must never break a lookup — every call is best-effort.
"""

import json
import logging
import os
from pathlib import Path

DEFAULT_LOG_PATH = Path(
    os.environ.get("KRIKO_ANALYSES_LOG", "logs/analyses.jsonl"))

log = logging.getLogger(__name__)


def log_analysis_jsonl(record: dict, path: Path | None = None) -> None:
    path = path or DEFAULT_LOG_PATH
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
    path = path or DEFAULT_LOG_PATH
    records, _ = load_records(path)
    matched = [
        rec for rec in records
        if not model
        or model.lower() in str(rec.get("ad_metadata", {}).get("model", "")).lower()
    ]
    matched.reverse()
    return matched[:limit]


def read_by_id(analysis_id: str, path: Path | None = None) -> dict | None:
    path = path or DEFAULT_LOG_PATH
    records, _ = load_records(path)
    for rec in records:
        if rec.get("id") == analysis_id:
            return rec
    return None

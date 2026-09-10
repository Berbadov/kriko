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

from app.web.settings import default_analysis_log

# Not `Path("logs/analyses.jsonl")`. That resolved against the working
# directory, which an installed app does not own — see settings.KRIKO_HOME.
DEFAULT_LOG_PATH = Path(
    os.environ.get("KRIKO_ANALYSES_LOG", default_analysis_log()))

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


def summarise(path: Path | None = None) -> dict:
    """What the log holds, as numbers a reader can act on.

    The log has existed since the first lookup and nothing the reader can
    reach has ever read it: `About` shows its *path*, which tells them where
    the file is and nothing about what is in it. That was the whole of the
    "no usage info" complaint on this side — the demand signal was being
    written for the agenda's benefit and for nobody else's.

    `answered_nothing` is the number that matters and the reason this is not
    just a line count: a lookup that resolved a subject and returned no claims
    is a coverage gap the reader personally hit, and it is the honest measure
    of how much of their own use this installation is actually serving.

    No timestamps, because the records carry none — see
    `routers/analyze.log_analysis_jsonl`. A count with no clock is what the
    file can support, and inventing a date from the mtime would date every
    record by the last one.
    """
    records, malformed = load_records(path or DEFAULT_LOG_PATH)
    subjects = {
        str(subject)
        for rec in records
        for subject in (rec.get("subjects") or [])
    }
    return {
        "analyses": len(records),
        "malformed": malformed,
        "claims_shown": sum(len(rec.get("claim_titles") or []) for rec in records),
        "answered_nothing": sum(
            1 for rec in records if not (rec.get("claim_titles") or [])
        ),
        "subjects": len(subjects),
        "adapters": sorted({str(rec.get("adapter") or "") for rec in records} - {""}),
    }


def read_by_id(analysis_id: str, path: Path | None = None) -> dict | None:
    path = path or DEFAULT_LOG_PATH
    records, _ = load_records(path)
    for rec in records:
        if rec.get("id") == analysis_id:
            return rec
    return None

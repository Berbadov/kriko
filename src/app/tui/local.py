"""The local model's quick look, read off its own log — no new plumbing.

**Why the log is the wire.** The local plane already narrates every stage it
enters (`providers/local_agent._measured`, `_phase`), and a job's log is the
one channel every client can read. So the console derives its stage table from
the job row it already polls, the same way `web/livefeed.py` derives its event
marks: one copy of the truth, no second endpoint to forget, and the numbers the
operator sees are the numbers a finished run keeps in
`result.measurement.stages`.

**What is measured, and in whose words.** A quick look is not a vector RAG
pipeline: it is search-grounded generation. There is no embedding index — the
retrieval leg is a public search engine, the "context" is whole pages fitted to
the model's window, and the selection leg is extractive evidence IDs. The
stages here are therefore the ones the code actually runs:

* `plan` — the model proposes search queries (or the identity's angles do).
* `search` — the queries reach OpenSERP and hits come back.
* `fetch` — one row per page, timed inside the worker that read it, so the one
  slow host is visible rather than averaged away.
* `identity` — one structured call to name the exact product.
* `extract` — per page: the model selects evidence IDs.
* `verify` — per candidate: source kind, support, identity.
* `digest` — grouping and pair-checking the surviving candidates.
* `render` — display text in the reader's language, then re-checked.
* `language` — language detection and its checks.

A row is one *call or phase*, so `verify` on four candidates is four rows. The
table aggregates them, which is what makes "the model spent two minutes
verifying" answerable at a glance.
"""

import re
from collections import Counter

#: The order a quick look actually runs them in (`local_pipeline.run`):
#: language and identity come first, the query plan is made from the identity,
#: and rendering closes the run. Not a vocabulary the code branches on — an
#: unknown stage is still shown, after these, in the order it first appeared.
#: A new component therefore needs no edit here to be visible.
STAGES = ("language", "identity", "plan", "search", "fetch", "extract",
          "verify", "digest", "render")

_START = re.compile(r"^stage (\S+) start$")
_DONE = re.compile(r"^stage (\S+) done ([0-9.]+)s(?: in=(\d+))?(?: out=(\d+))?$")
_FAILED = re.compile(r"^stage (\S+) failed ([0-9.]+)s(?:: (.*))?$")


def stage_events(log: str) -> list[dict]:
    """Every `stage …` line in a job log, in order.

    `start` is kept as well as the finished rows: it is the only signal that a
    run is *inside* a stage right now, which is what a console is for. A line
    the parser does not know is ignored rather than guessed at — the rest of
    the log is prose for a person.
    """
    events: list[dict] = []
    for line in str(log or "").splitlines():
        text = line.strip()
        match = _START.match(text)
        if match:
            events.append({"stage": match[1], "state": "start"})
            continue
        match = _DONE.match(text)
        if match:
            events.append({
                "stage": match[1], "state": "done",
                "ms": float(match[2]) * 1000,
                "tokens_in": int(match[3]) if match[3] else None,
                "tokens_out": int(match[4]) if match[4] else None,
            })
            continue
        match = _FAILED.match(text)
        if match:
            events.append({"stage": match[1], "state": "failed",
                           "ms": float(match[2]) * 1000,
                           "error": (match[3] or "").strip()})
    return events


def running_stage(events: list[dict]) -> str:
    """The stage a run is inside now, or "".

    Balanced per stage rather than "the last start wins": a stage that failed
    is finished, and the next start is the one actually running. Calls are
    sequential on the job thread, so this is exact for what it covers.
    """
    balance: Counter = Counter()
    for event in events:
        balance[event["stage"]] += 1 if event["state"] == "start" else -1
    for event in reversed(events):
        if event["state"] == "start" and balance[event["stage"]] > 0:
            return event["stage"]
    return ""


def _key(row: dict, order: list[str]) -> tuple[int, int]:
    name = str(row.get("stage") or "?")
    if name in STAGES:
        return (0, STAGES.index(name))
    return (1, order.index(name))


def fold(rows: list[dict]) -> list[dict]:
    """Rows for rows: one line per stage, with its calls and its cost.

    `tps` is output tokens over the stage's own milliseconds — the number that
    makes "too slow" checkable rather than a feeling. `longest` is kept beside
    the total because a stage that is slow once and instant ten times is a
    different bug from one that is slow every time.
    """
    order: list[str] = []
    by_stage: dict[str, dict] = {}
    for row in rows:
        name = str(row.get("stage") or "?")
        if name not in by_stage:
            by_stage[name] = {
                "stage": name, "calls": 0, "failed": 0, "ms": 0.0,
                "tokens_in": 0, "tokens_out": 0, "longest": 0.0, "errors": [],
            }
            order.append(name)
        cell = by_stage[name]
        cell["calls"] += 1
        millis = float(row.get("ms") or 0.0)
        cell["ms"] += millis
        cell["longest"] = max(cell["longest"], millis)
        if row.get("failed") or row.get("state") == "failed":
            cell["failed"] += 1
            if row.get("error") and len(cell["errors"]) < 3:
                cell["errors"].append(str(row["error"])[:160])
        for key in ("tokens_in", "tokens_out"):
            value = row.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                cell[key] += value
    out = []
    for name in order:
        cell = by_stage[name]
        seconds = cell["ms"] / 1000
        cell["seconds"] = round(seconds, 2)
        cell["tps"] = (round(cell["tokens_out"] / seconds, 1)
                       if seconds > 0 and cell["tokens_out"] else None)
        out.append(cell)
    return sorted(out, key=lambda row: _key(row, order))


def health(rows: list[dict], coverage: dict | None) -> dict:
    """The run's pulse: calls, failures, tokens per second, and what was refused.

    The rejection reasons are the closest thing to a straight answer to "is it
    making things up": "invalid evidence IDs" or "numeric assertion absent
    from evidence" is the model's own hallucination being caught, counted.
    """
    coverage = coverage or {}
    failed = sum(1 for row in rows if row.get("failed") or row.get("state") == "failed")
    millis = sum(float(row.get("ms") or 0.0) for row in rows)
    tokens_in = sum(row.get("tokens_in") or 0 for row in rows
                    if isinstance(row.get("tokens_in"), int))
    tokens_out = sum(row.get("tokens_out") or 0 for row in rows
                     if isinstance(row.get("tokens_out"), int))
    reasons = sorted((coverage.get("rejection_reasons") or {}).items(),
                     key=lambda item: -item[1])[:3]
    return {
        "calls": len(rows),
        "failed": failed,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "stage_ms": round(millis, 0),
        "tps": round(tokens_out / (millis / 1000), 1) if millis > 0 and tokens_out else None,
        "accepted": coverage.get("accepted_candidates"),
        "rejected": coverage.get("rejected_candidates"),
        "reasons": [{"reason": str(reason)[:80], "count": count}
                    for reason, count in reasons],
        "status": str(coverage.get("status") or ""),
        "errors": len(coverage.get("errors") or []),
        "pages_read": coverage.get("pages_read"),
    }


def is_local_job(row: dict) -> bool:
    """Whether a job row ran on this machine's own model.

    The handler says so before anything else (`tasks._local_asker` logs
    "local plane: …"), and a run submitted with `backend: local` says so in its
    params. Either is enough; a quick look on a coding agent has neither, and
    this console must not present one as the other.
    """
    if str(row.get("kind") or "") != "quick_look":
        return False
    params = row.get("params") or {}
    if str(params.get("backend") or "").lower() == "local":
        return True
    return "local plane:" in str(row.get("log") or "")


def wall_seconds(job: dict) -> float | None:
    """How long the job took, from its own two timestamps.

    Kept beside the sum of stage times because the difference is a finding: a
    run whose stages add to 20 s and whose wall clock is 34 s spent a third of
    its time outside any stage, and that is where a stray probe or a cold
    model loads shows up.
    """
    started, finished = job.get("started_at"), job.get("finished_at")
    if not started:
        return None
    from datetime import datetime, timezone

    def parse(text) -> datetime | None:
        try:
            return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    first = parse(started)
    last = parse(finished) if finished else datetime.now(timezone.utc)
    if first is None or last is None:
        return None
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return round(max(0.0, (last - first).total_seconds()), 1)
def newest_local_job(items: list[dict]) -> dict | None:
    for row in items or []:
        if is_local_job(row):
            return row
    return None


def report(job: dict | None, plane: dict | None = None) -> dict:
    """Everything the local tab draws, from one job row and one plane probe."""
    job = job or {}
    plane = plane or {}
    result = job.get("result") or {}
    coverage = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
    measurement = result.get("measurement") or {}
    finished_rows = [row for row in (measurement.get("stages") or [])
                     if isinstance(row, dict)]
    events = stage_events(job.get("log") or "")
    if finished_rows:
        rows = finished_rows
    else:
        rows = [event for event in events if event["state"] != "start"]
    running = running_stage(events) if not job.get("done") else ""
    stages = fold(rows)
    if running and all(cell["stage"] != running for cell in stages):
        # The run is inside a stage whose call has not finished, so the log
        # holds a `start` and no `done` yet. Without a row the table would be
        # empty at exactly the moment the console exists for: a stage that is
        # taking a long time.
        stages.append({"stage": running, "calls": 0, "failed": 0, "ms": 0.0,
                       "tokens_in": 0, "tokens_out": 0, "longest": 0.0,
                       "errors": [], "seconds": 0.0, "tps": None})
        order = [cell["stage"] for cell in stages]
        stages.sort(key=lambda row: _key(row, order))
    for cell in stages:
        cell["running"] = cell["stage"] == running
    return {
        "job": job,
        "plane": plane,
        "stages": stages,
        "health": health(rows, coverage),
        "running": running,
        "wall_seconds": wall_seconds(job) if job else None,
        "coverage": coverage,
    }

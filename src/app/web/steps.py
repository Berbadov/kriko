"""A job's log as ordered, timed, filterable steps (#261).

The job log (`jobs.log`) is prose: a tail of lines a person reads top to
bottom. The reader asked for "every step in order with its timing: the words
searched, each result and whether its page was read, every agent call, each
retry and why, each verification verdict, and every failure with its message",
filterable, expandable to the exact request and reply, and exportable.

**One hook, nothing listed per handler.** Every line a handler writes goes
through `state.update_job(line=...)`; that function now also calls
`record_line`, which classifies the line by *shape* (the same approach as
`livefeed.classify`, whose closed vocabulary of event kinds this extends) and
keeps a row. A new handler, a new agent, a new log line is a step with no
registration. Calls to an agent are the one thing a line cannot carry (the
prompt, the reply, tokens, cost), so `watch_calls` puts a recording wrapper on
a researcher's public entry points once, where `tasks._wire_researcher_text`
already connects every researcher to its job: every plane that is wired is
logged by the same code.

**Nothing is kept unredacted.** A prompt carries the reader's saved profile
and a CLI's reply can quote a key, so every text passes `redaction.redact_text`
before it is written: credentials by value and by shape, and the reader's own
saved words (`private_strings`) masked. That is the redaction the benchmark
traces use, moved down to `app/redaction.py`.

**Recording never changes the outcome.** Every write is wrapped; a step lost
is a worse log, never a failed job, exactly as `operations.record` and
`pipeline.Emitter` decide.
"""

import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app import redaction

#: The closed vocabulary of what produced a step. Event kinds of a job, not
#: anything a pack or a site knows. `failure` is a *level*, not a source: a
#: failed search is a search that failed.
SOURCES = ("job", "search", "page", "agent", "verify", "retry", "note")
LEVELS = ("info", "warn", "error")

#: Steps kept per job. The job log keeps 64 KiB; a long research run writes a
#: few hundred steps. Errors are always kept (`ERROR_ROOM` beyond the cap).
STEPS_PER_JOB = 1500
ERROR_ROOM = 200

#: Characters of a title (the one line a row shows) and of a kept request or
#: reply. Whole pages never pass through here, but a prompt can hold several.
TITLE_CHARS = 300
BODY_CHARS = 40_000

_URL = re.compile(r"https?://[^\s<>\"'`)\]}]+")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


# ── what the reader said about themselves, so a log can leave it out ─────────

_PRIVATE_TTL = 5.0
_private_cache: dict[str, tuple[float, list[str]]] = {}


def _db_file(conn: sqlite3.Connection) -> str:
    try:
        return str(conn.execute("PRAGMA database_list").fetchone()[2] or ":memory:")
    except sqlite3.Error:
        return ""


def private_strings(conn: sqlite3.Connection) -> list[str]:
    """The reader's saved free text, to be masked wherever a log would repeat it.

    Read from the profile rather than listed: whatever fields `buyer.clean`
    keeps are the reader's words (`about`, the must / avoid / prefer / distrust
    lists, the budget note). Cached for a few seconds per file because a
    running job writes a step per line and the profile does not change mid-run.
    """
    key = _db_file(conn)
    cached = _private_cache.get(key)
    if cached and time.monotonic() - cached[0] < _PRIVATE_TTL:
        return cached[1]
    found: list[str] = []
    try:
        from app import buyer

        profile = buyer.read(conn)
        found.append(str(profile.get("about") or ""))
        for name in ("must", "avoid", "prefer", "distrust"):
            found.extend(str(one) for one in profile.get(name) or [])
        found.append(str((profile.get("budget") or {}).get("note") or ""))
    except Exception:  # noqa: BLE001 - no profile to mask is an empty list
        found = []
    cleaned = [one for one in found if len(one.strip()) >= 4]
    _private_cache[key] = (time.monotonic(), cleaned)
    return cleaned


def forget_private() -> None:
    """For tests, and for the moment the reader saves a new profile."""
    _private_cache.clear()


# ── classifying a log line by its shape ──────────────────────────────────────

def _plain(url: str) -> str:
    """The address without its query or fragment, which is where tokens ride."""
    parts = urlsplit(url.rstrip(".,;:"))
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _urls(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for found in _URL.findall(text):
        try:
            seen[_plain(found)] = None
        except ValueError:
            # Model output and failed-read messages can contain broken URLs.
            # Keep the log line even when its address cannot be classified.
            continue
    return list(seen)


def _quoted(text: str) -> list[str]:
    return [one.strip() for one in re.findall(r"[\"“]([^\"”]+)[\"”]", text) if one.strip()]


def _words(text: str) -> list[str]:
    return [one.strip() for one in re.split(r";\s+", text) if one.strip()]


def _search(line: str) -> dict:
    after = line.split(":", 1)[1] if ":" in line else line
    queries = _quoted(line) if line.lower().startswith("searched") else _words(after)
    return {"queries": queries}


def _page(read: bool | None):
    def extract(line: str) -> dict:
        found = _urls(line)
        out: dict[str, Any] = {"urls": found}
        if read is not None:
            out["read"] = read
        count = re.search(r"\b(\d+)\s+page", line)
        if count:
            out["count"] = int(count.group(1))
        return out
    return extract


def _reason(line: str) -> dict:
    return {"reason": line}


def _verdict(verdict: str):
    def extract(line: str) -> dict:
        out: dict[str, Any] = {"verdict": verdict}
        quoted = _quoted(line)
        if quoted:
            out["subject"] = quoted[0]
        if ":" in line and verdict == "refused":
            out["why"] = line.rsplit(":", 1)[1].strip()
        return out
    return extract


def _none(_line: str) -> dict:
    return {}


#: Ordered; the first match wins. (pattern, source, level, extractor). A closed
#: vocabulary of line *shapes* written by the narrator (`harness._tool_line`),
#: the local plane and `tasks.py`, in the same spirit as `livefeed._SHAPES`: a
#: line that matches none is a `note`, kept and shown, never dropped.
_SHAPES: tuple[tuple[re.Pattern[str], str, str, Callable[[str], dict]], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), source, level, extract)
    for pattern, source, level, extract in (
        (r"^job failed", "job", "error", _reason),
        (r"^(a tool call failed|tool error)", "agent", "error", _reason),
        (r"^search failed\b", "search", "error", _search),
        (r"^could not (read|fetch)\b", "page", "error", _page(False)),
        (r"^(could not re-?ask|could not (check|separate|run))\b", "retry", "error", _reason),
        (r"^stopped\b", "job", "warn", _reason),
        (r"^(asking once more|asking for a correction|re-asking|the (second|planner'?s) reply|"
         r"the shape repair|the reply carried no|persistent protocol unavailable|"
         r"the agent offered to begin|sample check failed|retrying|trying again)",
         "retry", "warn", _reason),
        (r"^searching again\b", "retry", "info", _search),
        (r"^(refused|left out)\b", "verify", "warn", _verdict("refused")),
        (r"^kept\b", "verify", "info", _verdict("kept")),
        (r"^(self-check|evidence check|coverage:|result status|identified:|"
         r"checking )", "verify", "info", _none),
        (r"^(skipped|rejected candidate|replacing)\b", "page", "warn", _page(False)),
        (r"^(page reading deadline|page read budget|quick-look search budget)", "page", "warn", _reason),
        (r"^(read through the page reader|fetched|page fetched|read:|extracting source|"
         r"read \d+ page|using \d+ supplied)", "page", "info", _page(True)),
        (r"^found \d+ page", "search", "info", _page(None)),
        (r"^(searched\b|searching\b|query:|search language:|sources first)", "search", "info", _search),
        (r"^(asking\b|answering with|sending \d+|fitted \d+|plane:|local plane|"
         r"local structured completion|finished\b)", "agent", "info", _none),
    )
)


def classify(line: str) -> dict:
    """One log line as `{source, level, title, detail, body}`.

    `title` is the first line, bounded; a longer or multi-line text keeps its
    whole as `body`, because a reply the handler logged is the exact text a
    reader will want to expand.
    """
    text = str(line or "").strip()
    first = text.split("\n", 1)[0]
    for pattern, source, level, extract in _SHAPES:
        if pattern.match(first):
            detail = extract(first)
            break
    else:
        source, level, detail = "note", "info", {}
    body = text if (len(text) > TITLE_CHARS or "\n" in text) else ""
    return {"source": source, "level": level, "title": first[:TITLE_CHARS],
            "detail": {k: v for k, v in detail.items() if v not in (None, "", [])},
            "body": body}


# ── writing ──────────────────────────────────────────────────────────────────

def _clip(value: Any, private: Iterable[str], limit: int) -> str:
    return redaction.redact_text(value, limit=limit, private=private)


def _clean_detail(detail: dict, private: Iterable[str]) -> str:
    """The structured fields as JSON, with every string in them redacted."""
    def walk(value):
        if isinstance(value, str):
            return _clip(value, private, 2000)
        if isinstance(value, dict):
            return {str(k): walk(v) for k, v in list(value.items())[:60]}
        if isinstance(value, (list, tuple)):
            return [walk(v) for v in list(value)[:60]]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return _clip(str(value), private, 500)
    try:
        return json.dumps(walk(detail), ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def record(conn: sqlite3.Connection, job_id: str, *, source: str, title: str,
           level: str = "info", state: str = "done", ms: int | None = None,
           parent_id: int | None = None, tokens: int | None = None,
           usd: float | None = None, detail: dict | None = None,
           request: str = "", response: str = "",
           private: Iterable[str] | None = None, commit: bool = False) -> int | None:
    """Keep one step. Returns its id, or `None` when it was not kept.

    Never raises: the instrument must not break the experiment.
    """
    try:
        source = source if source in SOURCES else "note"
        level = level if level in LEVELS else "info"
        keep = list(private if private is not None else private_strings(conn))
        # A bounded log: past the cap only errors are kept, and those up to
        # their own ceiling, so a flood of notes cannot hide the failure.
        count = conn.execute("SELECT COUNT(*) FROM job_steps WHERE job_id = ?",
                             (job_id,)).fetchone()[0]
        if count >= STEPS_PER_JOB + (ERROR_ROOM if level == "error" else 0):
            return None
        cursor = conn.execute(
            "INSERT INTO job_steps (job_id, at, source, level, title, state, ms,"
            " parent_id, tokens, usd, detail_json, request, response)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, now(), source, level, _clip(title, keep, TITLE_CHARS), state, ms,
             parent_id, tokens, usd, _clean_detail(detail or {}, keep),
             _clip(request, keep, BODY_CHARS), _clip(response, keep, BODY_CHARS)),
        )
        if commit:
            conn.commit()
        return int(cursor.lastrowid or 0)
    except Exception:  # noqa: BLE001 - a step lost is a worse log, not a failed job
        return None


def record_line(conn: sqlite3.Connection, job_id: str, line: str) -> None:
    """The hook: `state.update_job` calls this for every line it appends."""
    found = classify(line)
    if not found["title"]:
        return
    record(conn, job_id, source=found["source"], level=found["level"],
           title=found["title"], detail=found["detail"], response=found["body"])


def close_running(conn: sqlite3.Connection, job_id: str = "",
                  why: str = "the app stopped while this was running") -> None:
    """A call still `running` when its job ends, or at startup, did not finish."""
    try:
        where, args = ("state = 'running'", [])
        if job_id:
            where, args = (where + " AND job_id = ?", [job_id])
        conn.execute(
            "UPDATE job_steps SET state = 'failed', level = 'error',"
            f" response = CASE WHEN response = '' THEN ? ELSE response END WHERE {where}",
            [why, *args])
    except sqlite3.Error:
        pass


# ── the one wrapper on a researcher ──────────────────────────────────────────

#: The entry points a call to an agent goes in at. Every researcher plane has
#: some of these (`ask` is the common one, `_run` is where a CLI is spoken to,
#: `gather` is a research pass); a name a plane lacks is simply skipped, and a
#: call made through one entry that makes another shows as a nested step.
WATCHED = ("ask", "ask_quick", "ask_author", "ask_followup", "gather", "_run")


def path_of(conn: sqlite3.Connection) -> str:
    return _db_file(conn)


def _agent_of(researcher) -> dict:
    harness = getattr(researcher, "harness", None)
    agent = getattr(researcher, "agent", None)
    provider = harness or agent
    ident = str(getattr(provider, "id", "") or getattr(provider, "key", "")
                or getattr(researcher, "name", "") or type(researcher).__name__)
    label = str(getattr(provider, "label", "") or ident)
    model = (getattr(researcher, "requested_model", "")
             or (getattr(researcher, "model", "") if provider is agent or harness is None else "")
             or "")
    return {"agent": ident, "agent_label": label, "model": str(model),
            "plane": str(getattr(researcher, "name", "") or "")}


def _number(value) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _spent(researcher) -> tuple[int | None, float | None]:
    tokens = getattr(researcher, "tokens_used", None)
    usd = getattr(researcher, "cost_usd", None)
    if usd is None:
        usd = getattr(researcher, "spent", None)
    priced = _number(usd)
    return (tokens if isinstance(_number(tokens), int) else None,
            float(priced) if priced is not None else None)


def _request_of(name: str, args: tuple, kwargs: dict) -> str:
    first = args[0] if args else next(iter(kwargs.values()), "")
    if isinstance(first, str) and name in ("ask", "_run"):
        return first
    try:
        shown = {"args": [a if isinstance(a, (str, int, float, bool, type(None))) else
                          getattr(a, "subject_label", None) or type(a).__name__ for a in args],
                 "kwargs": {k: (v if isinstance(v, (str, int, float, bool, type(None)))
                                else type(v).__name__) for k, v in kwargs.items()}}
        return json.dumps(shown, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def _verification_of(researcher) -> dict | None:
    found = getattr(researcher, "verification", None)
    if not isinstance(found, dict) or not found:
        return None
    out: dict[str, Any] = {}
    for key, value in found.items():
        if isinstance(value, (bool, int, float, str)):
            out[str(key)] = value
        elif isinstance(value, (list, dict)):
            out[str(key)] = len(value)
    return out or None


def watch_calls(researcher, db_path: str, job_id: str) -> bool:
    """Record every call to an agent on `researcher` as a step of `job_id`.

    Idempotent (`_wire_researcher_text` can run twice on one researcher), and
    inert when there is nowhere to write. Each call is one row, opened before
    the work so a hung call is visible as `running`, and closed with its
    duration, sizes, tokens, cost and the redacted prompt and reply. A call
    made inside another call is nested under it; a call that follows a failed
    call of the same entry point is marked a retry and says why.
    """
    if not db_path or not job_id:
        return False
    target = getattr(researcher, "_kriko_steps", None)
    if isinstance(target, dict):
        # Already wrapped, perhaps for an earlier job: the same wrapper now
        # writes to this one, so a researcher that is reused is not logged
        # into the job it served first.
        target.update(job_id=job_id, db_path=db_path)
        return False
    target = {"job_id": job_id, "db_path": db_path}
    from app.web import state

    local = threading.local()
    failed_before: dict[tuple[int, str], str] = {}
    attempts: dict[tuple[int, str], int] = {}

    def stack() -> list:
        if not hasattr(local, "stack"):
            local.stack = []
        return local.stack

    def wrap(name: str, inner: Callable[..., Any]) -> Callable[..., Any]:
        def recorded(*args, **kwargs):
            conn = None
            row_id: int | None = None
            job_id, db_path = target["job_id"], target["db_path"]
            started = time.monotonic()
            before_tokens, before_usd = _spent(researcher)
            who = _agent_of(researcher)
            calls = stack()
            depth = len(calls)
            parent = calls[-1] if calls else None
            request = _request_of(name, args, kwargs)
            retry_reason = failed_before.pop((depth, name), "")
            attempt = attempts.get((depth, name), 0) + 1 if retry_reason else 1
            attempts[(depth, name)] = attempt
            try:
                conn = state.connect(Path(db_path))
                private = private_strings(conn)
                if retry_reason:
                    record(conn, job_id, source="retry", level="warn", parent_id=parent,
                           title=f"retrying {name} (attempt {attempt}): {retry_reason}",
                           detail={"attempt": attempt, "reason": retry_reason, **who,
                                   "method": name}, private=private)
                row_id = record(
                    conn, job_id, source="agent", state="running", parent_id=parent,
                    title=_call_title(name, who),
                    detail={**who, "method": name, "depth": depth, "attempt": attempt,
                            "prompt_chars": len(request)},
                    request=request, private=private)
                conn.commit()
            except Exception:  # noqa: BLE001 - recording is never the failure
                row_id = None
            calls.append(row_id)
            try:
                try:
                    reply = inner(*args, **kwargs)
                except BaseException as error:
                    calls.pop()
                    why = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
                    # The reader pressing stop is not a failure to retry.
                    stopped = bool(getattr(error, "cancelled", False))
                    if not stopped:
                        failed_before[(depth, name)] = redaction.redact_text(why, limit=200)
                    _finish(conn, row_id, started, researcher, before_tokens, before_usd,
                            who, name, depth, attempt, request, "", why, failed=True,
                            stopped=stopped)
                    raise
                calls.pop()
                _finish(conn, row_id, started, researcher, before_tokens, before_usd,
                        who, name, depth, attempt, request, reply, "", failed=False)
                if depth == 0:
                    _verification(conn, job_id, researcher)
                return reply
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except sqlite3.Error:
                        pass

        recorded._kriko_recorded = True  # type: ignore[attr-defined]
        return recorded

    wrapped = False
    for name in WATCHED:
        inner = getattr(researcher, name, None)
        if callable(inner) and not getattr(inner, "_kriko_recorded", False):
            try:
                setattr(researcher, name, wrap(name, inner))
                wrapped = True
            except (AttributeError, TypeError):
                continue
    if wrapped:
        try:
            researcher._kriko_steps = target
        except (AttributeError, TypeError):
            pass
    return wrapped


def _call_title(name: str, who: dict) -> str:
    return f"{name}: {who['agent_label']}" + (f" · {who['model']}" if who["model"] else "")


def _finish(conn, row_id, started, researcher, before_tokens, before_usd,
            who, name, depth, attempt, request, reply, error, *, failed,
            stopped: bool = False) -> None:
    if conn is None or row_id is None:
        return
    try:
        ms = round((time.monotonic() - started) * 1000)
        after_tokens, after_usd = _spent(researcher)
        tokens = (after_tokens - (before_tokens or 0)) if after_tokens is not None else None
        usd = (round(after_usd - (before_usd or 0.0), 6) if after_usd is not None else None)
        text = reply if isinstance(reply, str) else ("" if reply is None else repr(reply)[:2000])
        private = private_strings(conn)
        detail = {**who, "method": name, "depth": depth, "attempt": attempt,
                  "prompt_chars": len(request), "reply_chars": len(text), "ms": ms}
        if error:
            detail["error"] = error
        conn.execute(
            "UPDATE job_steps SET state = ?, level = ?, ms = ?, tokens = ?, usd = ?,"
            " detail_json = ?, response = ?, title = ? WHERE step_id = ?",
            ("failed" if failed else "done",
             ("warn" if stopped else "error") if failed else "info", ms, tokens, usd,
             _clean_detail(detail, private),
             _clip(error if failed else text, private, BODY_CHARS),
             _clip(_call_title(name, who) + ((" stopped" if stopped else f" failed: {error}")
                                              if failed else ""),
                   private, TITLE_CHARS),
             row_id))
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


def _verification(conn, job_id: str, researcher) -> None:
    found = _verification_of(researcher)
    if conn is None or not found:
        return
    try:
        record(conn, job_id, source="verify", level="info",
               title="verification: " + ", ".join(f"{k} {v}" for k, v in list(found.items())[:6]),
               detail=found, commit=True)
    except Exception:  # noqa: BLE001
        pass


# ── reading ──────────────────────────────────────────────────────────────────

LABEL_KEYS = ("product", "label", "subject", "subject_id", "category", "question",
              "text", "message", "pack_id", "host", "url")


def label_of(params: dict | None) -> str:
    """What a job is about, from whichever of its own parameters says so."""
    for key in LABEL_KEYS:
        value = (params or {}).get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:120]
    return ""


def _csv(value: str) -> list[str]:
    return [one.strip() for one in str(value or "").split(",") if one.strip()]


def _ts(iso: str | None) -> float | None:
    try:
        return datetime.fromisoformat(str(iso)).timestamp() if iso else None
    except ValueError:
        return None


_JOB_AGG = (
    "SELECT s.job_id AS job_id, COUNT(*) AS steps,"
    " SUM(s.level = 'error') AS errors, SUM(s.level = 'warn') AS warnings,"
    " SUM(s.source = 'search') AS searches, SUM(s.source = 'page') AS pages,"
    " SUM(s.source = 'retry') AS retries, MIN(s.at) AS first_at, MAX(s.at) AS last_at,"
    " SUM(s.source = 'agent' AND NOT EXISTS"
    "     (SELECT 1 FROM job_steps c WHERE c.parent_id = s.step_id)) AS calls,"
    " SUM(CASE WHEN s.source = 'agent' AND NOT EXISTS"
    "     (SELECT 1 FROM job_steps c WHERE c.parent_id = s.step_id) THEN s.tokens END) AS tokens,"
    " SUM(CASE WHEN s.source = 'agent' AND NOT EXISTS"
    "     (SELECT 1 FROM job_steps c WHERE c.parent_id = s.step_id) THEN s.usd END) AS usd,"
    " SUM(s.source = 'agent' AND NOT EXISTS"
    "     (SELECT 1 FROM job_steps c WHERE c.parent_id = s.step_id) AND s.usd IS NULL"
    "     AND s.state = 'done') AS unpriced"
    " FROM job_steps s WHERE s.job_id IN ({marks}) GROUP BY s.job_id"
)


def _zero(job: dict, agg: dict | None) -> float | None:
    """When a job's clock starts: its first step, which has milliseconds,
    rather than the job row's start, which is whole seconds."""
    return _ts((agg or {}).get("first_at")) or _ts(job.get("started_at") or job.get("created_at"))


def _summary(job: dict, agg: dict | None) -> dict:
    started = _ts(job.get("started_at") or job.get("created_at"))
    ended = _ts(job.get("finished_at"))
    agg = agg or {}
    # The job row keeps whole seconds; its first and last step keep milliseconds,
    # so a job that took a fraction of a second says so.
    first, last = _ts(agg.get("first_at")), _ts(agg.get("last_at"))
    if job.get("done") and first is not None and last is not None:
        started, ended = first, last
    return {
        "job_id": job["job_id"], "kind": job["kind"], "label": label_of(job.get("params")),
        "state": job["state"], "done": bool(job.get("done")), "message": job.get("message") or "",
        "created_at": job.get("created_at"), "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "duration_ms": round((ended - started) * 1000) if started and ended else None,
        "steps": agg.get("steps") or 0, "errors": agg.get("errors") or 0,
        "warnings": agg.get("warnings") or 0, "searches": agg.get("searches") or 0,
        "pages": agg.get("pages") or 0, "retries": agg.get("retries") or 0,
        "calls": agg.get("calls") or 0, "tokens": agg.get("tokens"),
        "usd": agg.get("usd"),
        # An unpriced call is a call nobody could put a price on; a total that
        # leaves it out is a floor, and the screen says so.
        "usd_complete": not agg.get("unpriced"),
    }


def list_jobs(conn: sqlite3.Connection, *, limit: int = 60, kind: str = "",
              state: str = "", q: str = "") -> list[dict]:
    from app.web import state as app_state

    clauses, args = [], []
    kinds, states = _csv(kind), _csv(state)
    if kinds:
        clauses.append(f"kind IN ({','.join('?' * len(kinds))})")
        args += kinds
    if states:
        clauses.append(f"state IN ({','.join('?' * len(states))})")
        args += states
    if q.strip():
        clauses.append("(kind LIKE ? OR params_json LIKE ? OR job_id LIKE ?)")
        args += [f"%{q.strip()}%"] * 3
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM jobs {where} ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (*args, max(1, min(int(limit), 200)))).fetchall()
    jobs = [app_state._job(row) for row in rows]
    if not jobs:
        return []
    marks = ",".join("?" * len(jobs))
    aggs = {row["job_id"]: dict(row) for row in conn.execute(
        _JOB_AGG.format(marks=marks), [job["job_id"] for job in jobs])}
    return [_summary(job, aggs.get(job["job_id"])) for job in jobs]


def _filters(job_id: str, level: str, source: str, q: str) -> tuple[str, list]:
    clauses, args = [], []
    if job_id:
        clauses.append("s.job_id = ?")
        args.append(job_id)
    for column, values, allowed in (("level", _csv(level), LEVELS), ("source", _csv(source), SOURCES)):
        values = [v for v in values if v in allowed]
        if values:
            clauses.append(f"s.{column} IN ({','.join('?' * len(values))})")
            args += values
    if q.strip():
        clauses.append("(s.title LIKE ? OR s.detail_json LIKE ?)")
        args += [f"%{q.strip()}%"] * 2
    return (("WHERE " + " AND ".join(clauses)) if clauses else ""), args


def _step(row: sqlite3.Row, started: dict[str, float | None]) -> dict:
    out = {key: row[key] for key in ("step_id", "job_id", "at", "source", "level", "title",
                                     "state", "ms", "parent_id", "tokens", "usd")}
    try:
        out["detail"] = json.loads(row["detail_json"] or "{}")
    except ValueError:
        out["detail"] = {}
    out["request_chars"] = row["request_chars"]
    out["response_chars"] = row["response_chars"]
    zero = started.get(row["job_id"])
    at = _ts(row["at"])
    out["offset_ms"] = max(0, round((at - zero) * 1000)) if at is not None and zero else None
    out["gap_ms"] = None
    out["depth"] = 0
    return out


def list_steps(conn: sqlite3.Connection, *, job_id: str = "", level: str = "",
               source: str = "", q: str = "", limit: int = 1000, after_id: int = 0) -> dict:
    """The steps, oldest first, with each one's own time and the gap to the next."""
    where, args = _filters(job_id, level, source, q)
    if after_id:
        where = (where + " AND " if where else "WHERE ") + "s.step_id > ?"
        args.append(int(after_id))
    limit = max(1, min(int(limit), 5000))
    total = conn.execute(f"SELECT COUNT(*) FROM job_steps s {where}", args).fetchone()[0]
    # The newest `limit` rows, returned oldest first: a long job shows how it
    # ended, and `truncated` says the beginning is not here.
    rows = conn.execute(
        "SELECT s.*, LENGTH(s.request) AS request_chars, LENGTH(s.response) AS response_chars"
        f" FROM job_steps s {where} ORDER BY s.step_id DESC LIMIT ?", (*args, limit)).fetchall()
    rows.reverse()
    job_ids = list(dict.fromkeys(row["job_id"] for row in rows))
    jobs: dict[str, dict] = {}
    started: dict[str, float | None] = {}
    if job_ids:
        marks = ",".join("?" * len(job_ids))
        from app.web import state as app_state

        found = [app_state._job(r) for r in conn.execute(
            f"SELECT * FROM jobs WHERE job_id IN ({marks})", job_ids)]
        aggs = {r["job_id"]: dict(r) for r in conn.execute(_JOB_AGG.format(marks=marks), job_ids)}
        for job in found:
            jobs[job["job_id"]] = _summary(job, aggs.get(job["job_id"]))
            started[job["job_id"]] = _zero(job, aggs.get(job["job_id"]))
    steps = [_step(row, started) for row in rows]
    by_id = {one["step_id"]: one for one in steps}
    last: dict[str, dict] = {}
    for one in steps:
        parent = by_id.get(one["parent_id"]) if one["parent_id"] else None
        one["depth"] = (parent["depth"] + 1) if parent else 0
        before = last.get(one["job_id"])
        if before is not None:
            a, b = _ts(before["at"]), _ts(one["at"])
            if a is not None and b is not None:
                before["gap_ms"] = max(0, round((b - a) * 1000))
        last[one["job_id"]] = one
    return {"items": steps, "jobs": jobs, "total": total, "truncated": total > len(steps)}


def step_detail(conn: sqlite3.Connection, step_id: int) -> dict | None:
    """One step with its exact request and reply, redacted once more on the way out."""
    row = conn.execute(
        "SELECT s.*, LENGTH(s.request) AS request_chars, LENGTH(s.response) AS response_chars"
        " FROM job_steps s WHERE s.step_id = ?", (int(step_id),)).fetchone()
    if row is None:
        return None
    first = conn.execute("SELECT MIN(at) FROM job_steps WHERE job_id = ?",
                         (row["job_id"],)).fetchone()[0]
    zero = {row["job_id"]: _ts(first)}
    out = _step(row, zero)
    private = private_strings(conn)
    out["request"] = redaction.redact_text(row["request"], private=private)
    out["response"] = redaction.redact_text(row["response"], private=private)
    return out


def _clock(ms: int | None) -> str:
    return "      ?" if ms is None else f"+{ms / 1000:8.3f}s"


def export_text(conn: sqlite3.Connection, *, job_id: str = "", level: str = "",
                source: str = "", q: str = "", bodies: bool = False,
                limit: int = 5000) -> dict:
    """The log as plain text a reader can paste into a message or keep."""
    data = list_steps(conn, job_id=job_id, level=level, source=source, q=q, limit=limit)
    private = private_strings(conn)
    lines = [f"Kriko log, exported {now()}",
             f"{len(data['items'])} of {data['total']} step(s)"
             + (f", job {job_id}" if job_id else ", every job")
             + (f", level {level}" if level else "") + (f", source {source}" if source else "")
             + (f", containing {q!r}" if q else ""), ""]
    current = None
    for one in data["items"]:
        if one["job_id"] != current:
            current = one["job_id"]
            job = data["jobs"].get(current, {})
            lines += [f"job {current}  {job.get('kind', '')}  {job.get('label', '')}  "
                      f"[{job.get('state', '')}]  steps {job.get('steps', 0)}, "
                      f"errors {job.get('errors', 0)}, calls {job.get('calls', 0)}"
                      + (f", tokens {job['tokens']}" if job.get("tokens") is not None else "")
                      + (f", ${job['usd']:.4f}" if job.get("usd") is not None else ""), ""]
        facts = [f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in one["detail"].items()
                 if k not in ("ms",)]
        own = f" ({one['ms']} ms)" if one["ms"] is not None else ""
        spend = ""
        if one["tokens"] is not None:
            spend += f" tokens={one['tokens']}"
        if one["usd"] is not None:
            spend += f" usd={one['usd']}"
        indent = "  " * one["depth"]
        lines.append(f"{_clock(one['offset_ms'])}  {one['level'].upper():5}  {one['source']:6}  "
                     f"{indent}{one['title']}{own}{spend}")
        if facts:
            lines.append(f"{'':27}{indent}  " + " ".join(facts)[:600])
        if bodies and (one["request_chars"] or one["response_chars"]):
            full = step_detail(conn, one["step_id"]) or {}
            for label, text in (("request", full.get("request")), ("response", full.get("response"))):
                if text:
                    lines.append(f"{'':27}{indent}  --- {label} ({len(text)} chars) ---")
                    lines += [f"{'':27}{indent}  {part}" for part in text.splitlines() or [""]]
    body = redaction.redact_text("\n".join(lines) + "\n", private=private)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return {"filename": f"kriko-log-{job_id or 'all'}-{stamp}.txt", "text": body,
            "steps": len(data["items"]), "total": data["total"]}


def prune_orphans(conn: sqlite3.Connection) -> None:
    """Steps follow their job out when `finish_job` prunes history."""
    try:
        conn.execute("DELETE FROM job_steps WHERE job_id NOT IN (SELECT job_id FROM jobs)")
    except sqlite3.Error:
        pass

"""What the app has used, kept apart by the thing that was used.

"The web search API, the LLM API and so on need to be calculated separately."
One total hides the question a reader actually has, which is *which* of these is
running down, so every use is one row in `usage_events`, filed under one of four
resources:

    llm_api      a hosted model, billed by the token or the call
    web_search   a search provider's API
    local_model  the model on this machine: tokens and time, no price
    cli_agent    a coding agent the reader signs in to: a subscription window

**A blank is not a zero.** A column no call counted stays `NULL` in the row and
`None` in the sum. A sum is taken only over the rows that counted, and the
answer says how many did, so "$0.00" never means "nobody priced this".

**There is no balance here.** No provider lets a key read what is left, and the
number this module would have to invent for that is the most dangerous one on
the screen. A subscription agent is the exception, because it says how far into
its own window the reader is (`app/limits.py`); that is shown as reported, with
the time it was reported.

Windows are rolling: the last 5 hours, 24 hours, 7 days and 30 days from now.
They are the reader's way of asking "how much lately", and they are not the
vendor's billing periods, which the vendor alone knows.
"""

import sqlite3
import threading
import time
from collections.abc import Mapping
from pathlib import Path

RESOURCES = ("llm_api", "web_search", "local_model", "cli_agent")

#: Rolling windows, in seconds, in the order the screen draws them.
WINDOWS = {"5h": 5 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600, "30d": 30 * 24 * 3600}

LIMITS_KEY = "agent_limits"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    resource   TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT '',
    model      TEXT NOT NULL DEFAULT '',
    calls      INTEGER NOT NULL DEFAULT 1,
    ok         INTEGER,
    tokens_in  INTEGER,
    tokens_out INTEGER,
    tokens     INTEGER,
    usd        REAL
);
CREATE INDEX IF NOT EXISTS usage_events_ts ON usage_events (resource, ts);
"""

_lock = threading.Lock()


def _count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _money(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def resource_of(agent_id: str = "", plane: str = "") -> str:
    """Which resource an agent's use belongs to.

    `local` is the model on this machine. The `api` plane and an agent id that
    names a hosted API are billed per call. Everything else is a coding agent
    the reader runs under a subscription.
    """
    who, how = (agent_id or "").strip().lower(), (plane or "").strip().lower()
    if who == "local" or how == "local":
        return "local_model"
    if how == "api" or who.endswith("-api") or who in {"api", "openai", "anthropic", "mistral"}:
        return "llm_api"
    return "cli_agent"


def record_on(conn, resource: str, *, source: str = "", model: str = "", calls: int = 1,
              ok: bool | None = None, tokens_in=None, tokens_out=None, tokens=None, usd=None) -> None:
    """File one use on a connection the caller already holds."""
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO usage_events (ts, resource, source, model, calls, ok,"
        " tokens_in, tokens_out, tokens, usd) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (time.time(), resource, str(source)[:80], str(model)[:120], max(1, int(calls)),
         None if ok is None else int(bool(ok)), _count(tokens_in), _count(tokens_out),
         _count(tokens), _money(usd)))
    conn.commit()


def record(app_state_path, resource: str, **fields) -> None:
    """File one use. Never raises: a meter that could fail a run is not one."""
    if app_state_path is None or resource not in RESOURCES:
        return
    try:
        from app.web import state

        with _lock:
            conn = state.connect(Path(app_state_path))
            try:
                record_on(conn, resource, **fields)
            finally:
                conn.close()
    except Exception:  # noqa: BLE001 - see the docstring
        return


def _total(values: list):
    """A sum over the values that were counted, or `None` when none were."""
    counted = [one for one in values if one is not None]
    return sum(counted) if counted else None


def _window(rows: list[sqlite3.Row]) -> dict:
    tokens_in = _total([row["tokens_in"] for row in rows])
    tokens_out = _total([row["tokens_out"] for row in rows])
    tokens = _total([row["tokens"] if row["tokens"] is not None
                     else (row["tokens_in"] + row["tokens_out"]
                           if row["tokens_in"] is not None and row["tokens_out"] is not None else None)
                     for row in rows])
    usd = _total([row["usd"] for row in rows])
    judged = [row for row in rows if row["ok"] is not None]
    return {
        "calls": sum(int(row["calls"]) for row in rows),
        "tokens_in": tokens_in, "tokens_out": tokens_out, "tokens": tokens,
        "usd": round(usd, 6) if usd is not None else None,
        "rows_priced": sum(1 for row in rows if row["usd"] is not None),
        "rows_tokenised": sum(1 for row in rows if row["tokens"] is not None
                              or (row["tokens_in"] is not None and row["tokens_out"] is not None)),
        "rows": len(rows),
        "misses": sum(1 for row in judged if not row["ok"]) if judged else None,
    }


def limits(conn) -> dict:
    """The windows each coding agent last reported, with when it said so."""
    from app.web import state

    stored = state.all_settings(conn).get(LIMITS_KEY)
    return stored if isinstance(stored, dict) else {}


def save_limits(app_state_path, agent: str, rows: list[dict]) -> None:
    """Remember what `agent` said about its windows. Never raises."""
    if app_state_path is None or not rows:
        return
    try:
        from app.web import state

        with _lock:
            conn = state.connect(Path(app_state_path))
            try:
                kept = limits(conn)
                mine: dict = kept[agent] if isinstance(kept.get(agent), dict) else {}
                for row in rows:
                    mine[str(row["window"])] = {key: row.get(key) for key in
                                               ("used", "status", "resets_at", "overage", "seen_at")}
                kept[agent] = mine
                state.put_settings(conn, {LIMITS_KEY: kept})
            finally:
                conn.close()
    except Exception:  # noqa: BLE001 - see `record`
        return


def meters(conn, now: float | None = None) -> dict:
    """Every resource, over every rolling window, and what each agent last said.

    A resource with no rows at all is `used: false`, so the screen can leave it
    out instead of drawing a meter that reads zero.
    """
    now = time.time() if now is None else now
    try:
        conn.executescript(_SCHEMA)
    except sqlite3.Error:
        pass
    rows = conn.execute("SELECT * FROM usage_events WHERE ts >= ? ORDER BY ts",
                        (now - max(WINDOWS.values()),)).fetchall()
    ever = {row["resource"] for row in conn.execute("SELECT DISTINCT resource FROM usage_events")}
    out: dict[str, dict] = {}
    for resource in RESOURCES:
        mine = [row for row in rows if row["resource"] == resource]
        windows = {name: _window([row for row in mine if row["ts"] >= now - span])
                   for name, span in WINDOWS.items()}
        by_source: dict[tuple[str, str], list] = {}
        for row in mine:
            if row["ts"] >= now - WINDOWS["7d"]:
                by_source.setdefault((row["source"], row["model"]), []).append(row)
        out[resource] = {
            "used": resource in ever,
            "windows": windows,
            "by_source": sorted(
                ({"source": source, "model": model, **_window(group)}
                 for (source, model), group in by_source.items()),
                key=lambda item: -item["calls"]),
        }
    out["cli_agent"]["limits"] = limits(conn)
    return {"as_of": round(now), "windows": list(WINDOWS), "resources": out}


def turn_usage(app_state_path, agent: Mapping, meter) -> None:
    """File what one chat turn used, from the turn's own meter."""
    if not getattr(meter, "calls", 0):
        return
    split = meter.split == meter.calls
    record(app_state_path, resource_of(str(agent.get("id") or "")),
           source=str(agent.get("id") or agent.get("label") or ""), model=str(agent.get("model") or ""),
           calls=meter.calls,
           tokens_in=meter.measured_in if split else None,
           tokens_out=meter.measured_out if split else None,
           tokens=meter.measured_tokens if meter.tokenized == meter.calls else None,
           usd=meter.measured_usd if meter.priced else None)

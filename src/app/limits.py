"""What a coding agent says about its own usage windows, kept as it said it.

A subscription coding agent has no price per token. What it has is a window:
so much use in the last five hours and so much in the last week, and the agent
itself says how far into each window the reader is. Claude Code prints that
inside the stream of every run it makes (`rate_limit_event`), and until now
Kriko threw the line away as chatter.

**Nothing here is worked out.** A window is shown only with the numbers the
agent reported: how much of it is used, when it resets, whether the agent called
it `allowed`, `allowed_warning` or `rejected`. An agent that reports a status
and no figure keeps its status and no figure. Nothing is estimated from tokens,
because a token count cannot say how much of a plan is left, and a made-up
"left" is the one number a reader must never be given.

**The line is read once and remembered with its time**, so the screen can say
"as of 14 minutes ago". The agent reports on its own runs; use outside Kriko is
not visible here and the screen says so.

The module has no dependencies, so the provider layer can call it. A sink,
registered by the web app, decides where the rows are kept.
"""

import re
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime

#: The windows an agent may name, and the words the reader sees for each.
#: A name not listed is kept and shown by its own words, never dropped.
WINDOW_WORDS = {
    "five_hour": "5 hours",
    "seven_day": "Week",
    "seven_day_opus": "Week, Opus",
    "seven_day_sonnet": "Week, Sonnet",
    "overage": "Extra usage",
}

STATUSES = ("allowed", "allowed_warning", "rejected")

_name = re.compile(r"[^a-z0-9_]+")


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fraction(info: Mapping) -> float | None:
    """How much of the window is used, 0 to 1, or `None` when it was not said.

    `utilization` is a fraction in the stream; `used_percentage` is a percent
    in the status line's JSON. A `utilization` above 1 can only be a percent.
    """
    percent = _number(info.get("used_percentage"))
    if percent is not None:
        return min(1.0, max(0.0, percent / 100.0))
    value = _number(info.get("utilization"))
    if value is None or value < 0:
        return None
    return min(1.0, value if value <= 1.0 else value / 100.0)


def _epoch(value) -> float | None:
    """A reset time as epoch seconds. Seconds, milliseconds and ISO all appear."""
    number = _number(value)
    if number is not None:
        if number <= 0:
            return None
        return number / 1000.0 if number > 1e11 else number
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def parse(event: Mapping) -> list[dict]:
    """The windows one `rate_limit_event` reports, as rows, or `[]`.

    Each row: `window`, `used` (0 to 1 or `None`), `status`, `resets_at`
    (epoch seconds or `None`), `overage` (bool or `None`). An event that names
    no window, no figure and no status says nothing and returns nothing.
    """
    if not isinstance(event, Mapping):
        return []
    info = event.get("rate_limit_info") or event.get("rateLimitInfo")
    if not isinstance(info, Mapping):
        info = event if ("rateLimitType" in event or "rate_limit_type" in event) else {}
    if not info:
        return []
    window = str(info.get("rateLimitType") or info.get("rate_limit_type") or info.get("window") or "")
    window = _name.sub("_", window.strip().lower()).strip("_")[:32]
    status = str(info.get("status") or "").strip().lower()
    status = status if status in STATUSES else ""
    used = _fraction(info)
    resets = _epoch(info.get("resetsAt") if "resetsAt" in info else info.get("resets_at", info.get("resetAt")))
    overage = info.get("isUsingOverage", info.get("is_using_overage"))
    if not (window or used is not None or status):
        return []
    return [{"window": window or "window", "used": used, "status": status, "resets_at": resets,
             "overage": overage if isinstance(overage, bool) else None}]


_lock = threading.Lock()
_sink: Callable[[str, list[dict]], None] | None = None


def set_sink(sink: Callable[[str, list[dict]], None] | None) -> None:
    """Where the rows go. The web app registers one; with none, a line is read and dropped."""
    global _sink
    with _lock:
        _sink = sink


def observe(agent: str, event: Mapping) -> list[dict]:
    """Read one event from `agent` and hand its windows to the sink. Never raises.

    A reader of limits that could break a run would be the reason the run
    failed, so every failure here is swallowed.
    """
    try:
        rows = parse(event)
        sink = _sink
        if rows and sink is not None:
            stamp = round(time.time())
            sink(agent, [{**row, "seen_at": stamp} for row in rows])
        return rows
    except Exception:  # noqa: BLE001 - see the docstring
        return []

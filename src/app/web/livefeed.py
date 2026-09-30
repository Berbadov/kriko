"""A running job's log, as the events a reader watches (B176).

The log is prose for a person reading it top to bottom. The Run screen's dark
panel wants the same lines as things: *a source was read*, *a finding was
kept*, *a search ran* — so each can be drawn with its own mark and counted,
instead of every line looking like every other line in a terminal dump.

Derived from the log rather than stored beside it, for the reason
`_with_attention` gives: a second copy is a second thing to keep in step. The
shapes matched here are the ones the narrator (`providers.harness._tool_line`,
`narrate`) and `tasks.py` write, and `tests/test_live_feed.py` builds its input
from the narrator's own output, so a reworded line fails a test instead of
quietly turning the panel into a list of "notes".
"""

import re

#: The most events one payload carries. The log itself is capped at
#: `harness.MAX_NARRATED` lines; this keeps a job list of fifty live rows from
#: each shipping a full transcript a second time.
KEEP = 60

#: Ordered: the first match wins. Each entry is (kind, pattern). A closed
#: vocabulary of *event kinds*, not of anything a pack or a site knows.
_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("problem", re.compile(r"^(a tool call failed|refused\b|left out\b|stopped:)", re.I)),
    ("finding", re.compile(r"^(kept\b|wrote\b)", re.I)),
    ("source", re.compile(r"^(fetched\b|read through the page reader\b)", re.I)),
    ("search", re.compile(r"^(searched\b|query:)", re.I)),
)


def classify(line: str) -> dict[str, str] | None:
    """One log line as `{"kind", "text"}`, or `None` for an empty one."""
    text = line.strip()
    if not text:
        return None
    for kind, pattern in _SHAPES:
        if pattern.match(text):
            return {"kind": kind, "text": text}
    return {"kind": "note", "text": text}


def feed_of(log: str, keep: int = KEEP) -> list[dict[str, str]]:
    """The last `keep` events in `log`.

    A narrated line may hold several actions joined by `"; "` (one assistant
    message with two tool calls), and each is its own event here: two sources
    read are two sources, however the CLI batched them.
    """
    events: list[dict[str, str]] = []
    for raw in str(log or "").splitlines():
        for part in raw.split("; "):
            event = classify(part)
            if event is not None:
                events.append(event)
    return events[-keep:]

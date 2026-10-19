"""New chat and Recent chats: a delete asks first, and opening a chat writes nothing.

A chat is the reader's own words and the answers they cost. The rail deletes
one only on the second press, and a chat that is being answered is never
removed by the window (the engine refuses it with 409, and the window shows
that answer instead of hiding it). Opening a chat only reads.
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[3] / "kriko-ui" / "src"
RAIL = (UI / "ui" / "RailChats.tsx").read_text(encoding="utf-8")
THREADS = (UI / "engine" / "threads.ts").read_text(encoding="utf-8")
LIVE = (UI / "engine" / "live.ts").read_text(encoding="utf-8")
ROUTES = (
    Path(__file__).resolve().parents[1] / "web" / "routers" / "chat.py"
).read_text(encoding="utf-8")


def test_a_delete_is_wired_after_the_question():
    assert RAIL.count("void remove(row.id)") == 1
    assert RAIL.index("Delete?") < RAIL.index("void remove(row.id)")
    # The row's trash button only opens the question; the delete is the second press.
    assert "setDoing({ id: row.id, what: 'delete' })" in RAIL


def test_a_failed_delete_is_shown_not_swallowed():
    assert "setProblem(error instanceof Error" in THREADS
    assert "{(problem || note) &&" in RAIL


def test_opening_a_chat_only_reads():
    start = LIVE.index("const open = useCallback(")
    body = LIVE[start : LIVE.index("return { run, turns", start)]
    assert "post(" not in body.replace("post(`/api/jobs", "")
    assert "del(" not in body


def test_the_routes_are_the_ones_the_engine_serves():
    for route in ('"/threads"', '"/threads/{thread_id}"', '"/threads/{thread_id}/messages"'):
        assert route in ROUTES, route
    assert re.search(r"/api/chat/threads/\$\{seg\(id\)\}", THREADS + LIVE)

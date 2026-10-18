"""A saved check is the reader's own work, so deleting one takes two presses.

The History panel's delete button only asks; the second button, labelled
Delete, is the one that reaches the engine. A single-press delete beside an
"open" button that is easy to miss is how a reader loses a check they meant to
open. And a deleted check must leave the welcome page's list too, which reads
the same history through another hook.
"""

from __future__ import annotations

from pathlib import Path

UI = Path(__file__).resolve().parents[3] / "kriko-ui" / "src"
PANEL = (UI / "ui" / "panels" / "History.tsx").read_text(encoding="utf-8")
HOOK = (UI / "engine" / "history.ts").read_text(encoding="utf-8")
RECENTS = (UI / "engine" / "recents.ts").read_text(encoding="utf-8")


def test_the_x_button_asks_and_only_the_second_button_deletes():
    row = PANEL[PANEL.index("function PastRow") :]
    asks = row[row.index("onClick={onAsk}") - 120 : row.index("onClick={onAsk}") + 120]
    assert "remove" not in asks and "onDelete" not in asks
    # The only call of `remove` is inside the confirmation path.
    assert PANEL.count("remove(row.id)") == 1
    confirm = PANEL[PANEL.index("onDelete={() => {") :]
    assert "setAsking(null)" in confirm.split("}}")[0]
    assert "remove(row.id)" in confirm.split("}}")[0]
    assert "<button onClick={onDelete}>Delete</button>" in row
    assert "<button onClick={onKeep}>Keep</button>" in row


def test_a_delete_is_one_engine_call_for_one_id():
    assert HOOK.count("del(`/api/history/${seg(id)}`)") == 1


def test_a_deleted_check_leaves_the_welcome_list_too():
    assert "HISTORY_CHANGED" in HOOK and "dispatchEvent(new Event(HISTORY_CHANGED))" in HOOK
    assert "addEventListener(HISTORY_CHANGED" in RECENTS

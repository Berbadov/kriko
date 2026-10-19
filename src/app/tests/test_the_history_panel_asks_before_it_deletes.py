"""A saved check is the reader's own work, so deleting one takes two presses.

The History panel's delete button only asks; the second button, labelled
Delete, is the one that reaches the engine. A single-press delete beside an
"open" button that is easy to miss is how a reader loses a check they meant to
open. And a deleted check must leave the welcome page's list too, which reads
the same history through another hook.

**And it can be undone.** The confirm dialog asks before; the undo line answers
"not that one" after, which is the half the dialog cannot do. The engine hands
the deleted row back on `DELETE /api/history/{id}`, so the panel keeps it for
its own lifetime rather than the app keeping a trash table nobody empties.
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
    # The only call of `remove` is inside the confirmation path — and it goes
    # through `forget`, which is what keeps the returned record for the undo.
    assert PANEL.count("void forget(row)") == 1
    assert PANEL.count("await remove(row.id)") == 1
    confirm = PANEL[PANEL.index("onDelete={() => {") :]
    assert "setAsking(null)" in confirm.split("}}")[0]
    assert "void forget(row)" in confirm.split("}}")[0]
    assert "<button onClick={onDelete}>Delete</button>" in row
    assert "<button onClick={onKeep}>Keep</button>" in row


def test_the_delete_offers_an_undo_beside_it():
    """The confirm dialog asks; this is the part that lets the reader say no."""
    assert "undoLast" in PANEL and "past-undo" in PANEL
    assert "Undo" in PANEL
    # The hook hands the removed record back rather than only a boolean, which
    # is what makes the undo possible without a second fetch.
    assert "Promise<Undoable | null>" in HOOK
    assert "/api/history/restore" in HOOK


def test_a_delete_is_one_engine_call_for_one_id():
    assert HOOK.count("del<{ undo?: Undoable }>(`/api/history/${seg(id)}`)") == 1


def test_a_deleted_check_leaves_the_welcome_list_too():
    assert "HISTORY_CHANGED" in HOOK and "dispatchEvent(new Event(HISTORY_CHANGED))" in HOOK
    assert "addEventListener(HISTORY_CHANGED" in RECENTS

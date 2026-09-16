"""The one signal that a listing site changed its markup.

`adapt()` has always computed `unmapped` — every label the page carried that
no adapter rule covers — and every caller threw it away. That made the only
available warning about a site redesign the only thing nobody could see.

What it costs when it is dropped: a site renames "Motor Hacmi", the adapter
stops reading engine size, and *nothing errors*. The lookup succeeds, resolves
to a less specific subject, and returns fewer claims. From the reader's side
that is a thin pack, not a broken adapter — and from ours it is a support
thread with no evidence in it. The label was in the response the whole time.

These tests are about the mechanism and use invented labels throughout: the
generalization principle says a fix is the mechanism that catches the class,
so nothing here may depend on which sites the installed packs happen to read.
"""


import pytest

from app.web import state


@pytest.fixture()
def conn(tmp_path):
    connection = state.connect(tmp_path / "app.sqlite")
    yield connection
    connection.close()


def test_a_label_is_recorded_with_a_page_to_look_at(conn):
    state.record_unmapped(conn, "sahibinden", ["Kimden"], url="https://x/1")
    rows = state.unmapped_labels(conn)
    assert len(rows) == 1
    assert rows[0]["label"] == "Kimden"
    assert rows[0]["adapter_id"] == "sahibinden"
    assert rows[0]["seen"] == 1
    # Without a URL the author has a label and nowhere to go with it.
    assert rows[0]["sample_url"] == "https://x/1"


def test_the_same_label_twice_is_one_row_with_a_count(conn):
    """The difference between a signal and a log.

    A label on a page template appears on every listing of that type. A row
    per sighting would grow with reading volume while answering a question
    about *distinct* labels, and the count is the part that matters: a label
    seen four hundred times is a field the site actually publishes.
    """
    state.record_unmapped(conn, "a", ["Torque"], url="https://x/1")
    state.record_unmapped(conn, "a", ["Torque"], url="https://x/2")
    state.record_unmapped(conn, "a", ["Torque"], url="https://x/3")
    rows = state.unmapped_labels(conn)
    assert len(rows) == 1
    assert rows[0]["seen"] == 3
    # The newest example, because it is the one still on the site.
    assert rows[0]["sample_url"] == "https://x/3"


def test_the_same_label_on_two_sites_is_two_rows(conn):
    """Two adapters can miss the same word for unrelated reasons, and merging
    them would send an author to fix the wrong file."""
    state.record_unmapped(conn, "a", ["Renk"])
    state.record_unmapped(conn, "b", ["Renk"])
    assert len(state.unmapped_labels(conn)) == 2
    assert len(state.unmapped_labels(conn, adapter_id="a")) == 1


def test_first_seen_survives_and_last_seen_moves(conn):
    """`first_at` is what dates a site redesign; `last_at` is what says it is
    still happening. Overwriting either loses half the answer."""
    state.record_unmapped(conn, "a", ["Yeni Alan"])
    first = state.unmapped_labels(conn)[0]["first_at"]
    state.record_unmapped(conn, "a", ["Yeni Alan"])
    row = state.unmapped_labels(conn)[0]
    assert row["first_at"] == first
    assert row["last_at"] >= first


def test_one_odd_page_cannot_bury_the_recurring_labels(conn):
    """A page whose markup changed wholesale, or one an adapter matched by
    mistake, can carry hundreds of labels. That is one signal, not hundreds."""
    state.record_unmapped(conn, "a", [f"Label {i}" for i in range(500)])
    assert len(state.unmapped_labels(conn, limit=1000)) == state.MAX_UNMAPPED_PER_LOOKUP


def test_a_paragraph_that_landed_in_a_label_is_truncated(conn):
    state.record_unmapped(conn, "a", ["x" * 5000])
    assert len(state.unmapped_labels(conn)[0]["label"]) == state.MAX_LABEL_CHARS


def test_blank_labels_are_not_rows(conn):
    assert state.record_unmapped(conn, "a", ["", "   ", chr(10)]) == 0
    assert state.unmapped_labels(conn) == []


def test_an_adapterless_lookup_records_nothing(conn):
    """There is no adapter to fix, so there is no signal — and an empty
    `adapter_id` would collect every site's labels into one bucket."""
    assert state.record_unmapped(conn, "", ["Kimden"]) == 0


def test_the_newest_label_is_first(conn):
    """Recency before frequency.

    A label that appeared today might mean the site changed this week. One
    seen four hundred times over six months is a known gap somebody already
    decided not to map — and a list ordered by count would show that one
    forever and the new one never.
    """
    state.record_unmapped(conn, "a", ["Old"])
    for _ in range(50):
        state.record_unmapped(conn, "a", ["Old"])
    conn.execute("UPDATE unmapped_labels SET last_at = '2020-01-01T00:00:00'")
    state.record_unmapped(conn, "a", ["New"])
    assert [r["label"] for r in state.unmapped_labels(conn)] == ["New", "Old"]


def test_a_dismissed_label_comes_back_if_it_recurs(conn):
    """The honest behaviour, and the reason dismissal is a delete rather than
    a flag: "I said I did not care and it is still happening" is a different
    fact from "I said I did not care", and only the first is worth showing."""
    state.record_unmapped(conn, "a", ["Takasa Uygun"])
    assert state.forget_unmapped(conn, "a", "Takasa Uygun") is True
    assert state.unmapped_labels(conn) == []
    assert state.forget_unmapped(conn, "a", "Takasa Uygun") is False

    state.record_unmapped(conn, "a", ["Takasa Uygun"])
    rows = state.unmapped_labels(conn)
    assert len(rows) == 1
    # A fresh count, not the old one resumed: the dismissal reset the clock.
    assert rows[0]["seen"] == 1


def test_the_table_is_the_interfaces_and_not_the_engines(tmp_path):
    """Where this may not live.

    A pack's adapter is content; what a reader's browsing revealed about a
    site is not. If this table were in the engine's schema, uninstalling a
    pack would drop the evidence that its adapter needs fixing, and a label
    someone happened to browse past could move a `content_digest`.
    """
    from kriko.store.db import SCHEMA_PATH

    assert "unmapped_labels" not in SCHEMA_PATH.read_text()
    assert "unmapped_labels" in state.SCHEMA


def test_clearing_history_does_not_erase_the_signal(conn):
    """Its own table rather than a column on `lookups`, so the two lifetimes
    stay separate: a reader deleting their browsing history must not also
    delete the evidence that an adapter is broken."""
    lookup_id = state.record_lookup(
        conn, source="extension", label="a listing",
        request={"url": "https://x/1"}, response={},
    )
    state.record_unmapped(conn, "a", ["Kimden"], url="https://x/1")
    assert state.delete_lookup(conn, lookup_id) is True
    assert len(state.unmapped_labels(conn)) == 1

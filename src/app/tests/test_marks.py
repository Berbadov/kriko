"""What the reader thought of a claim, and where it is allowed to live.

The engine has no authority to retract a claim, so a reader who learns from a
mechanic that one is wrong had nowhere to put that — the single best signal
this project can receive was being dropped on the floor. These tests hold the
two things that make recording it safe: it changes no pack, and it survives
the pack it is about.
"""

import pytest
from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings(
            store_path=tmp_path / "k.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "a.jsonl",
        )
    )
    with TestClient(app) as client:
        yield client


def _mark(client, **kw):
    body = {"pack_id": "p", "claim_id": "c1", "verdict": "wrong", **kw}
    return client.post("/api/marks", json=body)


def test_the_counts_are_present_before_anything_is_marked(client):
    """A dashboard that changes shape when the first row arrives is a
    dashboard that was never tested empty."""
    payload = client.get("/api/marks").json()
    assert payload["items"] == []
    assert payload["counts"] == {"useful": 0, "wrong": 0, "not_applicable": 0}


def test_a_mark_carries_the_readers_own_words(client):
    """The note is the valuable field. "My mechanic says the belt was done at
    90k" is the sentence a later research pass actually wants."""
    row = _mark(client, note="mechanic says mine was replaced").json()
    assert row["verdict"] == "wrong"
    assert row["note"] == "mechanic says mine was replaced"
    assert client.get("/api/marks").json()["counts"]["wrong"] == 1


def test_changing_your_mind_replaces_rather_than_accumulates(client):
    """One reader, one claim, one opinion — the current one."""
    _mark(client, verdict="wrong")
    _mark(client, verdict="not_applicable", note="true of the DSG, mine is manual")
    payload = client.get("/api/marks").json()
    assert len(payload["items"]) == 1
    assert payload["counts"] == {"useful": 0, "wrong": 0, "not_applicable": 1}


def test_the_first_time_is_remembered_across_a_change_of_mind(client):
    first = _mark(client).json()["created_at"]
    assert _mark(client, verdict="useful").json()["created_at"] == first


def test_an_invented_verdict_is_refused(client):
    """Three answers to "was this any use". A fourth is a product decision,
    not something a caller gets to introduce."""
    assert _mark(client, verdict="probably").status_code == 422
    assert client.get("/api/marks?verdict=probably").status_code == 422


def test_unmarking_twice_is_not_an_error(client):
    """Pressing the same button again is how a reader takes it back, and the
    end state is what they asked for either way."""
    _mark(client)
    assert client.delete("/api/marks/p/c1").json() == {"removed": True}
    assert client.delete("/api/marks/p/c1").json() == {"removed": False}


def test_a_mark_stays_readable_after_the_pack_is_gone(client):
    """`subject_id` and `title` are copied in rather than joined out.

    A pack updates weekly and can be uninstalled. A mark whose claim row has
    since gone must still be readable, or the reader's own notes become a list
    of hashes.
    """
    _mark(client, title="Timing chain tensioner wear", subject_id="s1")
    row = client.get("/api/marks").json()["items"][0]
    assert row["title"] == "Timing chain tensioner wear"
    assert row["subject_id"] == "s1"


def test_a_mark_is_interface_state_and_never_touches_the_engine(client, tmp_path):
    """An opinion must not change a pack's `content_digest`, and it must not
    vanish with the pack. Both follow from which file it is written to.

    The strongest available form of the assertion: marking twice does not so
    much as *create* the engine's store, let alone add a table to it.
    """
    _mark(client)
    _mark(client, claim_id="c2", verdict="useful")

    assert not (tmp_path / "k.sqlite").exists()

    import sqlite3

    tables = {
        row[0]
        for row in sqlite3.connect(tmp_path / "app.sqlite").execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "claim_marks" in tables

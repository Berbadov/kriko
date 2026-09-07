"""What the reader thought of a claim, and where it is allowed to live.

The engine has no authority to retract a claim, so a reader who learns from a
mechanic that one is wrong had nowhere to put that — the single best signal
this project can receive was being dropped on the floor. These tests hold the
two things that make recording it safe: it changes no pack, and it survives
the pack it is about.
"""

import pytest
from fastapi.testclient import TestClient

from app.web import state
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


# ── what a mark feeds ────────────────────────────────────────────────────


def test_wrong_and_not_mine_land_in_different_queues(tmp_path):
    """The two verdicts are failures of different systems, so they are two
    queues. Merging them would hide which half needs the fix."""
    conn = state.connect(tmp_path / "app.sqlite")
    state.mark_claim(
        conn, pack_id="p", claim_id="c1", verdict="wrong",
        subject_id="s1", note="my mechanic says otherwise",
    )
    state.mark_claim(
        conn, pack_id="p", claim_id="c2", verdict="not_applicable", subject_id="s2",
    )
    state.mark_claim(conn, pack_id="p", claim_id="c3", verdict="useful", subject_id="s3")

    signals = state.mark_signals(conn)
    assert [item["subject_id"] for item in signals["research"]] == ["s1"]
    assert [item["subject_id"] for item in signals["matching"]] == ["s2"]
    # A useful mark is not a problem to be queued.
    assert all(
        item["subject_id"] != "s3"
        for queue in signals.values()
        for item in queue
    )
    # The reader's own words travel with the queue: they are the most valuable
    # field on a mark and the thing a later research pass wants.
    assert signals["research"][0]["notes"] == ["my mechanic says otherwise"]


def test_a_matching_problem_names_the_door_the_subject_arrived_through(tmp_path):
    """A subject only ever reached from a listing points at the adapter.

    `not mine` is upstream of the claim — identity extraction, or a gate that
    is too broad — and which door it came through is what separates those.
    """
    conn = state.connect(tmp_path / "app.sqlite")
    state.record_lookup(
        conn, source="url", label="a listing", request={},
        response={"claims": [{"claim_id": "c1", "subject_id": "s2"}]},
    )
    state.record_lookup(
        conn, source="form", label="typed in", request={},
        # A subject that resolved with nothing to say is still a match the
        # adapter made, and `subjects` is the only place it appears.
        response={"claims": [], "subjects": [{"subject_id": "s9"}]},
    )
    state.mark_claim(
        conn, pack_id="p", claim_id="c1", verdict="not_applicable", subject_id="s2",
    )
    state.mark_claim(
        conn, pack_id="p", claim_id="c9", verdict="not_applicable", subject_id="s9",
    )
    by_subject = {item["subject_id"]: item for item in state.mark_signals(conn)["matching"]}
    assert by_subject["s2"]["sources"] == {"url": 1}
    assert by_subject["s9"]["sources"] == {"form": 1}


def test_the_queue_is_worst_first_and_counts_the_claims(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    for claim_id in ("a", "b"):
        state.mark_claim(
            conn, pack_id="p", claim_id=claim_id, verdict="wrong", subject_id="loud",
        )
    state.mark_claim(conn, pack_id="p", claim_id="c", verdict="wrong", subject_id="quiet")
    research = state.mark_signals(conn)["research"]
    assert [(item["subject_id"], item["count"]) for item in research] == [
        ("loud", 2),
        ("quiet", 1),
    ]
    assert sorted(research[0]["claim_ids"]) == ["a", "b"]


def test_the_signals_endpoint_serves_both_queues(client):
    client.post(
        "/api/marks",
        json={"pack_id": "p", "claim_id": "c1", "verdict": "wrong", "subject_id": "s1"},
    )
    body = client.get("/api/marks/signals").json()
    assert body["research"][0]["subject_id"] == "s1"
    assert body["matching"] == []

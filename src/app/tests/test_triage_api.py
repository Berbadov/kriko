"""The reader's own marks on an answer: a checkmark and what the seller said.

A checkmark records *that* a risk was dealt with; the note records *how it
went*. "Belt done at 140k, seller has no receipt" is the sentence that turns a
report into a record of a negotiation, and it is what they will want on the
second visit — so it is durable interface state, in app.sqlite, exactly like
the checkmark beside it.

Both halves come back in one request on purpose: two calls for one screen means
a report that paints its checkboxes and then, a beat later, its notes.
"""

import pytest
from fastapi.testclient import TestClient

from app.web import state
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def client(tmp_path):
    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
            )
        )
    )


def test_a_note_survives_the_request_that_wrote_it(client):
    written = client.post(
        "/api/lookups/L1/notes",
        json={"claim_key": "c1", "note": "belt done at 140k, no receipt"},
    )
    assert written.status_code == 200
    assert written.json()["notes"] == {"c1": "belt done at 140k, no receipt"}

    read = client.get("/api/lookups/L1/triage").json()
    assert read["notes"]["c1"] == "belt done at 140k, no receipt"


def test_triage_returns_both_halves_together(client):
    client.post("/api/lookups/L1/checked", json={"claim_key": "c1", "checked": True})
    client.post("/api/lookups/L1/notes", json={"claim_key": "c2", "note": "said no"})
    both = client.get("/api/lookups/L1/triage").json()
    assert both["checked"] == ["c1"]
    assert both["notes"] == {"c2": "said no"}


def test_an_emptied_note_is_gone_rather_than_stored_blank(client):
    client.post("/api/lookups/L1/notes", json={"claim_key": "c1", "note": "something"})
    cleared = client.post("/api/lookups/L1/notes", json={"claim_key": "c1", "note": "  "})
    # Not `{"c1": ""}`: an empty string is a note the UI would open a field for
    # and the reader never wrote.
    assert cleared.json()["notes"] == {}


def test_notes_are_scoped_to_one_answer(client):
    client.post("/api/lookups/L1/notes", json={"claim_key": "c1", "note": "on L1"})
    assert client.get("/api/lookups/L2/triage").json()["notes"] == {}


def test_a_pasted_listing_cannot_become_a_history_row(client):
    refused = client.post(
        "/api/lookups/L1/notes", json={"claim_key": "c1", "note": "x" * 4001}
    )
    assert refused.status_code == 422


def test_deleting_an_answer_takes_its_notes_with_it(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    lookup_id = state.record_lookup(
        conn, source="ask", label="one", request={}, response={"claims": []}
    )
    state.set_note(conn, lookup_id, "c1", "said done")
    state.delete_lookup(conn, lookup_id)
    # Otherwise a new answer that happened to reuse the id would inherit
    # somebody else's negotiation.
    assert state.notes(conn, lookup_id) == {}

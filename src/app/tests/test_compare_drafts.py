"""B183: a comparison is a named draft the reader can reopen and edit.

*"Compare: work like draft papers, each draft saved and helping the user
choose"*. The drafts are app state in `app.sqlite`, not knowledge.
"""

import pytest
from fastapi.testclient import TestClient

from app.web import state
from app.web.app import create_app
from app.web.settings import Settings
from kriko.store.db import connect


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )
    return TestClient(create_app(settings)), settings


def test_a_draft_is_saved_listed_renamed_and_deleted(client):
    http, _ = client
    made = http.post("/api/compare-drafts",
                     json={"name": "  Shortlist  ", "lookup_ids": ["a", "b", "a", ""]}).json()
    assert made["name"] == "Shortlist"
    assert made["lookup_ids"] == ["a", "b"]

    assert http.get("/api/compare-drafts").json()["items"] == [made]

    edited = http.put(f"/api/compare-drafts/{made['draft_id']}",
                      json={"name": "Final two", "lookup_ids": ["b", "c"]}).json()
    assert edited["draft_id"] == made["draft_id"]
    assert (edited["name"], edited["lookup_ids"]) == ("Final two", ["b", "c"])
    assert len(http.get("/api/compare-drafts").json()["items"]) == 1

    assert http.delete(f"/api/compare-drafts/{made['draft_id']}").status_code == 200
    assert http.get("/api/compare-drafts").json()["items"] == []


def test_a_draft_needs_a_name_and_holds_at_most_four_checks(client):
    http, _ = client
    assert http.post("/api/compare-drafts",
                     json={"name": "  ", "lookup_ids": ["a"]}).status_code == 422
    made = http.post("/api/compare-drafts", json={
        "name": "Many", "lookup_ids": list("abcdef")}).json()
    assert made["lookup_ids"] == list("abcd")


def test_editing_or_deleting_a_draft_that_is_gone_says_so(client):
    http, _ = client
    assert http.put("/api/compare-drafts/nope",
                    json={"name": "x", "lookup_ids": []}).status_code == 404
    assert http.delete("/api/compare-drafts/nope").status_code == 404


def test_drafts_live_in_the_app_file_and_not_in_the_knowledge_store(client):
    http, settings = client
    http.post("/api/compare-drafts", json={"name": "Kept", "lookup_ids": ["a"]})
    store = connect(settings.store_path)
    tables = {r[0] for r in store.execute("SELECT name FROM sqlite_master")}
    store.close()
    assert "compare_drafts" not in tables
    app_db = state.connect(settings.app_state_path)
    assert app_db.execute("SELECT COUNT(*) FROM compare_drafts").fetchone()[0] == 1
    app_db.close()

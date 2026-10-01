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


def test_a_follow_up_question_is_stored_listed_and_refused_for_a_gone_draft(client):
    http, _ = client
    made = http.post("/api/compare-drafts",
                     json={"name": "Shortlist", "lookup_ids": ["a", "b"]}).json()
    asked = http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                      json={"question": "  which of these two  is cheaper to fix? "}).json()
    assert asked["question"] == "which of these two is cheaper to fix?"
    assert asked["answer"] == "" and asked["job_id"]
    listed = http.get(f"/api/compare-drafts/{made['draft_id']}/questions").json()
    assert [q["question"] for q in listed["items"]] == [asked["question"]]
    assert http.post("/api/compare-drafts/nope/questions",
                     json={"question": "x"}).status_code == 404
    assert http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                     json={"question": "   "}).status_code == 422


def _one_lookup(settings, label, response) -> str:
    """Record one stored answer and return the id it was given.

    `record_lookup` mints its own id, so a test cannot name one the way the
    extension's door does; the draft is built from what it returns.
    """
    conn = state.connect(settings.app_state_path)
    try:
        return state.record_lookup(conn, source="ask", label=label,
                                   request={}, response=response)
    finally:
        conn.close()


def test_the_job_handler_answers_a_question_and_writes_it_on_the_row(
        client, monkeypatch):
    http, settings = client
    from app.web import tasks
    a1 = _one_lookup(settings, "One", {
        "claims": [{"claim_id": "c", "pack_id": "p", "title": "Timing chain",
                    "body": "Stretches early.", "severity": "high"}],
        "context": {"mileage": "120000"},
        "context_units": {"mileage": "km"}})
    b2 = _one_lookup(settings, "Two", {"claims": [], "context": {}})
    made = http.post("/api/compare-drafts",
                     json={"name": "Two cars", "lookup_ids": [a1, b2]}).json()
    asked = http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                      json={"question": "which has the cheaper known fix?"}).json()

    class _Researcher:
        def ask(self, prompt):
            self.prompt = prompt
            return " The first one: the chain is a known, cheap fix. "

    researcher = _Researcher()
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a, **k: True)
    monkeypatch.setattr(tasks, "_local_asker", lambda *a, **k: researcher)

    class _Progress:
        job_id = "job-1"
        def log(self, line): pass
        def set(self, *a, **k): pass
        def check(self): pass

    result = tasks.compare_ask(settings, {
        "draft_id": made["draft_id"], "question_id": asked["question_id"],
        "question": asked["question"]}, _Progress())
    assert result["answer"].startswith("The first one")
    assert "QUESTION: which has the cheaper known fix?" in researcher.prompt
    assert "## One" in researcher.prompt and "## Two" in researcher.prompt
    conn = state.connect(settings.app_state_path)
    stored = state.compare_questions(conn, made["draft_id"])
    conn.close()
    assert stored[0]["answer"].startswith("The first one")
    assert stored[0]["job_id"] == "job-1"


def test_a_question_about_a_shortlist_of_one_is_refused(client, monkeypatch):
    http, settings = client
    from app.web import tasks
    a1 = _one_lookup(settings, "One", {"claims": [], "context": {}})
    made = http.post("/api/compare-drafts",
                     json={"name": "One car", "lookup_ids": [a1]}).json()
    asked = http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                      json={"question": "is it any good?"}).json()
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a, **k: True)
    monkeypatch.setattr(tasks, "_local_asker",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError(
                            "no agent should have been asked")))
    with pytest.raises(ValueError, match="fewer than two"):
        tasks.compare_ask(settings, {
            "draft_id": made["draft_id"],
            "question_id": asked["question_id"],
            "question": asked["question"]}, _BareProgress())


class _BareProgress:
    job_id = "job-2"
    def log(self, line): pass
    def set(self, *a, **k): pass
    def check(self): pass


def test_the_brief_carries_the_table_and_refuses_to_invent():
    from app.web.tasks import _compare_brief
    brief = _compare_brief("which is cheaper?", [
        {"label": "One", "response": {
            "claims": [{"claim_id": "c", "pack_id": "p", "title": "Timing chain",
                        "body": "Stretches early.", "advice": "Ask for the invoice.",
                        "severity": "high"}],
            "context": {"mileage": "120000"},
            "context_units": {"mileage": "km"}}},
        {"label": "Two", "response": {"claims": [], "context": {}}},
    ])
    assert "QUESTION: which is cheaper?" in brief
    assert "## One" in brief and "## Two" in brief
    assert "[high] Timing chain: Stretches early. (advice: Ask for the invoice.)" in brief
    assert "none recorded" in brief
    assert "mileage: 120000 km" in brief
    assert "Do not invent risks" in brief

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


def test_compare_can_explicitly_choose_the_local_model(client, monkeypatch):
    http, _ = client
    made = http.post("/api/compare-drafts",
                     json={"name": "Two", "lookup_ids": ["a", "b"]}).json()
    submitted = []
    monkeypatch.setattr(http.app.state.jobs, "submit",
                        lambda kind, params: submitted.append((kind, params)) or "job-local")
    asked = http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                      json={"question": "Which has fewer known risks?",
                            "backend": "local", "harness": "local"})
    assert asked.status_code == 200
    assert submitted[0][0] == "compare_ask"
    assert submitted[0][1]["backend"] == "local"
    assert http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                     json={"question": "x", "backend": "invalid"}).status_code == 422


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
    monkeypatch.setattr(http.app.state.jobs, "submit", lambda *_: "queued-test-job")
    asked = http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                      json={"question": "which has the cheaper known fix?"}).json()

    class _Completer:
        context_chars = 12000
        model = "small:4b"
        tokens_used = 141
        tokens_in = 100
        tokens_out = 41

        def __call__(self, prompt):
            self.prompt = prompt
            return " The first one: the chain is a known, cheap fix. "

    researcher = _Completer()
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a, **k: True)
    monkeypatch.setattr(tasks, "_local_compare_completer", lambda *a, **k: researcher)
    monkeypatch.setattr(tasks, "_local_asker", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("comparison must not search or crawl")))

    class _Progress:
        job_id = "job-1"
        def log(self, line): pass
        def set(self, *a, **k): pass
        def check(self): pass

    result = tasks.compare_ask(settings, {
        "draft_id": made["draft_id"], "question_id": asked["question_id"],
        "question": asked["question"]}, _Progress())
    assert result["answer"].startswith("The first one")
    assert result["saved_checks"] == [
        {"name": "One", "risks": 1}, {"name": "Two", "risks": 0}]
    assert result["brief_chars"] == len(researcher.prompt)
    assert result["web_searches"] == 0
    assert (result["model"], result["tokens_used"], result["tokens_in"], result["tokens_out"]) == (
        "small:4b", 141, 100, 41)
    assert "QUESTION: which has the cheaper known fix?" in researcher.prompt
    assert "## One" in researcher.prompt and "## Two" in researcher.prompt
    conn = state.connect(settings.app_state_path)
    stored = state.compare_questions(conn, made["draft_id"])
    conn.close()
    assert stored[0]["answer"].startswith("The first one")
    assert stored[0]["job_id"] == "job-1"


def test_small_compare_brief_keeps_each_product_and_names_omissions():
    from app.web.tasks import _compare_brief

    answers = [
        {"label": f"Product {i}", "response": {
            "claims": [{"title": f"Risk {j}", "body": "A" * 300,
                        "severity": "high"} for j in range(20)],
            "context": {"year": 2020 + i},
        }} for i in range(4)
    ]
    brief = _compare_brief("Which has Risk 19?", answers, max_chars=4000)
    assert len(brief) <= 4000
    for i in range(4):
        assert f"## Product {i}" in brief
    assert brief.count("Risks shown:") == 4
    assert "- [high] Risk 19" in brief
    assert "recorded risks omitted from this brief" in brief

    long_question = "Which is safer? " + "detail " * 300
    bounded = _compare_brief(long_question, answers, max_chars=3000)
    assert len(bounded) <= 3000
    assert all(f"## Product {i}" in bounded for i in range(4))


def test_local_comparison_probes_only_the_model(monkeypatch, tmp_path):
    from app import localplane
    from app.web.tasks import _local_compare_completer

    probed = []

    def resolve(*args, **kwargs):
        probed.append(kwargs.get("with_search"))
        return {"ready": True, "url": "http://127.0.0.1:11434",
                "model": "a-larger-model:27b", "models": ["a-larger-model:27b"],
                "timeout": 300, "line": "Ready"}

    monkeypatch.setattr(localplane, "resolve", resolve)
    settings = type("Settings", (), {"app_state_path": tmp_path / "app.sqlite"})()
    logged = []
    progress = type("Progress", (), {"log": lambda self, line: logged.append(line)})()
    socket = _local_compare_completer(settings, {}, progress)
    assert probed == [False]
    assert socket.serving_name == "a-larger-model:27b"
    assert socket.reasoning_effort == "none"
    assert "saved checks only" in logged[0]


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


def test_a_board_is_saved_read_back_and_refused_for_a_gone_draft(client):
    http, _ = client
    made = http.post("/api/compare-drafts",
                     json={"name": "Shortlist", "lookup_ids": ["a", "b"]}).json()
    # An unmarked draft reads as an empty board, not a missing one.
    empty = http.get(f"/api/compare-drafts/{made['draft_id']}/board").json()
    assert empty == {"draft_id": made["draft_id"], "strokes": [],
                     "notes": [], "updated_at": ""}
    saved = http.put(
        f"/api/compare-drafts/{made['draft_id']}/board",
        json={"strokes": [[{"x": 1, "y": 2}, {"x": 3, "y": 4}]],
              "notes": [{"x": 10, "y": 20, "text": "this one"}]}).json()
    assert len(saved["strokes"]) == 1 and saved["notes"][0]["text"] == "this one"
    assert saved["updated_at"]
    back = http.get(f"/api/compare-drafts/{made['draft_id']}/board").json()
    assert back["strokes"] == saved["strokes"]
    assert back["notes"] == saved["notes"]
    assert http.get("/api/compare-drafts/nope/board").status_code == 404
    assert http.put("/api/compare-drafts/nope/board",
                    json={}).status_code == 404


def test_saving_a_board_replaces_it_wholesale(client):
    """Erasing is the point of a board: a stroke merged back by the save
    would resurrect what the reader just rubbed out."""
    http, _ = client
    made = http.post("/api/compare-drafts",
                     json={"name": "Shortlist", "lookup_ids": ["a", "b"]}).json()
    http.put(f"/api/compare-drafts/{made['draft_id']}/board",
             json={"strokes": [[{"x": 1}], [{"x": 2}]], "notes": [
                 {"x": 0, "y": 0, "text": "gone"}]})
    http.put(f"/api/compare-drafts/{made['draft_id']}/board",
             json={"strokes": [], "notes": []})
    back = http.get(f"/api/compare-drafts/{made['draft_id']}/board").json()
    assert back["strokes"] == [] and back["notes"] == []


def test_the_brief_carries_each_claims_sources():
    """The reader: "in compare agents do not read the sources of the
    knowledge." Each claim's recorded pages and quotes reach the agent, in
    the full brief and, where it fits, in a small model's compact one."""
    from app.web.tasks import _compare_brief
    claim = {"title": "Timing chain", "body": "Stretches early.", "severity": "high",
             "sources": [{"url": "https://example.org/thread", "quote": "the chain rattled at 80k",
                          "tier": "forum_ugc"}]}
    answers = [{"label": "One", "response": {"claims": [claim], "context": {}}},
               {"label": "Two", "response": {"claims": [], "context": {}}}]
    full = _compare_brief("which is safer?", answers)
    assert 'source: https://example.org/thread [forum_ugc] "the chain rattled at 80k"' in full
    assert "cite the recorded source" in full
    compact = _compare_brief("which is safer?", answers, max_chars=4000)
    assert "https://example.org/thread" in compact

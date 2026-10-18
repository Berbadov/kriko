"""The chat endpoints, and the job that answers a message, end to end.

The runner's thread pool is stubbed at the router (a posted message must submit
a `chat_ask` job, not run one). The handler itself is run directly against a
real job row with a scripted local model, so the answer and its steps are
written where the screen will read them.
"""

import pytest
from fastapi.testclient import TestClient

from app.web import state, tasks
from app.web.app import create_app
from app.web.jobs import Progress, _overlap, claims
from app.web.settings import Settings


@pytest.fixture
def paths(tmp_path):
    return Settings(store_path=tmp_path / "knowledge.sqlite",
                    app_state_path=tmp_path / "app.sqlite",
                    analysis_log_path=tmp_path / "analysis.jsonl")


@pytest.fixture
def http(paths, monkeypatch):
    app = create_app(paths)
    submitted = []

    def submit(kind, params):
        submitted.append((kind, params))
        return f"job{len(submitted):03d}"

    monkeypatch.setattr(app.state.jobs, "submit", submit)
    client = TestClient(app)
    client.submitted = submitted
    return client


def test_the_sources_endpoint_names_the_records_and_holds_no_data(http):
    items = http.get("/api/chat/sources").json()["items"]
    assert {item["name"] for item in items} >= {"product_match", "catalogue_search"}
    assert all(set(item) == {"name", "description", "args"} for item in items)


def test_a_thread_round_trip(http):
    thread = http.post("/api/chat/threads", json={}).json()
    assert thread["title"] == ""
    assert [row["thread_id"] for row in http.get("/api/chat/threads").json()["items"]] == [
        thread["thread_id"]]
    assert http.get(f"/api/chat/threads/{thread['thread_id']}/messages").json() == {"items": []}
    assert http.delete(f"/api/chat/threads/{thread['thread_id']}").json() == {
        "deleted": thread["thread_id"]}
    assert http.get("/api/chat/threads").json()["items"] == []
    assert http.delete(f"/api/chat/threads/{thread['thread_id']}").status_code == 404


def test_active_chat_turn_is_reconnectable_and_prevents_thread_deletion(http, paths):
    app_state = state.connect(paths.app_state_path)
    try:
        thread = state.create_chat_thread(app_state)
        job_id = state.create_job(app_state, "chat_ask", {"thread_id": thread["thread_id"]})
    finally:
        app_state.close()

    messages = http.get(f"/api/chat/threads/{thread['thread_id']}/messages").json()
    assert messages == {"items": [], "job_id": job_id}
    refused = http.delete(f"/api/chat/threads/{thread['thread_id']}")
    assert refused.status_code == 409
    assert "active chat turn" in refused.json()["detail"]

    app_state = state.connect(paths.app_state_path)
    try:
        state.finish_job(app_state, job_id, state.CANCELLED, message="stopped")
    finally:
        app_state.close()
    assert http.get(f"/api/chat/threads/{thread['thread_id']}/messages").json() == {
        "items": []}
    assert http.delete(f"/api/chat/threads/{thread['thread_id']}").status_code == 200


def test_posting_a_message_stores_it_and_starts_a_chat_turn(http):
    thread = http.post("/api/chat/threads", json={}).json()
    tid = thread["thread_id"]
    posted = http.post(f"/api/chat/threads/{tid}/messages", json={
        "text": "  I need a widget with blue paint ", "harness": "h1", "backend": "harness",
    })
    assert posted.status_code == 200
    body = posted.json()
    assert body["job_id"] == "job001" and body["kind"] == "chat_ask"
    kind, params = http.submitted[0]
    assert kind == "chat_ask"
    assert params == {"thread_id": tid, "message_id": body["message_id"],
                      "text": "I need a widget with blue paint", "harness": "h1",
                      "backend": "harness"}
    messages = http.get(f"/api/chat/threads/{tid}/messages").json()["items"]
    assert [(m["role"], m["text"]) for m in messages] == [
        ("reader", "I need a widget with blue paint")]
    assert http.get("/api/chat/threads").json()["items"][0]["title"] == (
        "I need a widget with blue paint")


def test_a_message_is_refused_before_anything_runs(http):
    tid = http.post("/api/chat/threads", json={}).json()["thread_id"]
    assert http.post("/api/chat/threads/missing/messages",
                     json={"text": "hello"}).status_code == 404
    assert http.post(f"/api/chat/threads/{tid}/messages",
                     json={"text": "   "}).status_code == 422
    assert http.post(f"/api/chat/threads/{tid}/messages",
                     json={"text": "q" * 2001}).status_code == 422
    assert http.post(f"/api/chat/threads/{tid}/messages",
                     json={"text": "ok", "backend": "cloud"}).status_code == 422
    assert http.submitted == []
    assert http.get(f"/api/chat/threads/{tid}/messages").json()["items"] == []


def test_chat_keeps_paragraphs_and_indentation_in_the_posted_message(http):
    tid = http.post("/api/chat/threads", json={}).json()["thread_id"]
    text = "Explain this:\n\n    first step\n    second step"
    response = http.post(f"/api/chat/threads/{tid}/messages", json={"text": text})
    assert response.status_code == 200
    assert http.submitted[0][1]["text"] == text
    stored = http.get(f"/api/chat/threads/{tid}/messages").json()["items"]
    assert stored[0]["text"] == text


def test_a_turn_is_shown_the_messages_said_before_its_own_question(paths):
    app_state = state.connect(paths.app_state_path)
    try:
        thread = state.create_chat_thread(app_state)
        tid = thread["thread_id"]
        first = state.add_chat_message(app_state, tid, role="reader", text="first")
        state.add_chat_message(app_state, tid, role="agent", text="reply one")
        asked = state.add_chat_message(app_state, tid, role="reader", text="second")
        before = state.chat_history(app_state, tid, before=asked["message_id"])
        assert [m["text"] for m in before] == ["first", "reply one"]
        assert state.chat_history(app_state, tid, before=first["message_id"]) == []
        assert [m["text"] for m in state.chat_history(app_state, tid, limit=1)] == ["second"]
        state.delete_chat_thread(app_state, tid)
        assert state.chat_messages(app_state, tid) == []
    finally:
        app_state.close()


def test_one_turn_at_a_time_per_conversation_and_others_run_beside_it():
    same = claims("chat_ask", {"thread_id": "t1"})
    assert _overlap(same, claims("chat_ask", {"thread_id": "t1"}))
    assert not _overlap(same, claims("chat_ask", {"thread_id": "t2"}))


def test_provider_prose_streams_are_forwarded_to_the_chat_answer():
    class Researcher:
        def __init__(self):
            self.on_text = None

    previous, answer = [], []
    codex = Researcher()
    codex.on_text = previous.append
    assert tasks._wire_codex_answer_stream(codex, "codex", answer.append)
    codex.on_text("A live sentence")
    assert previous == answer == ["A live sentence"]

    claude = Researcher()
    assert tasks._wire_codex_answer_stream(claude, "claude-code", answer.append)
    claude.on_text("Another live sentence")
    assert answer == ["A live sentence", "Another live sentence"]
    assert not tasks._wire_codex_answer_stream(object(), "unknown", answer.append)


class Completer:
    """A local model that asks for one search, then answers with a source line."""

    model = "local-test-model"

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            return ('{"need": {"product": "widget", "must": [], "prefer": []}, '
                    '"calls": [{"source": "catalogue_search", "args": {"query": "widget"}}], '
                    '"ready": true}')
        return "No widget is recorded yet. Sources: catalogue_search"


def test_the_job_writes_the_answer_and_its_steps_to_the_thread(paths, monkeypatch):
    completer = Completer()
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: True)
    monkeypatch.setattr(tasks, "_local_structured_completer", lambda *a: completer)
    app_state = state.connect(paths.app_state_path)
    thread = state.create_chat_thread(app_state)
    reader = state.add_chat_message(app_state, thread["thread_id"], role="reader",
                                    text="find a widget in my catalogue")
    job_id = state.create_job(app_state, "chat_ask", {"thread_id": thread["thread_id"]})
    progress = Progress(job_id, app_state)
    try:
        result = tasks.chat_ask(paths, {"thread_id": thread["thread_id"],
                                        "message_id": reader["message_id"],
                                        "text": "find a widget in my catalogue", "backend": "local"},
                                progress)
    finally:
        app_state.close()

    assert result["answer"] == "No widget is recorded yet."
    assert result["sources"] == ["catalogue_search"]
    assert result["agent"] == {"id": "local", "label": "Local model",
                               "model": "local-test-model"}
    assert result["steps"][0]["source"] == "catalogue_search"
    assert result["steps"][0]["state"] == "empty"

    stored = TestClient(create_app(paths)).get(
        f"/api/chat/threads/{thread['thread_id']}/messages").json()["items"]
    assert [(m["role"], m["text"]) for m in stored] == [
        ("reader", "find a widget in my catalogue"),
        ("agent", "No widget is recorded yet.")]
    assert stored[1]["sources"] == ["catalogue_search"]
    assert stored[1]["steps"][0]["label"].startswith("no rows from")
    assert stored[1]["job_id"] == job_id


def test_a_turn_with_no_packs_installed_still_answers(paths, monkeypatch):
    """A fresh install has no store file: the sources say so and nothing fails."""
    completer = Completer()
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: True)
    monkeypatch.setattr(tasks, "_local_structured_completer", lambda *a: completer)
    app_state = state.connect(paths.app_state_path)
    thread = state.create_chat_thread(app_state)
    job_id = state.create_job(app_state, "chat_ask", {})
    try:
        result = tasks.chat_ask(paths, {"thread_id": thread["thread_id"], "message_id": "",
                                        "text": "find a widget in my catalogue", "backend": "local"},
                                Progress(job_id, app_state))
    finally:
        app_state.close()
    assert not paths.store_path.exists()
    assert result["steps"][0]["state"] == "empty"
    assert result["steps"][0]["detail"] == "the engine store has no packs yet"
    assert result["answer"] == "No widget is recorded yet."


def test_the_chat_job_wires_web_search_and_saves_fetched_urls(paths, monkeypatch):
    class WebCompleter:
        model = "local-test-model"

        def __init__(self):
            self.prompts = []

        def __call__(self, prompt):
            self.prompts.append(prompt)
            return ("The fetched maker page lists the purifier's CADR. Check room size "
                    "and noise claims on the product page.")

    completer = WebCompleter()
    searched, fetched = [], []

    def search(query, limit):
        searched.append((query, limit))
        return [{"title": "Maker product page", "url": "https://maker.example/purifier",
                 "site": "maker.example"}]

    def read(url):
        fetched.append(url)
        return "Air purifier CADR 300 m³/h."

    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: True)
    monkeypatch.setattr(tasks, "_local_structured_completer", lambda *a: completer)
    monkeypatch.setattr(tasks, "_chat_web_accessors", lambda *a: (search, read))
    app_state = state.connect(paths.app_state_path)
    thread = state.create_chat_thread(app_state)
    reader = state.add_chat_message(app_state, thread["thread_id"], role="reader",
                                    text="Find a quiet air purifier for a small bedroom")
    job_id = state.create_job(app_state, "chat_ask", {"thread_id": thread["thread_id"]})
    try:
        result = tasks.chat_ask(
            paths,
            {"thread_id": thread["thread_id"], "message_id": reader["message_id"],
             "text": reader["text"], "backend": "local"},
            Progress(job_id, app_state),
        )
        stored = state.chat_messages(app_state, thread["thread_id"])[-1]
    finally:
        app_state.close()

    assert searched == [("a quiet air purifier for a small bedroom", 5)]
    assert fetched == ["https://maker.example/purifier"]
    # One short call writes the search words; the last call answers from the page.
    assert "Write the web search" in completer.prompts[0]
    assert "CADR 300 m³/h" in completer.prompts[-1]
    assert result["agent_calls"] == 2
    assert result["sources"] == ["web_search", "https://maker.example/purifier"]
    assert stored["sources"] == result["sources"]


def test_an_empty_answer_fails_the_job_and_keeps_the_question(paths, monkeypatch):
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: True)
    monkeypatch.setattr(tasks, "_local_structured_completer", lambda *a: (lambda prompt: ""))
    app_state = state.connect(paths.app_state_path)
    thread = state.create_chat_thread(app_state)
    state.add_chat_message(app_state, thread["thread_id"], role="reader", text="anything")
    job_id = state.create_job(app_state, "chat_ask", {})
    try:
        with pytest.raises(ValueError, match="no answer"):
            tasks.chat_ask(paths, {"thread_id": thread["thread_id"], "message_id": "",
                                   "text": "anything", "backend": "local"},
                           Progress(job_id, app_state))
        messages = state.chat_messages(app_state, thread["thread_id"])
    finally:
        app_state.close()
    assert [m["role"] for m in messages] == ["reader"]

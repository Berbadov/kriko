"""A reader names their chats, keeps some at the top, finds one by what was said,
and sees which agent wrote an answer.

Chats were named after the first question for good, could not be searched, and an
answer did not say who wrote it.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.web import state
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def http(tmp_path):
    paths = Settings(store_path=tmp_path / "knowledge.sqlite",
                     app_state_path=tmp_path / "app.sqlite",
                     analysis_log_path=tmp_path / "analysis.jsonl")
    return TestClient(create_app(paths)), paths


def _thread(client, title):
    return client.post("/api/chat/threads", json={"title": title}).json()["thread_id"]


def _say(paths, thread_id, role, text, **more):
    conn = state.connect(paths.app_state_path)
    try:
        return state.add_chat_message(conn, thread_id, role=role, text=text, **more)
    finally:
        conn.close()


def test_a_chat_is_renamed(http):
    client, _ = http
    thread = _thread(client, "Which oil?")

    renamed = client.patch(f"/api/chat/threads/{thread}", json={"title": "  Megane   oil  "}).json()

    assert renamed["title"] == "Megane oil"
    assert [row["title"] for row in client.get("/api/chat/threads").json()["items"]] == ["Megane oil"]


def test_a_chat_cannot_be_renamed_to_nothing(http):
    client, _ = http
    thread = _thread(client, "Keep me")

    reply = client.patch(f"/api/chat/threads/{thread}", json={"title": "   "})

    assert reply.status_code == 422
    assert client.get("/api/chat/threads").json()["items"][0]["title"] == "Keep me"


def test_a_missing_chat_is_a_404_not_a_silent_success(http):
    client, _ = http
    assert client.patch("/api/chat/threads/nope", json={"pinned": True}).status_code == 404


def test_a_pin_is_kept_and_does_not_move_the_chat_in_time(http):
    client, _ = http
    old = _thread(client, "Older")
    _thread(client, "Newer")
    before = client.get("/api/chat/threads").json()["items"]
    stamp = next(row for row in before if row["thread_id"] == old)["updated_at"]

    pinned = client.patch(f"/api/chat/threads/{old}", json={"pinned": True}).json()

    assert pinned["pinned"] is True
    assert pinned["updated_at"] == stamp
    rows = {row["thread_id"]: row for row in client.get("/api/chat/threads").json()["items"]}
    assert rows[old]["pinned"] is True and rows[[k for k in rows if k != old][0]]["pinned"] is False
    assert client.patch(f"/api/chat/threads/{old}", json={"pinned": False}).json()["pinned"] is False


def test_a_chat_is_found_by_its_name_or_by_what_was_said(http):
    client, paths = http
    oil = _thread(client, "Engine oil")
    drill = _thread(client, "Drills")
    _say(paths, oil, "agent", "Use 5W-30 with the RN17 approval.")
    _say(paths, drill, "agent", "The chuck holds.")

    def found(query):
        return [row["title"] for row in client.get("/api/chat/threads", params={"q": query}).json()["items"]]

    assert found("rn17") == ["Engine oil"]
    assert found("drill") == ["Drills"]
    assert sorted(found("")) == ["Drills", "Engine oil"]
    assert found("nothing like it") == []


def test_a_search_means_the_characters_typed(http):
    client, paths = http
    sale = _thread(client, "50% off drills")
    other = _thread(client, "5 other things")
    _say(paths, other, "agent", "A_B is not a wildcard")

    def found(query):
        return [row["thread_id"] for row in client.get("/api/chat/threads", params={"q": query}).json()["items"]]

    assert found("50%") == [sale]
    assert found("5_") == []
    assert found("a_b") == [other]


def test_an_answer_keeps_the_agent_that_wrote_it(http):
    client, paths = http
    thread = _thread(client, "Q")
    _say(paths, thread, "reader", "Which oil?")
    _say(paths, thread, "agent", "5W-30.", agent={"id": "codex", "label": "Codex", "model": "x", "secret": "dropped"})

    reader, agent = client.get(f"/api/chat/threads/{thread}/messages").json()["items"]

    assert reader["agent"] == {}
    assert agent["agent"] == {"id": "codex", "label": "Codex", "model": "x"}


def test_a_store_from_before_these_columns_gains_them(tmp_path):
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE chat_threads (thread_id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '',"
        " created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '');"
        "CREATE TABLE chat_messages (message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL DEFAULT '',"
        " role TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '', steps_json TEXT NOT NULL DEFAULT '[]',"
        " sources_json TEXT NOT NULL DEFAULT '[]', products_json TEXT NOT NULL DEFAULT '[]',"
        " job_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '');"
        "INSERT INTO chat_threads VALUES ('t1', 'Kept', 'a', 'b');"
        "INSERT INTO chat_messages (message_id, thread_id, role, text) VALUES ('m1', 't1', 'agent', 'hi');")
    old.commit()
    old.close()

    conn = state.connect(path)
    try:
        assert state.get_chat_thread(conn, "t1")["pinned"] is False
        assert state.chat_messages(conn, "t1")[0]["agent"] == {}
    finally:
        conn.close()

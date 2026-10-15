"""The research queue, as the browser extension's Add to queue key uses it."""

from fastapi.testclient import TestClient

from app.web import state
from app.web.app import create_app
from app.web.settings import Settings


def _client(tmp_path):
    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
            )
        )
    )


def test_a_queued_product_is_kept_with_where_it_came_from(tmp_path):
    client = _client(tmp_path)
    body = client.post("/api/queue", json={
        "url": "https://shop.example/item/42", "name": "Buds2 Pro", "lookup_id": "abc"}).json()

    assert body["added"] is True
    assert body["count"] == 1
    item = client.get("/api/queue").json()["items"][0]
    assert (item["name"], item["origin"], item["lookup_id"], item["state"]) == (
        "Buds2 Pro", "shop.example", "abc", "waiting")


def test_pressing_again_on_the_same_page_does_not_queue_it_twice(tmp_path):
    """The panel says "already queued" off `added: false`; a second row would
    have the agent research the same product twice."""
    client = _client(tmp_path)
    url = "https://shop.example/item/42"
    client.post("/api/queue", json={"url": url, "name": "Buds2 Pro"})
    again = client.post("/api/queue", json={
        "url": url, "name": "Galaxy Buds2 Pro", "lookup_id": "x1"}).json()

    assert again["added"] is False
    assert again["count"] == 1
    assert again["item"]["name"] == "Galaxy Buds2 Pro"
    assert again["item"]["lookup_id"] == "x1"


def test_the_queue_is_research_order_and_survives_a_restart(tmp_path):
    client = _client(tmp_path)
    for n in range(3):
        client.post("/api/queue", json={"url": f"https://shop.example/{n}", "name": f"P{n}"})

    names = [i["name"] for i in _client(tmp_path).get("/api/queue").json()["items"]]
    assert names == ["P0", "P1", "P2"]


def test_a_full_queue_says_so_rather_than_dropping_the_oldest(tmp_path):
    client = _client(tmp_path)
    for n in range(state.QUEUE_MAX):
        client.post("/api/queue", json={"url": f"https://shop.example/{n}", "name": f"P{n}"})

    over = client.post("/api/queue", json={"url": "https://shop.example/over", "name": "Over"})
    assert over.status_code == 409
    assert len(client.get("/api/queue").json()["items"]) == state.QUEUE_MAX


def test_a_product_can_be_taken_off_the_queue(tmp_path):
    client = _client(tmp_path)
    item = client.post("/api/queue", json={
        "url": "https://shop.example/1", "name": "P"}).json()["item"]

    assert client.delete(f"/api/queue/{item['queue_id']}").status_code == 200
    assert client.get("/api/queue").json()["items"] == []
    assert client.delete(f"/api/queue/{item['queue_id']}").status_code == 404


def test_history_keeps_completed_and_removed_queue_work_after_restart(tmp_path):
    client = _client(tmp_path)
    item = client.post("/api/queue", json={"url": "https://shop.example/1", "name": "Widget"}).json()["item"]
    conn = state.connect(tmp_path / "app.sqlite")
    # Researched first, as the worker does: a row cannot go from waiting to done.
    state.update_queued(conn, item["queue_id"], state="researching")
    state.update_queued(conn, item["queue_id"], state="done")
    conn.close()
    client.delete(f"/api/queue/{item['queue_id']}")
    records = _client(tmp_path).get("/api/history/records").json()["items"]
    [row] = [r for r in records if r["kind"] == "queue"]
    assert row["label"] == "Widget" and row["status"] == "removed"


def test_no_address_is_refused(tmp_path):
    assert _client(tmp_path).post(
        "/api/queue", json={"url": "  ", "name": "P"}).status_code == 422


def test_a_queued_product_moves_along_and_keeps_its_fresh_answer(tmp_path):
    client = _client(tmp_path)
    item = client.post("/api/queue", json={
        "url": "https://shop.example/1", "name": "P", "lookup_id": "old"}).json()["item"]
    path = f"/api/queue/{item['queue_id']}"

    moved = client.patch(path, json={"state": "researching"}).json()["item"]
    assert (moved["state"], moved["lookup_id"]) == ("researching", "old")
    done = client.patch(path, json={"state": "done", "lookup_id": "new"}).json()["item"]
    assert (done["state"], done["lookup_id"]) == ("done", "new")
    assert client.get("/api/queue").json()["items"][0]["state"] == "done"


def test_a_state_the_queue_does_not_have_is_refused_and_a_gone_row_is_missing(tmp_path):
    client = _client(tmp_path)
    item = client.post("/api/queue", json={
        "url": "https://shop.example/1", "name": "P"}).json()["item"]

    assert client.patch(f"/api/queue/{item['queue_id']}", json={"state": "lost"}).status_code == 422
    assert client.patch("/api/queue/nope", json={"state": "done"}).status_code == 404


# ---- the queue's state machine ------------------------------------------
#
# A row moves waiting -> researching -> (done | waiting), and a finished row
# goes back to waiting when the reader presses Add to queue on it again. Any
# other move is refused, so a row cannot be finished without having been
# researched, and cannot be researched twice at once.


def _queued(client, name="P", url="https://shop.example/1"):
    return client.post("/api/queue", json={"url": url, "name": name}).json()["item"]


def test_pressing_add_again_on_a_finished_product_queues_it_again(tmp_path):
    client = _client(tmp_path)
    item = _queued(client, url="https://shop.example/1")
    path = f"/api/queue/{item['queue_id']}"
    client.patch(path, json={"state": "researching"})
    client.patch(path, json={"state": "done", "lookup_id": "fresh"})

    again = client.post("/api/queue", json={"url": "https://shop.example/1", "name": "P"}).json()

    assert again["added"] is False
    assert again["requeued"] is True
    row = client.get("/api/queue").json()["items"][0]
    assert (row["state"], row["lookup_id"]) == ("waiting", "fresh")


def test_a_move_the_queue_does_not_allow_is_refused(tmp_path):
    client = _client(tmp_path)
    item = _queued(client)
    path = f"/api/queue/{item['queue_id']}"

    # waiting cannot jump straight to done: nothing was researched
    assert client.patch(path, json={"state": "done"}).status_code == 409
    client.patch(path, json={"state": "researching"})
    client.patch(path, json={"state": "done"})
    # done cannot go back to researching: it is queued again first
    assert client.patch(path, json={"state": "researching"}).status_code == 409
    assert client.get("/api/queue").json()["items"][0]["state"] == "done"


def test_a_passed_over_reason_is_kept_on_the_row_until_it_is_claimed_again(tmp_path):
    client = _client(tmp_path)
    item = _queued(client)
    path = f"/api/queue/{item['queue_id']}"

    client.patch(path, json={"state": "waiting",
                             "note": "research failed: the agent printed nothing"})
    kept = client.get("/api/queue").json()["items"][0]
    assert kept["note"] == "research failed: the agent printed nothing"

    client.patch(path, json={"state": "researching"})
    assert client.get("/api/queue").json()["items"][0]["note"] == ""


def test_a_row_left_researching_by_a_closed_app_is_waiting_again_at_startup(tmp_path):
    client = _client(tmp_path)
    item = _queued(client)
    client.patch(f"/api/queue/{item['queue_id']}", json={"state": "researching"})

    conn = state.connect(tmp_path / "app.sqlite")
    try:
        assert state.recover_queue(conn) == 1
    finally:
        conn.close()
    row = client.get("/api/queue").json()["items"][0]
    assert row["state"] == "waiting"
    assert "stopped" in row["note"]

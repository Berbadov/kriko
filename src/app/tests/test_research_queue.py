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

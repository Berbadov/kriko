"""A result you cannot reopen is a result you did not get.

The old dashboard rendered into innerHTML and forgot; a tab switch or a reload
destroyed the answer. These tests pin the fix at the API boundary, where the UI
can rely on it.
"""

import pytest
from fastapi.testclient import TestClient

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


def test_a_lookup_is_recorded_and_reopenable(client):
    posted = client.post(
        "/api/lookup",
        json={"kind": "product", "identity": {"brand": "acme"}, "context": {}},
    )
    assert posted.status_code == 200
    lookup_id = posted.json()["lookup_id"]
    assert lookup_id

    reopened = client.get(f"/api/lookup/{lookup_id}")
    assert reopened.status_code == 200
    assert reopened.json()["request"]["identity"] == {"brand": "acme"}
    assert reopened.json()["response"]["method"] == posted.json()["method"]


def test_history_lists_newest_first(client):
    for brand in ("one", "two"):
        client.post(
            "/api/lookup",
            json={"kind": "product", "identity": {"brand": brand}, "context": {}},
        )
    items = client.get("/api/history").json()["items"]
    assert len(items) == 2
    assert "two" in items[0]["label"]


def test_an_unknown_lookup_is_a_404_not_a_500(client):
    assert client.get("/api/lookup/deadbeef").status_code == 404


def test_a_lookup_can_be_forgotten(client):
    lookup_id = client.post(
        "/api/lookup",
        json={"kind": "product", "identity": {"brand": "acme"}, "context": {}},
    ).json()["lookup_id"]
    assert client.delete(f"/api/history/{lookup_id}").status_code == 200
    assert client.get(f"/api/lookup/{lookup_id}").status_code == 404
    assert client.delete(f"/api/history/{lookup_id}").status_code == 404


def test_history_stays_empty_when_nothing_was_asked(client):
    assert client.get("/api/history").json()["items"] == []


def test_settings_round_trip_through_the_api(client):
    assert client.get("/api/settings").json() == {}
    client.post("/api/settings", json={"values": {"mode": "author"}})
    assert client.get("/api/settings").json() == {"mode": "author"}


def test_checking_a_claim_persists_across_requests(client):
    body = {"claim_key": "tools:Timing belt", "checked": True}
    posted = client.post("/api/lookups/xyz/checked", json=body).json()
    assert posted["checked"] == ["tools:Timing belt"]
    assert client.get("/api/lookups/xyz/checked").json()["checked"] == [
        "tools:Timing belt"
    ]
    client.post(
        "/api/lookups/xyz/checked",
        json={"claim_key": "tools:Timing belt", "checked": False},
    )
    assert client.get("/api/lookups/xyz/checked").json()["checked"] == []

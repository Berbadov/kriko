"""A Compare column may be a quick look's own job id, so `/api/lookup` answers it.

The observed defect: Compare's "Research … and add" stored the quick-look job
id in the draft, and the column loader asked `/api/lookup/<job id>`. Quick looks
live in the jobs table, so that read was a 404 and the column said "Not read".
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.web import state
from app.web.app import create_app
from app.web.jobs import JobRunner
from app.web.settings import Settings


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )
    return TestClient(create_app(settings)), settings


def _finished_quick_look(settings, params: dict) -> str:
    result = {
        "risks": [{
            "title": "Stick drift",
            "severity": "high",
            "sources": [{
                "url": "https://classaction.example/dualsense",
                "domain": "classaction.example",
                "quote": "The sticks drift without input.",
            }],
        }],
        "specs": [{"name": "Weight", "value": "280 g"}],
        "listing": {"url": "https://shop.example/dualsense", "facts": {}, "description": ""},
        "identity": {"product": "DualSense"},
        "category": "wireless game controller",
        "assumed": "standard edition",
    }
    runner = JobRunner(settings, {"quick_look": lambda *_: result})
    try:
        job_id = runner.submit("quick_look", params)
        deadline = time.monotonic() + 10
        while True:
            conn = state.connect(settings.app_state_path)
            try:
                job = state.get_job(conn, job_id)
            finally:
                conn.close()
            if job and job["done"]:
                break
            assert time.monotonic() < deadline, "the quick look did not finish"
            time.sleep(0.01)
        assert job["state"] == state.SUCCEEDED
        return job_id
    finally:
        runner.shutdown(wait=True)


def test_a_quick_look_job_id_reads_as_the_lookup_shape(client):
    http, settings = client
    conn = state.connect(settings.app_state_path)
    try:
        draft = state.save_compare_draft(conn, "New", [])
    finally:
        conn.close()
    job_id = _finished_quick_look(settings, {
        "product": "ps5 gamepad",
        "compare_draft_id": draft["draft_id"],
        "compare_add": True,
    })

    conn = state.connect(settings.app_state_path)
    try:
        assert state.get_compare_draft(conn, draft["draft_id"])["lookup_ids"] == [job_id]
    finally:
        conn.close()

    reply = http.get(f"/api/lookup/{job_id}")
    assert reply.status_code == 200
    row = reply.json()
    assert row["lookup_id"] == job_id
    assert row["label"] == "ps5 gamepad"
    assert row["request"]["url"] == "https://shop.example/dualsense"
    assert row["created_at"]
    response = row["response"]
    assert response["category"] == "wireless game controller"
    assert response["assumed"] == "standard edition"
    # The same claim enrichment a saved lookup gets: the loader never has to
    # know which door the answer came from.
    assert response["claims"][0]["evidence"]["level"] in {"solid", "partial", "thin"}
    assert response["claims"][0]["sources"][0]["url"] == "https://classaction.example/dualsense"


def test_a_real_saved_lookup_still_wins_over_a_job_with_the_same_id(client):
    http, settings = client
    job_id = _finished_quick_look(settings, {"product": "a quick look"})
    conn = state.connect(settings.app_state_path)
    try:
        conn.execute(
            "INSERT INTO lookups (lookup_id, created_at, source, label, request_json, response_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, "2026-01-01T00:00:00+00:00", "manual", "a real check",
             '{"url": "https://real.example/p"}', '{"claims": []}'),
        )
        conn.commit()
    finally:
        conn.close()

    row = http.get(f"/api/lookup/{job_id}").json()
    assert row["label"] == "a real check"
    assert row["source"] == "manual"


def test_a_new_product_is_refused_when_the_board_already_holds_four(client):
    http, _ = client
    draft = http.post("/api/compare-drafts", json={
        "name": "Full", "lookup_ids": ["a", "b", "c", "d"]}).json()
    refused = http.post(f"/api/compare-drafts/{draft['draft_id']}/products",
                        json={"product": "a fifth product"})
    assert refused.status_code == 409
    assert "four checks" in refused.json()["detail"]

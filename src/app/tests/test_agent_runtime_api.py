"""Persisted manifests and bounded readers survive retries and reconnects."""

import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agentledger import Ledger
from app.web import state
from app.web.deps import get_app_state, get_jobs
from app.web.routers import agent_runtime, jobs


@pytest.fixture
def runtime(tmp_path):
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    ledger = Ledger(path)
    saved = ledger.reserve_job(conn, "client-intent", "research", {"subject_id": "fixture"},
        {"settings": {"store_path": "private/path", "packs_dir": "private/packs"}, "pack": {"version": "1"}})
    state.update_job(conn, saved["job_id"], line="αβγ\nneedle\n" + "x" * 10000)
    ledger.finish(saved["run_id"], "succeeded", result={"reply": "private input context"})
    app = FastAPI()
    app.include_router(agent_runtime.router)
    app.dependency_overrides[get_jobs] = lambda: SimpleNamespace(ledger=ledger)
    app.dependency_overrides[get_app_state] = lambda: conn
    with TestClient(app) as client:
        yield client, conn, ledger, saved
    conn.close()


def test_manifest_indexes_result_without_exposing_input_or_provider_diagnostics(runtime):
    client, _, ledger, saved = runtime
    response = client.get(f"/api/jobs/{saved['job_id']}/manifest")
    assert response.status_code == 200
    body = response.json()
    assert "input" not in body and "result" not in body
    assert "private/path" not in response.text and "private/packs" not in response.text
    assert body["snapshot"]["pack"]["version"] == "1"
    assert body["result_digest"] == ledger.lookup(saved["run_id"])["result_digest"]


def test_log_reader_uses_character_cursors_bounded_tail_and_literal_search(runtime):
    client, _, _, saved = runtime
    url = f"/api/jobs/{saved['job_id']}/log"
    first = client.get(url, params={"limit": 3}).json()
    second = client.get(url, params={"limit": 3, "cursor": first["next_cursor"]}).json()
    assert first["text"] == "αβγ"
    assert second["cursor"] == 3
    assert len(client.get(url, params={"tail": True, "limit": 100}).json()["text"]) == 100
    match = client.get(url, params={"q": "needle", "limit": 6}).json()
    assert match["text"] == "needle"
    assert client.get(url, params={"limit": 16001}).status_code == 422


def test_sse_reconnect_skips_persisted_events_and_completes(runtime):
    client, _, ledger, saved = runtime
    first_event = ledger.logs(saved["run_id"], limit=1)["events"][0]["seq"]
    response = client.get(f"/api/jobs/{saved['job_id']}/events",
                          headers={"Last-Event-ID": str(first_event)})
    assert "event: snapshot" in response.text
    assert "event: complete" in response.text
    assert f"id: {first_event}\n" not in response.text
    assert "private input context" not in response.text


def test_sse_rejects_negative_header_and_surfaces_store_failure(runtime, monkeypatch):
    client, _, ledger, saved = runtime
    url = f"/api/jobs/{saved['job_id']}/events"
    assert client.get(url, headers={"Last-Event-ID": "-1"}).status_code == 422
    monkeypatch.setattr(ledger, "logs", lambda *args, **kwargs: (_ for _ in ()).throw(
        sqlite3.OperationalError("private/path")))
    response = client.get(url)
    assert "event: error" in response.text
    assert "private/path" not in response.text


def test_research_endpoint_forwards_identity_and_reports_conflict(tmp_path):
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    ledger = Ledger(path)
    def submit(kind, params, *, client_request_id=""):
        return ledger.reserve_job(conn, client_request_id, kind, params)["job_id"]
    app = FastAPI()
    app.include_router(jobs.router)
    app.dependency_overrides[get_jobs] = lambda: SimpleNamespace(submit=submit)
    with TestClient(app) as client:
        original = {"subject_id": "one", "client_request_id": "same-intent"}
        first = client.post("/api/research", json=original)
        assert first.status_code == 200
        assert client.post("/api/research", json=original).json() == first.json()
        assert client.post("/api/research", json={**original, "subject_id": "two"}).status_code == 409
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert json.loads(conn.execute("SELECT params_json FROM jobs").fetchone()[0])["subject_id"] == "one"
    conn.close()

"""Behaviour tests for durable request identity and provider delivery records."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from app.agentledger import Ledger, RequestConflict
from app.web import state
from app.web.app import create_app
from app.web.jobs import (JobRunner, _PROMPT_EVALUATOR_SOURCES,
                          _hash_prompt_evaluator_sources, _manifest_snapshot)
from app.web.settings import Settings
from fastapi.testclient import TestClient
from kriko.store.db import connect as connect_store
from kriko.store.packstore import write_pack_row


def test_ledger_constructor_explicitly_closes_schema_connection(tmp_path, monkeypatch):
    closed = []
    original_connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        def close(self):
            closed.append(True)
            super().close()

    def tracked_connect(*args, **kwargs):
        kwargs["factory"] = TrackedConnection
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    Ledger(tmp_path / "app.sqlite")
    assert closed == [True]


def test_concurrent_duplicate_job_requests_create_one_job_and_manifest(tmp_path):
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    conn.close()
    ledger = Ledger(path)

    def reserve(_):
        db = state.connect(path)
        try:
            return ledger.reserve_job(db, "browser-request-7", "research",
                                      {"subject_id": "s-1"}, {"model": "local"})
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(reserve, range(16)))
    assert len({item["job_id"] for item in outcomes}) == 1
    assert sum(item["created"] for item in outcomes) == 1
    conn = state.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 1
    finally:
        conn.close()


def test_same_request_id_with_changed_input_conflicts(tmp_path):
    ledger = Ledger(tmp_path / "app.sqlite")
    first = ledger.reserve("request-a", "quick_ask", {"question": "one"})
    assert first["created"] is True
    with pytest.raises(RequestConflict):
        ledger.reserve("request-a", "quick_ask", {"question": "two"})


def test_request_snapshot_and_input_are_immutable_on_duplicate(tmp_path):
    ledger = Ledger(tmp_path / "app.sqlite")
    first = ledger.reserve("request-a", "research", {"subject_id": "s"},
                           {"provider": "p1", "revision": "r1"})
    duplicate = ledger.reserve("request-a", "research", {"subject_id": "s"},
                               {"provider": "p2", "revision": "r2"})
    saved = ledger.lookup(first["run_id"])
    assert duplicate["created"] is False
    assert duplicate["run_id"] == first["run_id"]
    assert saved["input"] == {"kind": "research", "params": {"subject_id": "s"}}
    assert saved["snapshot"] == {"provider": "p1", "revision": "r1"}


def test_terminal_finish_is_absorbing_and_persists_partial_usage(tmp_path):
    ledger = Ledger(tmp_path / "app.sqlite")
    run = ledger.reserve(None, "research", {"subject_id": "s"})
    partial = {"coverage": {"sources": 2}, "query_ids": ["q1"],
               "evidence_pages": [{"url": "https://example.test/a"}], "findings": [1]}
    assert ledger.checkpoint(run["run_id"], partial)
    assert ledger.finish(run["run_id"], "succeeded", usage={"usd": 0.4, "tokens": 17})
    assert not ledger.finish(run["run_id"], "failed", {"error": "late"})
    saved = ledger.lookup(run["run_id"])
    assert saved["outcome"] == "succeeded"
    assert saved["result"] == partial
    assert saved["coverage"] == {"sources": 2}
    assert saved["query_ids"] == ["q1"]
    assert saved["evidence_ids"] == ["https://example.test/a"]
    assert saved["usage"] == {"usd": 0.4, "tokens": 17}
    assert len(saved["result_digest"]) == 64
    assert ledger.checkpoint(run["run_id"], {"replacement": True}) is False


def test_crash_recovery_never_replays_accepted_or_uncertain_delivery(tmp_path):
    ledger = Ledger(tmp_path / "app.sqlite")
    retryable = ledger.reserve(None, "research", {"id": 1})
    attempt = ledger.start_attempt(retryable["run_id"], "codex", "m", {"prompt": "a"})
    assert ledger.update_delivery(attempt, "rejected", detail={"code": "busy"})

    uncertain = ledger.reserve(None, "research", {"id": 2})
    attempt = ledger.start_attempt(uncertain["run_id"], "codex", "m", {})
    ledger.mark_sending(attempt)
    accepted = ledger.reserve(None, "research", {"id": 3})
    attempt2 = ledger.start_attempt(accepted["run_id"], "codex", "m", {})
    ledger.update_delivery(attempt2, "accepted", "thread-1", "turn-1")

    recovered = ledger.recover()
    assert set(recovered["retry"]) == {retryable["run_id"]}
    assert set(recovered["reconcile"]) == {uncertain["run_id"], accepted["run_id"]}
    assert all(item["terminal_at"] for item in
               (ledger.lookup(retryable["run_id"]), ledger.lookup(uncertain["run_id"]),
                ledger.lookup(accepted["run_id"])))
    assert ledger.lookup(uncertain["run_id"])["recovery_action"] == {
        "action": "reconcile", "automatic_replay": False, "delivery": "unknown"}
    records = ledger.attempts(accepted["run_id"])
    assert records[0]["context_id"] == "thread-1"
    assert records[0]["turn_id"] == "turn-1"


def test_attempt_delivery_callback_records_ids_and_cursor_log(tmp_path):
    ledger = Ledger(tmp_path / "app.sqlite")
    run = ledger.reserve(None, "quick_ask", {"question": "q"})
    attempt_id = ledger.start_attempt(run["run_id"], "codex", "model-x", {"input": "x"})
    ledger.update_delivery(attempt_id, "accepted", "ctx-9", "turn-4",
                           {"status": "ok", "api_key": "do-not-save"})
    first = ledger.logs(run["run_id"], limit=2)
    second = ledger.logs(run["run_id"], cursor=first["next_cursor"])
    assert first["events"]
    assert all(event["seq"] > first["next_cursor"] for event in second["events"])
    attempt = ledger.attempts(run["run_id"])[0]
    assert attempt["delivery"] == "accepted"
    assert attempt["detail"]["api_key"] == "[redacted]"


def test_concurrent_attempt_ordinals_are_unique_and_late_delivery_is_ignored(tmp_path):
    ledger = Ledger(tmp_path / "app.sqlite")
    run = ledger.reserve(None, "research", {"subject_id": "s"})
    with ThreadPoolExecutor(max_workers=8) as pool:
        attempt_ids = list(pool.map(lambda _: ledger.start_attempt(run["run_id"]), range(16)))
    assert sorted(row["ordinal"] for row in ledger.attempts(run["run_id"])) == list(range(1, 17))
    attempt_id = attempt_ids[0]
    assert ledger.finish_attempt(attempt_id, "failed")
    assert not ledger.update_delivery(attempt_id, "accepted", "late-context", "late-turn")
    assert ledger.attempts(run["run_id"])[0]["delivery"] == "not_sent"


def test_recovery_reconciles_job_terminal_state_after_crash_before_manifest_finish(tmp_path):
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    conn.close()
    ledger = Ledger(path)
    conn = state.connect(path)
    try:
        run = ledger.reserve_job(conn, "request-crash-window", "research",
                                 {"subject_id": "s"}, {"backend": "local"})
        state.finish_job(conn, run["job_id"], state.SUCCEEDED,
                         result={"coverage": {"pages": 1}, "query_ids": ["q1"]})
    finally:
        conn.close()

    recovered = ledger.recover()
    saved = ledger.lookup(run["run_id"])
    assert recovered["actions"] == [{"run_id": run["run_id"], "action": "job_terminal",
                                     "job_state": state.SUCCEEDED, "delivery": "not_sent"}]
    assert saved["state"] == state.SUCCEEDED
    assert saved["outcome"] == state.SUCCEEDED
    assert saved["result"] == {"coverage": {"pages": 1}, "query_ids": ["q1"]}
    assert saved["terminal_at"]


def test_sse_stream_completes_for_recovered_terminal_run(tmp_path):
    settings = Settings(store_path=tmp_path / "knowledge.sqlite",
                        app_state_path=tmp_path / "app.sqlite",
                        analysis_log_path=tmp_path / "analyses.jsonl",
                        packs_dir=tmp_path / "packs")
    app = create_app(settings)
    ledger = app.state.jobs.ledger
    conn = state.connect(settings.app_state_path)
    try:
        run = ledger.reserve_job(conn, "request-sse-crash", "quick_ask",
                                 {"question": "q"}, {"backend": "agent"})
        state.finish_job(conn, run["job_id"], state.FAILED,
                         message="provider stopped", result={"partial": True})
    finally:
        conn.close()
    with TestClient(app) as client:
        response = client.get(f"/api/jobs/{run['job_id']}/events")
    assert response.status_code == 200
    assert "event: complete" in response.text
    assert '"state": "failed"' in response.text


def test_manifest_snapshot_prefers_backend_and_omits_filesystem_paths(tmp_path):
    settings = Settings(store_path=tmp_path / "knowledge.sqlite",
                        app_state_path=tmp_path / "app.sqlite",
                        packs_dir=tmp_path / "packs")
    conn = state.connect(settings.app_state_path)
    try:
        state.put_settings(conn, {"llm_model": "saved-model", "search_provider": "exa"})
    finally:
        conn.close()
    store = connect_store(settings.store_path)
    try:
        write_pack_row(store, pack_id="p1", name="Pack", version="3.2",
                       content_digest="digest-p1")
        store.commit()
    finally:
        store.close()
    snapshot = _manifest_snapshot(settings, {"backend": "api", "provider": "stale-provider",
                                             "pack_id": "p1"})
    assert snapshot["backend"] == "api"
    assert snapshot["provider"] == "api"
    assert snapshot["model"] == "saved-model"
    assert snapshot["search_provider"] == "exa"
    assert snapshot["implementation"]["version"]
    implementation = snapshot["implementation"]["prompt_evaluator"]
    assert len(implementation["sha256"]) == 64
    assert implementation["source_status"] == "available"
    assert implementation["sources_available"] == len(_PROMPT_EVALUATOR_SOURCES)
    assert snapshot["pack"]["revision_id"] == "p1@digest-p1"
    rendered = repr(snapshot)
    assert str(tmp_path) not in rendered
    assert "store_path" not in rendered and "packs_dir" not in rendered


def test_prompt_evaluator_digest_is_content_based_across_package_layouts(tmp_path):
    checkout_src = tmp_path / "checkout" / "src"
    wheel_root = tmp_path / "wheel" / "site-packages"
    for relative in _PROMPT_EVALUATOR_SOURCES:
        for root in (checkout_src, wheel_root):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("implementation for " + relative).encode("utf-8"))

    checkout = _hash_prompt_evaluator_sources(checkout_src)
    installed = _hash_prompt_evaluator_sources(wheel_root)
    assert checkout == installed
    changed_file = wheel_root / _PROMPT_EVALUATOR_SOURCES[0]
    changed_file.write_bytes(b"changed implementation")
    changed = _hash_prompt_evaluator_sources(wheel_root)
    assert changed["sha256"] != installed["sha256"]
    assert changed["source_status"] == "available"


def test_startup_recovery_classifies_delivery_before_marking_job_interrupted(tmp_path):
    settings = Settings(store_path=tmp_path / "knowledge.sqlite",
                        app_state_path=tmp_path / "app.sqlite",
                        packs_dir=tmp_path / "packs")
    runner = JobRunner(settings, {"quick_ask": lambda *_: {}})
    conn = state.connect(settings.app_state_path)
    try:
        run = runner.ledger.reserve_job(conn, "request-live-crash", "quick_ask",
                                        {"question": "q"})
        assert state.start_job(conn, run["job_id"])
    finally:
        conn.close()
    attempt = runner.ledger.start_attempt(run["run_id"], "codex", "model")
    runner.ledger.update_delivery(attempt, "accepted", "thread", "turn")

    runner.recover()
    saved = runner.ledger.lookup(run["run_id"])
    conn = state.connect(settings.app_state_path)
    try:
        job = state.get_job(conn, run["job_id"])
    finally:
        conn.close()
    assert saved["outcome"] == state.INTERRUPTED
    assert saved["recovery_action"]["action"] == "reconcile"
    assert saved["recovery_action"]["automatic_replay"] is False
    assert job["state"] == state.INTERRUPTED
    runner.shutdown(wait=True)

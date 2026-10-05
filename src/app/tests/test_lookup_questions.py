"""Follow-up questions use the saved check and never become knowledge."""

import pytest
from fastapi.testclient import TestClient

from app.web import state, tasks
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def check(tmp_path, monkeypatch):
    settings = Settings(store_path=tmp_path / "knowledge.sqlite",
                        app_state_path=tmp_path / "app.sqlite",
                        analysis_log_path=tmp_path / "analysis.jsonl")
    conn = state.connect(settings.app_state_path)
    lookup_id = state.record_lookup(conn, source="extension", label="Example product",
                                   request={}, response={"claims": [{
                                       "title": "Seal wear", "body": "Leaks after heavy use.",
                                       "severity": "medium", "advice": "Ask for service records.",
                                       "sources": [{"url": "https://example.test/source",
                                                    "quote": "The seal can leak."}],
                                   }], "context": {"hours": 100},
                                       "context_units": {"hours": "h"}})
    conn.close()
    app = create_app(settings)
    # The job runner's durable write is real; its thread executor is the edge
    # held here so endpoint tests cannot start a machine's configured agent.
    monkeypatch.setattr(app.state.jobs._quick, "submit", lambda *a: None)
    return TestClient(app), settings, lookup_id


def test_a_followup_is_a_durable_job_attached_to_the_saved_check(check, monkeypatch):
    http, settings, lookup_id = check
    monkeypatch.setattr(tasks, "default_backend", lambda *a: "local")
    response = http.post(f"/api/lookup/{lookup_id}/questions",
                         json={"question": "  What should I check?  "})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    job = http.get(f"/api/jobs/{job_id}").json()
    assert job["kind"] == "lookup_ask"
    assert job["params"]["lookup_id"] == lookup_id
    assert job["params"]["question"] == "What should I check?"
    assert job["params"]["backend"] == "local"
    assert 0 < job["params"]["budget_usd"] <= 0.20
    reopened = TestClient(create_app(settings))
    listed = reopened.get(f"/api/lookup/{lookup_id}/questions").json()["items"]
    assert [row["job_id"] for row in listed] == [job_id]


def test_invalid_followups_are_refused_before_starting_an_agent(check):
    http, _, lookup_id = check
    assert http.post("/api/lookup/missing/questions", json={"question": "Why?"}).status_code == 404
    for question in ("", "   ", "q" * 2001):
        assert http.post(f"/api/lookup/{lookup_id}/questions",
                         json={"question": question}).status_code == 422
    assert http.get(f"/api/lookup/{lookup_id}/questions").json()["items"] == []


def test_the_agent_reads_the_recorded_evidence_and_answers_without_writing_claims(check, monkeypatch):
    http, settings, lookup_id = check

    class Researcher:
        model = "small-local-model"

        def ask(self, prompt):
            self.prompt = prompt
            assert progress.identity == {"agent": {
                "id": "local", "label": "Local model", "model": self.model,
            }}, "identity must be reported before the answer starts"
            return " Ask for a service record. "

    class Progress:
        def set(self, *args): pass
        def log(self, text): pass
        def check(self): pass
        def partial(self, result): self.identity = result

    researcher = Researcher()
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: True)
    monkeypatch.setattr(tasks, "_local_asker", lambda *a: researcher)
    conn = state.connect(settings.app_state_path)
    prior = state.create_job(conn, "lookup_ask", {"lookup_id": lookup_id,
                                                  "question": "Which risk is most urgent?"})
    state.finish_job(conn, prior, state.SUCCEEDED, result={"answer": "Check the seal first."})
    unrelated = state.create_job(conn, "lookup_ask", {"lookup_id": "another-check",
                                                       "question": "An unrelated question"})
    state.finish_job(conn, unrelated, state.SUCCEEDED, result={"answer": "An unrelated reply"})
    conn.close()
    before = http.get(f"/api/lookup/{lookup_id}").json()
    progress = Progress()
    result = tasks.lookup_ask(settings, {"lookup_id": lookup_id,
                                        "question": "What should I check?"}, progress)
    assert result["answer"] == "Ask for a service record."
    assert result["agent"] == progress.identity["agent"]
    assert result["lookup_id"] == lookup_id
    for text in ("What should I check?", "Seal wear", "Leaks after heavy use.",
                 "hours: 100 h", "https://example.test/source", "The seal can leak."):
        assert text in researcher.prompt
    assert "Do not invent risks" in researcher.prompt
    assert "Which risk is most urgent?" in researcher.prompt
    assert "Check the seal first." in researcher.prompt
    assert "An unrelated reply" not in researcher.prompt
    assert http.get(f"/api/lookup/{lookup_id}").json() == before


@pytest.mark.parametrize("api", [False, True])
def test_followup_names_the_resolved_agent_not_the_requested_one(check, monkeypatch, api):
    from types import SimpleNamespace

    import app.providers as providers
    from app.web.jobs import Progress

    http, settings, lookup_id = check
    resolved = SimpleNamespace(id="resolved-agent", label="Resolved agent")
    researcher = SimpleNamespace(harness=resolved, model="resolved-agent",
                                 requested_model="cli-model")
    if api:
        researcher.agent = resolved
        researcher.model = "api-model"
    conn = state.connect(settings.app_state_path)
    job_id = state.create_job(conn, "lookup_ask", {"lookup_id": lookup_id,
                                                  "question": "Why?"})
    progress = Progress(job_id, conn)

    def ask(brief):
        running = http.get(f"/api/jobs/{job_id}").json()
        assert running["result"]["agent"] == {
            "id": "resolved-agent", "label": "Resolved agent",
            "model": "api-model" if api else "cli-model",
        }
        return "Recorded answer"

    researcher.ask = ask
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: False)
    monkeypatch.setattr(providers, "agent_ready", lambda *a: True)
    monkeypatch.setattr(providers, "harness_researcher", lambda **kw: researcher)
    try:
        result = tasks.lookup_ask(settings, {"lookup_id": lookup_id,
                                            "question": "Why?", "harness": "requested-agent"}, progress)
        state.finish_job(conn, job_id, state.SUCCEEDED, result=result)
    finally:
        conn.close()
    saved = TestClient(create_app(settings)).get(f"/api/lookup/{lookup_id}/questions").json()
    assert saved["items"][0]["result"]["agent"] == result["agent"]


def test_a_gone_check_does_not_reach_the_agent(check, monkeypatch):
    _, settings, _ = check
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: pytest.fail("Agent was reached"))
    with pytest.raises(ValueError, match="no such lookup"):
        tasks.lookup_ask(settings, {"lookup_id": "missing", "question": "Why?"}, None)

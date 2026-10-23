"""B183: a comparison is a named draft the reader can reopen and edit.

*"Compare: work like draft papers, each draft saved and helping the user
choose"*. The drafts are app state in `app.sqlite`, not knowledge.
"""

import pytest
import threading
import time
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
    assert [(q["question"], q["job_id"]) for q in listed["items"]] == [
        (asked["question"], asked["job_id"])]
    assert http.post("/api/compare-drafts/nope/questions",
                     json={"question": "x"}).status_code == 404
    assert http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                     json={"question": "   "}).status_code == 422


def test_compare_can_explicitly_choose_the_local_model(client, monkeypatch):
    http, _ = client
    from app import localplane
    monkeypatch.setattr(localplane, "resolve", lambda *a, **k: {
        "ready": True, "reason": "", "model": "gemma4:e2b"})
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


def test_compare_refuses_a_missing_agent_when_another_cli_is_installed(client, monkeypatch):
    http, _ = client
    from app.providers import apiagent, harness
    from app.providers.harness import KNOWN
    monkeypatch.setattr(apiagent, "available", lambda *a, **k: [])
    other = next(agent for agent in KNOWN if agent.id != "missing-agent")
    monkeypatch.setattr(harness, "available", lambda: [other])
    made = http.post("/api/compare-drafts",
                     json={"name": "Two", "lookup_ids": ["a", "b"]}).json()
    submitted = []
    monkeypatch.setattr(http.app.state.jobs, "submit",
                        lambda *a, **k: submitted.append((a, k)) or "should-not-queue")
    response = http.post(
        f"/api/compare-drafts/{made['draft_id']}/questions",
        json={"question": "Which is better?", "harness": "missing-agent"})
    assert response.status_code == 503
    assert "missing-agent" in response.json()["detail"]
    assert submitted == []


def test_compare_explicit_local_agent_needs_a_model_but_not_search(client, monkeypatch):
    http, _ = client
    from app import localplane
    made = http.post("/api/compare-drafts",
                     json={"name": "Two", "lookup_ids": ["a", "b"]}).json()
    submitted = []
    calls = []
    monkeypatch.setattr(localplane, "resolve", lambda *a, **k: (
        calls.append(k) or {"ready": False, "reason": "no model"}))
    monkeypatch.setattr(http.app.state.jobs, "submit",
                        lambda *a, **k: submitted.append((a, k)) or "should-not-queue")
    response = http.post(
        f"/api/compare-drafts/{made['draft_id']}/questions",
        json={"question": "Which is better?", "backend": "local", "harness": "local"})
    assert response.status_code == 503
    assert calls == [{"with_search": False}]
    assert submitted == []

def test_compare_replay_returns_job_after_selected_agent_disappears(client, monkeypatch):
    http, _ = client
    from app.providers import apiagent, harness
    from app.providers.harness import KNOWN
    selected = next(agent for agent in KNOWN if agent.id == "codex")
    monkeypatch.setattr(apiagent, "available", lambda *a, **k: [])
    monkeypatch.setattr(harness, "available", lambda: [selected])
    made = http.post("/api/compare-drafts",
                     json={"name": "Two", "lookup_ids": ["a", "b"]}).json()
    submitted = []
    def submit(kind, params, **kwargs):
        submitted.append((kind, params, kwargs))
        return "job-existing"
    monkeypatch.setattr(http.app.state.jobs, "submit", submit)
    payload = {"question": "Which is better?", "harness": selected.id,
               "client_request_id": "retry-1"}
    first = http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                      json=payload)
    assert first.status_code == 200
    monkeypatch.setattr(harness, "available", lambda: [])
    replay = http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                       json=payload)
    assert replay.status_code == 200
    assert replay.json()["job_id"] == "job-existing"
    assert len(submitted) == 1


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


def test_the_job_handler_searches_with_quicklook_product_context_and_persists_sources(
        client, monkeypatch):
    http, settings = client
    from app.web import tasks
    app_state = state.connect(settings.app_state_path)
    quick_id = state.create_job(app_state, "quick_look", {"product": "Acme 5W-30 oil"})
    state.finish_job(app_state, quick_id, state.SUCCEEDED, result={
        "assumed": "the 5W-30 full synthetic",
        "category": "engine oil",
        "risks": [],
        "specs": [{"name": "Viscosity", "value": "SAE 5W-30",
                   "url": "https://oil.example/spec", "domain": "oil.example",
                   "quote": "SAE 5W-30 full synthetic engine oil."}],
        "listing": {"url": "https://shop.example/listing", "facts": {
            "vehicle": "2018 Honda Civic", "engine": "1.5L turbo"},
            "description": "Meets API SP; synthetic oil."},
        "coverage": {"status": "no_supported_findings", "pages_read": 2,
                     "pages_relevant": 2, "pages_extracted": 2},
        "diagnostic": {"code": "no_issues_found", "message": "No supported issues found in 2 pages."},
        "evidence_pages": [{"url": "https://oil.example/spec", "domain": "oil.example",
                            "excerpt": "SAE 5W-30 full synthetic engine oil."}],
    })
    b2 = _one_lookup(settings, "Acme 0W-20 oil", {
        "claims": [{"claim_id": "c", "pack_id": "p", "title": "Timing chain",
                    "body": "Stretches early.", "severity": "high"}],
        "context": {"engine": "2.0L"},
    })
    app_state.close()
    made = http.post("/api/compare-drafts",
                     json={"name": "Two oils", "lookup_ids": [quick_id, b2]}).json()
    app_state = state.connect(settings.app_state_path)
    prior = state.record_compare_question(
        app_state, made["draft_id"], "What does the manual specify?")
    state.answer_compare_question(
        app_state, made["draft_id"], prior["question_id"],
        "The manual specifies 0W-20.", "previous-job")
    app_state.close()
    monkeypatch.setattr(http.app.state.jobs, "submit", lambda *_: "queued-test-job")
    asked = http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                      json={"question": "Is the first oil right for my car?"}).json()

    class Researcher:
        requested_model = "codex"
        harness = type("Harness", (), {"id": "codex", "label": "Codex"})()
        sources = {"https://owner.example/manual": "Honda specifies 0W-20 for this engine."}
        on_text = None

        def ask_followup(self, prompt, *, product, question):
            self.prompt = prompt
            self.product = product
            self.question = question
            self.on_text("The listing shows 5W-30, but the manual says ")
            return ("The listing shows 5W-30, but the manual says to use 0W-20. "
                    "Sources: https://owner.example/manual")

        def ask(self, _prompt):
            raise AssertionError("the harness follow-up should use host-read pages")

    researcher = Researcher()
    from app import providers
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a, **k: False)
    monkeypatch.setattr(providers, "agent_ready", lambda *a, **k: True)
    monkeypatch.setattr(providers, "harness_researcher", lambda **_kwargs: researcher)

    class _Progress:
        job_id = "job-1"
        def log(self, line): pass
        def set(self, *a, **k): pass
        def check(self): pass
        def partial(self, result): pass

    result = tasks.compare_ask(settings, {
        "draft_id": made["draft_id"], "question_id": asked["question_id"],
        "question": asked["question"]}, _Progress())
    assert result["answer"].startswith("The listing shows 5W-30")
    assert result["saved_checks"] == [
        {"name": "Acme 5W-30 oil", "risks": 0}, {"name": "Acme 0W-20 oil", "risks": 1}]
    assert result["brief_chars"] == len(researcher.prompt)
    assert result["sources"] == [{"url": "https://owner.example/manual",
                                   "domain": "owner.example"}]
    assert result["model"] == "codex"
    assert researcher.product == "Acme 5W-30 oil, Acme 0W-20 oil"
    assert researcher.question == "Is the first oil right for my car?"
    assert "QUESTION: Is the first oil right for my car?" in researcher.prompt
    assert "What does the manual specify?" in researcher.prompt
    assert "The manual specifies 0W-20." in researcher.prompt
    assert "## Acme 5W-30 oil" in researcher.prompt and "## Acme 0W-20 oil" in researcher.prompt
    assert "2018 Honda Civic" in researcher.prompt and "1.5L turbo" in researcher.prompt
    assert "SAE 5W-30 full synthetic engine oil." in researcher.prompt
    assert "Search the web" in researcher.prompt
    conn = state.connect(settings.app_state_path)
    stored = state.compare_questions(conn, made["draft_id"])
    conn.close()
    assert stored[0]["answer"].startswith("The listing shows 5W-30")
    assert stored[0]["sources"] == result["sources"]
    assert stored[0]["job_id"] == "job-1"


def test_compare_research_runs_a_quick_look_for_saved_products(client, monkeypatch):
    http, settings = client
    from app.providers import apiagent, harness
    from app.providers.harness import KNOWN
    selected = next(agent for agent in KNOWN if agent.id == "codex")
    monkeypatch.setattr(apiagent, "available", lambda *a, **k: [])
    monkeypatch.setattr(harness, "available", lambda: [selected])
    lookup_id = _one_lookup(settings, "Acme headset", {
        "claims": [], "context": {}, "listing": {
            "url": "https://shop.example/item", "facts": {"brand": "Acme"},
            "description": "Wireless headset"}})
    conn = state.connect(settings.app_state_path)
    try:
        draft = state.save_compare_draft(conn, "Headset", [lookup_id])
    finally:
        conn.close()
    submitted = []
    monkeypatch.setattr(
        http.app.state.jobs, "submit",
        lambda kind, params, **kwargs: submitted.append((kind, params, kwargs)) or "quick-job")
    response = http.post(
        f"/api/compare-drafts/{draft['draft_id']}/research",
        json={"lookup_id": lookup_id, "harness": selected.id,
              "client_request_id": "headset-research"})
    assert response.status_code == 200
    payload = response.json()
    assert (payload["job_id"], payload["kind"], payload["lookup_id"]) == (
        "quick-job", "quick_look", lookup_id)
    kind, params, options = submitted[0]
    assert kind == "quick_look"
    assert params["product"] == "Acme headset"
    assert params["backend"] == "harness" and params["harness"] == selected.id
    assert params["compare_lookup_id"] == lookup_id
    assert params["page_url"] == "https://shop.example/item"
    assert params["page"]["facts"] == {"brand": "Acme"}
    assert options["client_request_id"] == "compare-product:headset-research"


def test_compare_research_replaces_only_a_still_present_source(client):
    from app.web import jobs

    _, settings = client
    conn = state.connect(settings.app_state_path)
    try:
        draft = state.save_compare_draft(conn, "Two", ["old", "keep"])
        params = {"compare_draft_id": draft["draft_id"], "compare_lookup_id": "old"}
        job_id = state.create_job(conn, "quick_look", params)
        assert state.start_job(conn, job_id)
        with conn:
            state.finish_job(conn, job_id, state.SUCCEEDED, result={}, commit=False)
            assert jobs._replace_compare_lookup(conn, draft["draft_id"], "old", job_id)
    finally:
        conn.close()
    conn = state.connect(settings.app_state_path)
    try:
        current = state.get_compare_draft(conn, draft["draft_id"])
        assert current["lookup_ids"] == [job_id, "keep"]
        state.save_compare_draft(conn, "Renamed while researching",
                                 ["keep", "another"], draft["draft_id"])
    finally:
        conn.close()
    conn = state.connect(settings.app_state_path)
    try:
        with conn:
            assert not jobs._replace_compare_lookup(conn, draft["draft_id"], "old", "stale")
        current = state.get_compare_draft(conn, draft["draft_id"])
        assert current["name"] == "Renamed while researching"
        assert current["lookup_ids"] == ["keep", "another"]
        state.delete_compare_draft(conn, draft["draft_id"])
    finally:
        conn.close()
    conn = state.connect(settings.app_state_path)
    try:
        with conn:
            assert not jobs._replace_compare_lookup(conn, draft["draft_id"], "old", "orphan")
    finally:
        conn.close()

@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("success", state.SUCCEEDED), ("failure", state.FAILED),
     ("cancel", state.CANCELLED)],
)
def test_compare_research_replaces_its_column_only_after_success(
        client, outcome, expected):
    from app.web.jobs import Cancelled, JobRunner

    _, settings = client
    conn = state.connect(settings.app_state_path)
    try:
        draft = state.save_compare_draft(conn, "Two", ["old", "keep"])
    finally:
        conn.close()
    started = threading.Event()
    release = threading.Event()

    def finish(_settings, _params, _progress):
        started.set()
        assert release.wait(5)
        if outcome == "failure":
            raise RuntimeError("research failed")
        if outcome == "cancel":
            raise Cancelled()
        return {"risks": []}

    runner = JobRunner(settings, {"quick_look": finish})
    params = {"compare_draft_id": draft["draft_id"], "compare_lookup_id": "old"}
    try:
        job_id = runner.submit("quick_look", params)
        assert started.wait(5)
        conn = state.connect(settings.app_state_path)
        try:
            assert state.get_compare_draft(conn, draft["draft_id"])["lookup_ids"] == [
                "old", "keep"]
        finally:
            conn.close()
        release.set()
        for _ in range(500):
            conn = state.connect(settings.app_state_path)
            try:
                job = state.get_job(conn, job_id)
            finally:
                conn.close()
            if job and job["done"]:
                break
            time.sleep(0.01)
        assert job["state"] == expected
        conn = state.connect(settings.app_state_path)
        try:
            ids = state.get_compare_draft(conn, draft["draft_id"])["lookup_ids"]
        finally:
            conn.close()
        assert ids == ([job_id, "keep"] if outcome == "success" else ["old", "keep"])
    finally:
        release.set()
        runner.shutdown(wait=True)


def test_compare_success_and_replacement_become_visible_together(client, monkeypatch):
    from app.web import jobs

    _, settings = client
    observer = state.connect(settings.app_state_path)
    draft = state.save_compare_draft(observer, "Two", ["old", "keep"])
    entered = threading.Event()
    allow_replace = threading.Event()
    replaced = threading.Event()
    allow_commit = threading.Event()
    saving_checks = threading.Event()
    finish_checks = threading.Event()
    original = jobs._replace_compare_lookup

    def paused_replace(conn, draft_id, source_id, replacement_id):
        assert conn.in_transaction
        entered.set()
        assert allow_replace.wait(10)
        changed = original(conn, draft_id, source_id, replacement_id)
        replaced.set()
        assert allow_commit.wait(10)
        return changed

    def slow_checks(_kind, _result):
        saving_checks.set()
        assert finish_checks.wait(10)

    monkeypatch.setattr(jobs, "_replace_compare_lookup", paused_replace)
    runner = jobs.JobRunner(settings, {"quick_look": lambda *_: {"risks": []}})
    monkeypatch.setattr(runner, "_save_product_checks", slow_checks)
    try:
        job_id = runner.submit("quick_look", {
            "compare_draft_id": draft["draft_id"], "compare_lookup_id": "old"})
        assert entered.wait(10)
        assert state.get_job(observer, job_id)["state"] == state.RUNNING
        assert state.get_compare_draft(observer, draft["draft_id"])["lookup_ids"] == ["old", "keep"]
        allow_replace.set()
        assert replaced.wait(10)
        # Even after both writes, another connection sees neither until commit.
        assert state.get_job(observer, job_id)["state"] == state.RUNNING
        assert state.get_compare_draft(observer, draft["draft_id"])["lookup_ids"] == ["old", "keep"]
        allow_commit.set()
        assert saving_checks.wait(10)
        job = state.get_job(observer, job_id)
        assert job["state"] == state.SUCCEEDED
        assert job["result"] == {"risks": []}
        assert state.get_compare_draft(observer, draft["draft_id"])["lookup_ids"] == [job_id, "keep"]
        assert state.saved_answer(observer, job_id) is not None
        # The expensive catalog work does not retain the SQLite write lock.
        observer.execute("BEGIN IMMEDIATE")
        observer.rollback()
    finally:
        allow_replace.set()
        allow_commit.set()
        finish_checks.set()
        runner.shutdown(wait=True)
        observer.close()


@pytest.mark.parametrize("edit", ["reorder", "remove", "delete"])
def test_compare_research_preserves_draft_edits_made_while_running(client, edit):
    from app.web.jobs import JobRunner

    _, settings = client
    conn = state.connect(settings.app_state_path)
    try:
        draft = state.save_compare_draft(conn, "Two", ["old", "keep"])
    finally:
        conn.close()
    started = threading.Event()
    release = threading.Event()

    def finish(_settings, _params, _progress):
        started.set()
        assert release.wait(5)
        return {"risks": []}

    runner = JobRunner(settings, {"quick_look": finish})
    params = {"compare_draft_id": draft["draft_id"], "compare_lookup_id": "old"}
    try:
        job_id = runner.submit("quick_look", params)
        assert started.wait(5)
        conn = state.connect(settings.app_state_path)
        try:
            if edit == "delete":
                assert state.delete_compare_draft(conn, draft["draft_id"])
            else:
                changed = (["keep", "old", "new"] if edit == "reorder"
                           else ["keep", "new"])
                state.save_compare_draft(conn, "Edited while researching", changed,
                                         draft["draft_id"])
        finally:
            conn.close()
        release.set()
        for _ in range(500):
            conn = state.connect(settings.app_state_path)
            try:
                job = state.get_job(conn, job_id)
            finally:
                conn.close()
            if job and job["done"]:
                break
            time.sleep(0.01)
        assert job["state"] == state.SUCCEEDED
        conn = state.connect(settings.app_state_path)
        try:
            current = state.get_compare_draft(conn, draft["draft_id"])
            if edit == "delete":
                assert current is None
            elif edit == "reorder":
                assert current["name"] == "Edited while researching"
                assert current["lookup_ids"] == ["keep", job_id, "new"]
            else:
                assert current["name"] == "Edited while researching"
                assert current["lookup_ids"] == ["keep", "new"]
        finally:
            conn.close()
    finally:
        release.set()
        runner.shutdown(wait=True)

def test_compare_research_refuses_products_outside_the_draft(client, monkeypatch):
    http, settings = client
    from app.providers import apiagent, harness
    from app.providers.harness import KNOWN
    selected = next(agent for agent in KNOWN if agent.id == "codex")
    monkeypatch.setattr(apiagent, "available", lambda *a, **k: [])
    monkeypatch.setattr(harness, "available", lambda: [selected])
    conn = state.connect(settings.app_state_path)
    try:
        draft = state.save_compare_draft(conn, "Headset", [])
    finally:
        conn.close()
    submitted = []
    monkeypatch.setattr(http.app.state.jobs, "submit",
                        lambda *a, **k: submitted.append((a, k)) or "should-not-queue")
    response = http.post(
        f"/api/compare-drafts/{draft['draft_id']}/research",
        json={"lookup_id": "other", "harness": selected.id})
    assert response.status_code == 404
    assert submitted == []


def test_compare_research_refuses_a_product_with_no_completed_saved_check(client, monkeypatch):
    """A column with nothing saved has no page and no name to research, so the
    press must say that rather than queue a job that cannot be built."""
    http, settings = client
    from app.providers import apiagent, harness
    from app.providers.harness import KNOWN
    selected = next(agent for agent in KNOWN if agent.id == "codex")
    monkeypatch.setattr(apiagent, "available", lambda *a, **k: [])
    monkeypatch.setattr(harness, "available", lambda: [selected])
    conn = state.connect(settings.app_state_path)
    try:
        draft = state.save_compare_draft(conn, "Headset", ["never-answered"])
    finally:
        conn.close()
    submitted = []
    monkeypatch.setattr(http.app.state.jobs, "submit",
                        lambda *a, **k: submitted.append((a, k)) or "should-not-queue")
    response = http.post(
        f"/api/compare-drafts/{draft['draft_id']}/research",
        json={"lookup_id": "never-answered", "harness": selected.id})
    assert response.status_code == 409
    assert "no completed saved check" in response.json()["detail"]
    assert submitted == []


def test_compare_research_refuses_an_agent_this_machine_does_not_offer(client, monkeypatch):
    """The reader pressed an agent the engine had listed; a race took it away.
    The refusal names the agent, what is missing and how to get it, because the
    reader is standing on Compare and an id alone is not an answer."""
    http, settings = client
    from app.providers import apiagent, harness
    from app.providers.harness import KNOWN
    monkeypatch.setattr(apiagent, "available", lambda *a, **k: [])
    other = next(agent for agent in KNOWN if agent.id != "codex")
    monkeypatch.setattr(harness, "available", lambda: [other])
    lookup_id = _one_lookup(settings, "Acme headset", {"claims": [], "context": {}})
    conn = state.connect(settings.app_state_path)
    try:
        draft = state.save_compare_draft(conn, "Headset", [lookup_id])
    finally:
        conn.close()
    submitted = []
    monkeypatch.setattr(http.app.state.jobs, "submit",
                        lambda *a, **k: submitted.append((a, k)) or "should-not-queue")
    response = http.post(
        f"/api/compare-drafts/{draft['draft_id']}/research",
        json={"lookup_id": lookup_id, "harness": "codex"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "Codex" in detail and "not installed here" in detail
    assert "codex" in detail
    assert submitted == []


def test_compare_research_says_the_key_or_the_trial_an_api_agent_is_missing(
        client, monkeypatch):
    """The sentence is the key resolver's own. A missing key and a spent trial
    are different problems with different ways out, and a second copy of that
    vocabulary here would drift from the one the rest of the app shows."""
    from app import keys
    from app.providers import MissingKey, apiagent, harness
    from app.providers.harness import KNOWN

    http, settings = client
    monkeypatch.setattr(apiagent, "available", lambda *a, **k: [])
    selected = next(agent for agent in KNOWN if agent.id == "codex")
    monkeypatch.setattr(harness, "available", lambda: [selected])
    monkeypatch.setattr(keys, "require", lambda provider, **kwargs: (_ for _ in ()).throw(
        MissingKey("The free Kriko Agent trial for this computer is used up (10 of 10 questions). "
                   "Paste an access code and password, or add your own Mercury and DeepSeek keys "
                   "in Settings.")))
    lookup_id = _one_lookup(settings, "Acme headset", {"claims": [], "context": {}})
    conn = state.connect(settings.app_state_path)
    try:
        draft = state.save_compare_draft(conn, "Headset", [lookup_id])
    finally:
        conn.close()
    submitted = []
    monkeypatch.setattr(http.app.state.jobs, "submit",
                        lambda *a, **k: submitted.append((a, k)) or "should-not-queue")
    response = http.post(
        f"/api/compare-drafts/{draft['draft_id']}/research",
        json={"lookup_id": lookup_id, "harness": "kriko-agent"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "Kriko Agent cannot run here" in detail
    assert "trial" in detail and "used up" in detail
    assert submitted == []


def test_compare_research_accepts_the_engines_own_choice(client, monkeypatch):
    """A column whose stored agent is not on this machine offers a press that
    asks the engine to resolve one. The empty id has to reach the job: that is
    where `harness_researcher` falls back visibly or says what is missing."""
    http, settings = client
    from app.providers import apiagent, harness
    from app.providers.harness import KNOWN
    selected = next(agent for agent in KNOWN if agent.id == "codex")
    monkeypatch.setattr(apiagent, "available", lambda *a, **k: [])
    monkeypatch.setattr(harness, "available", lambda: [selected])
    lookup_id = _one_lookup(settings, "Acme headset", {"claims": [], "context": {}})
    conn = state.connect(settings.app_state_path)
    try:
        draft = state.save_compare_draft(conn, "Headset", [lookup_id])
    finally:
        conn.close()
    submitted = []
    monkeypatch.setattr(http.app.state.jobs, "submit",
                        lambda kind, params, **kwargs:
                        submitted.append((kind, params, kwargs)) or "quick-job")
    response = http.post(
        f"/api/compare-drafts/{draft['draft_id']}/research",
        json={"lookup_id": lookup_id})
    assert response.status_code == 200
    assert response.json()["harness"] == ""
    kind, params, _ = submitted[0]
    assert kind == "quick_look" and params["harness"] == ""
    assert params["backend"] == "harness"


def test_compare_research_refuses_an_explicit_local_agent_with_no_model(client, monkeypatch):
    """The availability list carries the local row from a stored preference
    without probing the model server, so this press can be the one that
    refuses. Its reason and its `with_search=False` probe are the engine's."""
    http, settings = client
    from app import localplane
    lookup_id = _one_lookup(settings, "Acme headset", {"claims": [], "context": {}})
    conn = state.connect(settings.app_state_path)
    try:
        draft = state.save_compare_draft(conn, "Headset", [lookup_id])
    finally:
        conn.close()
    calls = []
    submitted = []
    monkeypatch.setattr(localplane, "resolve", lambda *a, **k: (
        calls.append(k) or {"ready": False, "reason": "no model downloaded"}))
    monkeypatch.setattr(http.app.state.jobs, "submit",
                        lambda *a, **k: submitted.append((a, k)) or "should-not-queue")
    response = http.post(
        f"/api/compare-drafts/{draft['draft_id']}/research",
        json={"lookup_id": lookup_id, "harness": "local", "backend": "local"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "local agent is unavailable" in detail and "no model downloaded" in detail
    assert calls == [{"with_search": False}]
    assert submitted == []

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


def test_structured_local_completion_probes_only_the_model(monkeypatch, tmp_path):
    from app import localplane
    from app.web.tasks import _local_structured_completer

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
    socket = _local_structured_completer(settings, {}, progress)
    assert probed == [False]
    assert socket.serving_name == "a-larger-model:27b"
    assert socket.reasoning_effort == "none"
    assert "local structured completion" in logged[0]


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


def _local_plane(monkeypatch, *, search_answers: bool):
    """The local plane as `localplane.resolve` reports it: a model server with a
    chat model, and a search service that may or may not be answering."""
    from app import localplane

    def resolve(app_state_path=None, *, url="", model="", search_url="",
                with_search=True):
        plan = {
            "ready": True, "reason": "", "url": "http://127.0.0.1:11434",
            "name": "Ollama", "model": "gemma4:e2b", "models": ["gemma4:e2b"],
            "timeout": 60.0, "search_url": "", "search_kind": "",
            "runtime_options": {}, "context_tokens": 4096,
            "output_language": "auto", "search_language": "en", "line": "",
        }
        if with_search and not search_answers:
            plan.update(ready=False,
                        reason="No local search service is answering at http://127.0.0.1:7070.")
        return plan

    monkeypatch.setattr(localplane, "resolve", resolve)


def test_the_local_agent_is_offered_to_chat_and_compare_when_its_model_answers(
        client, monkeypatch):
    """The picker in Chat and Compare reads `/api/prefs`. A model that answers is
    offered there even with no search service: the picker must not ask for one."""
    http, _ = client
    _local_plane(monkeypatch, search_answers=False)
    harnesses = http.get("/api/prefs").json()["harnesses"]
    assert [row["id"] for row in harnesses if row.get("local")] == ["local"]


def test_a_local_agent_that_is_not_ready_says_why_in_the_picker_payload(client, monkeypatch):
    """Chat and Compare drop an unusable row, so the reason has to travel in the
    payload where the screens can show it, and not only on the Agents tab."""
    from app import localplane

    http, _ = client
    monkeypatch.setattr(localplane, "resolve", lambda *a, **k: {
        "ready": False, "url": "http://127.0.0.1:11434", "name": "Ollama",
        "reason": "Ollama is running but no model is downloaded.", "model": "",
        "models": [], "timeout": 60.0, "search_url": "", "search_kind": "",
        "runtime_options": {}, "context_tokens": 4096, "output_language": "auto",
        "search_language": "en"})
    payload = http.get("/api/prefs").json()
    assert "local" not in [row["id"] for row in payload["harnesses"]]
    unusable = [row for row in payload["unusable"] if row["id"] == "local"]
    assert unusable == [{"id": "local", "label": "Local agent",
                         "why": "Ollama is running but no model is downloaded."}]


def test_a_follow_up_naming_the_local_agent_answers_when_no_search_service_answers(
        client, monkeypatch):
    """A reader picks the Local agent in Compare, the model answers, and no search
    service is running. The run used to reject the pick with "No local search
    service is answering" although the picker had offered it. It now answers from
    the saved checks alone, and says it did not search."""
    from app.providers import local_inference
    from app.web import tasks

    http, settings = client
    _local_plane(monkeypatch, search_answers=False)
    first = _one_lookup(settings, "Acme 5W-30 oil", {
        "claims": [], "context": {"engine": "2.0L"}})
    second = _one_lookup(settings, "Acme 0W-20 oil", {
        "claims": [{"claim_id": "c", "pack_id": "p", "title": "Timing chain",
                    "body": "Stretches early.", "severity": "high"}],
        "context": {},
    })
    made = http.post("/api/compare-drafts",
                     json={"name": "Two oils", "lookup_ids": [first, second]}).json()
    monkeypatch.setattr(http.app.state.jobs, "submit", lambda *_: "queued-test-job")
    asked = http.post(f"/api/compare-drafts/{made['draft_id']}/questions",
                      json={"question": "Which one has the known risk?",
                            "backend": "local", "harness": "local"}).json()

    class Socket:
        def __init__(self, base_url, model, **_kwargs):
            self.model = model
            self.prompts = []

        def __call__(self, prompt):
            self.prompts.append(prompt)
            return "The 0W-20 oil has the timing chain risk, from the saved checks."

    monkeypatch.setattr(local_inference, "OpenAICompatSocket", Socket)
    logged: list[str] = []

    class _Progress:
        job_id = "job-local"
        def log(self, line): logged.append(line)
        def set(self, *a, **k): pass
        def check(self): pass
        def partial(self, result): pass

    result = tasks.compare_ask(settings, {
        "draft_id": made["draft_id"], "question_id": asked["question_id"],
        "question": asked["question"], "backend": "local", "harness": "local"},
        _Progress())
    assert result["answer"].startswith("The 0W-20 oil has the timing chain risk")
    assert result["sources"] == []
    assert result["model"] == "gemma4:e2b"
    assert any("no web search" in line for line in logged)

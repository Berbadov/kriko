"""#261: the log section. "Every step in order with its timing."

The reader asked for one screen that shows, per job, the words searched, each
page and whether it was read, every agent call (sizes, tokens, cost, agent,
model), each retry and why, each verdict and every failure, filterable, with a
row that expands to the exact request and reply and a plain-text export, and
**no secret and none of their saved words in it**.

These tests drive the behaviour through the same doors the app uses: a handler
logging through `Progress`, a researcher wired with `Progress.watch`, and the
HTTP API the screen calls.
"""

import pytest
from fastapi.testclient import TestClient

from app import buyer, redaction
from app.web import state, steps
from app.web.app import create_app
from app.web.jobs import JobRunner
from app.web.settings import Settings

KEY = "sk-live-0123456789abcdefABCDEF"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
        packs_dir=tmp_path / "packs",
    )


@pytest.fixture(autouse=True)
def _fresh_profile_cache():
    steps.forget_private()
    yield
    steps.forget_private()


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def run_job(settings, handler, kind="probe", params=None):
    runner = JobRunner(settings, {kind: handler})
    conn = state.connect(settings.app_state_path)
    try:
        job_id = state.create_job(conn, kind, params or {})
        runner._run(job_id, kind, params or {})
        return job_id
    finally:
        runner.shutdown(wait=True)
        conn.close()


class FakeAgent:
    """The duck-typed surface every plane shares: `ask`, usage counters, a model."""

    name = "harness"
    requested_model = "model-x"

    class harness:  # noqa: N801 - mirrors `researcher.harness.id`
        id = "fake-cli"
        label = "Fake CLI"

    def __init__(self, replies):
        self.replies = list(replies)
        self.tokens_used = None
        self.cost_usd = None
        self.verification = None

    def ask(self, prompt, *, allow_tools=True):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        self.tokens_used = (self.tokens_used or 0) + 120
        return reply


def steps_of(client, job_id, **query):
    return client.get("/api/logs/steps", params={"job_id": job_id, **query}).json()


def test_every_line_a_handler_logs_becomes_a_timed_classified_step(client, settings):
    def handler(settings_, params, progress):
        progress.log('searched "brand model 300 problems"')
        progress.log("fetched https://example.test/forum/thread-1?session=abc")
        progress.log("could not read: https://example.test/blocked")
        progress.log("a note about nothing in particular")
        return {}

    job_id = run_job(settings, handler)
    data = steps_of(client, job_id)
    titles = [one["title"] for one in data["items"]]

    # Lifecycle first and last, the handler's lines in the order it wrote them.
    assert titles[0] == "started" and titles[-1].startswith("succeeded")
    mine = [one for one in data["items"] if one["source"] != "job"]
    assert [one["source"] for one in mine] == ["search", "page", "page", "note"]
    assert mine[0]["detail"]["queries"] == ["brand model 300 problems"]
    # A page the agent opened says it was read, one it could not says it was not,
    # and the address kept in the detail carries no query string.
    assert mine[1]["detail"] == {"urls": ["https://example.test/forum/thread-1"], "read": True}
    assert mine[2]["detail"]["read"] is False and mine[2]["level"] == "error"
    # Each row is timed from the job's start, in order.
    offsets = [one["offset_ms"] for one in data["items"]]
    assert offsets == sorted(offsets) and all(isinstance(value, int) for value in offsets)
    assert data["jobs"][job_id]["errors"] == 1


def test_a_failure_keeps_its_message_and_the_job_says_failed(client, settings):
    def handler(settings_, params, progress):
        progress.log("searched \"x\"")
        raise ValueError("the index refused: key " + KEY)

    job_id = run_job(settings, handler)
    data = steps_of(client, job_id, level="error")
    text = " ".join(one["title"] for one in data["items"])

    assert "ValueError" in text
    assert KEY not in text, "the failure line must not carry the key"
    assert {one["source"] for one in data["items"]} == {"job"}
    assert client.get("/api/logs/jobs").json()["items"][0]["state"] == "failed"


def test_filters_narrow_by_job_level_and_source(client, settings):
    def handler(settings_, params, progress):
        progress.log('searched "a"')
        progress.log("refused “Claim A”: no quote on the page")
        progress.log("kept “Claim B” as c-1")

    one = run_job(settings, handler)
    two = run_job(settings, handler)

    assert {s["job_id"] for s in steps_of(client, one)["items"]} == {one}
    warned = steps_of(client, one, level="warn")["items"]
    assert [s["title"] for s in warned] == ["refused “Claim A”: no quote on the page"]
    assert warned[0]["detail"] == {"verdict": "refused", "subject": "Claim A",
                                   "why": "no quote on the page"}
    verdicts = steps_of(client, "", source="verify")["items"]
    assert {s["job_id"] for s in verdicts} == {one, two}
    assert len(verdicts) == 4
    assert steps_of(client, one, source="search", level="warn")["items"] == []
    assert steps_of(client, one, q="Claim B")["items"][0]["detail"]["verdict"] == "kept"


def test_an_agent_call_records_sizes_tokens_agent_model_and_the_exact_text(client, settings):
    agent = FakeAgent(["the reply text"])

    def handler(settings_, params, progress):
        progress.watch(agent)
        assert agent.ask("the prompt text") == "the reply text"

    job_id = run_job(settings, handler)
    call = next(one for one in steps_of(client, job_id)["items"] if one["source"] == "agent")

    assert call["state"] == "done" and call["tokens"] == 120 and call["usd"] is None
    assert call["detail"]["agent"] == "fake-cli" and call["detail"]["model"] == "model-x"
    assert (call["detail"]["prompt_chars"], call["detail"]["reply_chars"]) == (15, 14)
    assert isinstance(call["ms"], int)
    full = client.get(f"/api/logs/steps/{call['step_id']}").json()
    assert (full["request"], full["response"]) == ("the prompt text", "the reply text")
    job = client.get("/api/logs/jobs").json()["items"][0]
    assert (job["calls"], job["tokens"]) == (1, 120)


def test_a_failed_call_then_a_second_one_is_a_retry_that_says_why(client, settings):
    agent = FakeAgent([RuntimeError("the CLI exited 1: rate limit"), "second try"])

    def handler(settings_, params, progress):
        progress.watch(agent)
        progress.watch(agent)  # wired twice, as the chat path does; one wrapper
        with pytest.raises(RuntimeError):
            agent.ask("first")
        agent.ask("first again")

    job_id = run_job(settings, handler)
    rows = steps_of(client, job_id)["items"]
    calls = [one for one in rows if one["source"] == "agent"]
    retry = next(one for one in rows if one["source"] == "retry")

    assert [call["state"] for call in calls] == ["failed", "done"]
    assert calls[0]["level"] == "error" and "rate limit" in calls[0]["title"]
    assert "rate limit" in retry["title"] and retry["detail"]["attempt"] == 2
    assert calls[1]["detail"]["attempt"] == 2
    assert client.get("/api/logs/jobs").json()["items"][0]["retries"] == 1


def test_a_nested_call_is_one_call_and_its_totals_are_counted_once(client, settings):
    class Nesting(FakeAgent):
        def ask_quick(self, product):
            return self.ask("brief for " + product)

    agent = Nesting(["answer"])

    def handler(settings_, params, progress):
        progress.watch(agent)
        agent.ask_quick("Acme X")

    job_id = run_job(settings, handler)
    rows = steps_of(client, job_id)["items"]
    outer, inner = [one for one in rows if one["source"] == "agent"]

    assert inner["parent_id"] == outer["step_id"] and (outer["depth"], inner["depth"]) == (0, 1)
    job = client.get("/api/logs/jobs").json()["items"][0]
    assert (job["calls"], job["tokens"]) == (1, 120)


def test_no_secret_and_none_of_the_readers_saved_words_reach_the_log(client, settings, monkeypatch):
    monkeypatch.setenv("ACME_API_KEY", KEY)
    conn = state.connect(settings.app_state_path)
    buyer.save(conn, {"about": "I tow a caravan with a small diesel estate"})
    conn.close()
    agent = FakeAgent([f"answer quoting {KEY} and Authorization: Bearer abc.def.ghi"])
    prompt = ("Question\n\n## About this reader\nI tow a caravan with a small diesel estate\n"
              f"header api_key={KEY}")

    def handler(settings_, params, progress):
        progress.watch(agent)
        agent.ask(prompt)
        progress.log("the profile says: I tow a caravan with a small diesel estate")

    job_id = run_job(settings, handler)
    rows = steps_of(client, job_id)["items"]
    call = next(one for one in rows if one["source"] == "agent")
    full = client.get(f"/api/logs/steps/{call['step_id']}").json()
    exported = client.get("/api/logs/export", params={"job_id": job_id, "bodies": True}).json()["text"]

    everything = " ".join([full["request"], full["response"], exported]
                          + [one["title"] for one in rows])
    assert KEY not in everything
    assert "abc.def.ghi" not in everything
    assert "caravan" not in everything
    assert "[saved profile]" in full["request"]
    # Not merely hidden on the way out: the file on disk never holds them.
    kept = state.connect(settings.app_state_path)
    on_disk = " ".join(" ".join(str(part) for part in row) for row in kept.execute(
        "SELECT title, detail_json, request, response FROM job_steps"))
    kept.close()
    assert KEY not in on_disk and "caravan" not in on_disk and "abc.def.ghi" not in on_disk


def test_the_log_survives_a_restart_and_a_call_in_flight_ends_as_failed(settings):
    conn = state.connect(settings.app_state_path)
    job_id = state.create_job(conn, "probe", {})
    state.start_job(conn, job_id)
    state.update_job(conn, job_id, line='searched "kept across a restart"')
    steps.record(conn, job_id, source="agent", state="running", title="ask: Fake CLI")
    conn.commit()
    conn.close()

    # A new process: the same file, and the startup reconciliation.
    again = state.connect(settings.app_state_path)
    state.interrupt_running(again)
    data = steps.list_steps(again, job_id=job_id)
    again.close()

    by_title = {one["title"]: one for one in data["items"]}
    assert 'searched "kept across a restart"' in by_title
    assert by_title["ask: Fake CLI"]["state"] == "failed"
    assert any(one["title"].startswith("interrupted") for one in data["items"])


def test_steps_go_when_their_job_is_pruned(settings, monkeypatch):
    monkeypatch.setattr(state, "JOBS_KEPT", 1)
    conn = state.connect(settings.app_state_path)
    old = state.create_job(conn, "probe", {})
    state.start_job(conn, old)
    state.finish_job(conn, old, state.SUCCEEDED)
    new = state.create_job(conn, "probe", {})
    state.start_job(conn, new)
    state.finish_job(conn, new, state.SUCCEEDED)

    assert state.get_job(conn, old) is None
    assert steps.list_steps(conn, job_id=old)["items"] == []
    assert steps.list_steps(conn, job_id=new)["items"]
    conn.close()


def test_a_busy_job_cannot_bury_its_own_failure(settings, monkeypatch):
    monkeypatch.setattr(steps, "STEPS_PER_JOB", 5)
    conn = state.connect(settings.app_state_path)
    job_id = state.create_job(conn, "probe", {})
    for number in range(20):
        state.update_job(conn, job_id, line=f"note {number}")
    state.update_job(conn, job_id, line="job failed at x.py:1: ValueError: nope")
    data = steps.list_steps(conn, job_id=job_id)
    conn.close()

    assert len(data["items"]) == 6
    assert data["items"][-1]["level"] == "error"


def test_the_export_is_plain_text_in_order_and_bodies_are_opt_in(client, settings):
    agent = FakeAgent(["a reply"])

    def handler(settings_, params, progress):
        progress.log('searched "export me"')
        progress.watch(agent)
        agent.ask("a prompt")

    job_id = run_job(settings, handler, params={"product": "Acme X 300"})
    plain = client.get("/api/logs/export", params={"job_id": job_id}).json()
    full = client.get("/api/logs/export", params={"job_id": job_id, "bodies": True}).json()

    assert plain["filename"].startswith(f"kriko-log-{job_id}-") and plain["filename"].endswith(".txt")
    assert "Acme X 300" in plain["text"] and 'searched "export me"' in plain["text"]
    assert plain["text"].index("started") < plain["text"].index("export me")
    assert "a prompt" not in plain["text"] and "a prompt" in full["text"]
    assert "a reply" in full["text"]
    assert client.get("/api/logs/export", params={"job_id": "nope"}).status_code == 404


def test_a_browser_extension_cannot_read_the_log(client, settings):
    run_job(settings, lambda *_: None)
    refused = client.get("/api/logs/jobs", headers={"Origin": "chrome-extension://abcdef"})
    allowed = client.get("/api/logs/jobs", headers={"Origin": "http://127.0.0.1:1420"})

    assert refused.status_code == 403
    assert allowed.status_code == 200


def test_the_shared_redactor_is_what_the_benchmark_traces_use(monkeypatch):
    from app.searchbench.__main__ import redact

    monkeypatch.setenv("MERCURY_API_KEY", "mercury-secret-value")
    assert "mercury-secret-value" not in redact({"header": "Bearer mercury-secret-value"})
    assert redaction.redact_json({"k": "plain"}, ["MERCURY_API_KEY"]) == '{"k": "plain"}'
    assert "the-value-8" not in redaction.redact_text(
        "x the-value-8 y", env={"SOME_TOKEN": "the-value-8"})


def test_a_slow_call_is_visible_while_it_runs(client, settings):
    seen = {}

    class Slow(FakeAgent):
        def ask(self, prompt, *, allow_tools=True):
            conn = state.connect(settings.app_state_path)
            seen["rows"] = steps.list_steps(conn, job_id=seen["job"])["items"]
            conn.close()
            return "late"

    agent = Slow([])

    def handler(settings_, params, progress):
        seen["job"] = progress.job_id
        progress.watch(agent)
        agent.ask("hello")

    run_job(settings, handler)
    running = [one for one in seen["rows"] if one["source"] == "agent"]
    assert [one["state"] for one in running] == ["running"]

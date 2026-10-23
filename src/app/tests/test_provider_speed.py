"""Provider startup and first-text latency, measured with fake processes.

The provider controls remote model latency. Kriko controls whether a CLI
probe blocks a screen and whether a text delta waits for a sentence before it
reaches the job row. These tests measure those local parts without credentials.
"""

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace

import pytest

from app.providers import harness
from app import providers
from app.web import state
from app.web.jobs import Progress


def test_api_agent_stops_waiting_for_a_transport_that_ignores_its_timeout(tmp_path):
    from app.providers import apiagent, mistral

    release = threading.Event()
    researcher = apiagent.ApiAgentResearcher(apiagent.MISTRAL, home=tmp_path, timeout=0.15)

    def stalled(*_args, **_kwargs):
        release.wait(3)
        return mistral.Reply(text="too late")

    researcher._stream_converse = stalled
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="did not finish"):
            researcher.ask("A bounded request")
        assert time.monotonic() - started < 0.8
    finally:
        release.set()

def _row(one_id: str = "antigravity-cli") -> harness.Harness:
    from app.tests.harness_fixtures import row

    return row(one_id)


def test_cold_model_discovery_does_not_hold_the_agents_screen(monkeypatch, tmp_path):
    one = replace(_row(), id="slow-listing", model_source="models")
    monkeypatch.setattr(harness, "locate", lambda _one: str(tmp_path / "cli"))
    monkeypatch.setattr(harness, "_MODELS", {})
    monkeypatch.setattr(harness, "_ASKING", {})
    started = threading.Event()
    calls = []

    def slow_listing(_one, _executable):
        calls.append(time.monotonic())
        started.set()
        time.sleep(0.25)
        return ["vendor/model-a"]

    monkeypatch.setattr(harness, "_from_models_command", slow_listing)
    began = time.monotonic()
    first = harness.models_for_each([one])
    elapsed = time.monotonic() - began

    assert elapsed < 0.1, f"cold model discovery blocked for {elapsed:.3f}s"
    assert first == {one.id: []}
    assert started.wait(0.5)
    for _ in range(4):
        assert harness.models_for_each([one]) == {one.id: []}
    assert len(calls) == 1, "repeated screen reads spawned duplicate model probes"
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        rows = harness.models_for_each([one])
        if rows[one.id]:
            break
        time.sleep(0.01)
    assert rows == {one.id: ["vendor/model-a"]}


def test_first_cli_text_delta_reaches_the_live_callback_before_exit(tmp_path):
    sentinel = tmp_path / "first-fragment-was-seen"
    emitted = tmp_path / "emitted-at"
    exited = tmp_path / "exited-at"
    script = tmp_path / "fake_cli.py"
    script.write_text(
        "import json, pathlib, sys, time\n"
        f"pathlib.Path({str(emitted)!r}).write_text(str(time.monotonic()))\n"
        "event = {'event':'step_update','step_update':"
        "{'step_type':'agent_response','state':'ACTIVE','text_delta':'The'}}\n"
        "print(json.dumps(event), flush=True)\n"
        f"deadline = time.monotonic() + 0.5\nwhile time.monotonic() < deadline and not pathlib.Path({str(sentinel)!r}).exists(): time.sleep(0.005)\n"
        f"seen = pathlib.Path({str(sentinel)!r}).exists()\n"
        "if not seen: raise SystemExit(7)\n"
        "print(json.dumps({'event':'step_update','step_update':"
        "{'step_type':'agent_response','state':'DONE','text_delta':' model is ready.'}}), flush=True)\n"
        f"pathlib.Path({str(exited)!r}).write_text(str(time.monotonic()))\n",
        encoding="utf-8",
    )
    one = replace(_row(), executable=sys.executable)
    researcher = harness.HarnessResearcher(one, timeout=3)
    heard: list[tuple[float, str]] = []

    def live(text: str) -> None:
        heard.append((time.monotonic(), text))
        sentinel.write_text("seen", encoding="utf-8")

    researcher.on_text = live
    researcher.on_action = lambda _line: None
    code, _, _ = researcher._stream(
        [sys.executable, str(script)], subprocess.DEVNULL, researcher.on_action
    )

    assert heard, "the first text fragment was buffered until the CLI finished"
    assert heard[0][1].startswith("The")
    assert code == 0, "the fake provider exited before the callback could run"
    assert sentinel.exists(), "the child did not observe the reader before exiting"
    first_delay = heard[0][0] - float(emitted.read_text(encoding="utf-8"))
    assert first_delay < 0.25, f"local first-fragment delay was {first_delay:.3f}s"
    assert heard[0][0] < float(exited.read_text(encoding="utf-8"))


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX executable fixture")
def test_configured_first_ask_pays_only_one_verified_help_probe(tmp_path, monkeypatch):
    """Measure the full selected-provider path, not only the stream reader."""
    one = replace(_row("claude-code"), executable=str(tmp_path / "fake-claude"))
    emitted = tmp_path / "emitted"
    sentinel = tmp_path / "callback-seen"
    script = tmp_path / "fake-claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys, time\n"
        "if '--help' in sys.argv[1:]:\n"
        "    time.sleep(0.15)\n"
        "    print('''--output-format <format> stream-json\\n--verbose\\n"
        "--allowedTools <tools...>\\n--strict-mcp-config\\n--safe-mode\\n"
        "--include-partial-messages\\n--tools <tools...>\\n"
        "--mcp-config <path>\\n--effort <level>\\n--model <model>\\n"
        "--max-budget-usd <amount>\\n--input-format <format>''')\n"
        "    raise SystemExit(0)\n"
        f"pathlib.Path({str(emitted)!r}).write_text(str(time.monotonic()))\n"
        "print(json.dumps({'type':'stream_event','event':{'type':"
        "'content_block_delta','delta':{'type':'text_delta',"
        "'text':'The first fragment'}}}), flush=True)\n"
        f"deadline = time.monotonic() + 0.5\nwhile time.monotonic() < deadline and not pathlib.Path({str(sentinel)!r}).exists(): time.sleep(0.005)\n"
        f"if not pathlib.Path({str(sentinel)!r}).exists(): raise SystemExit(7)\n"
        "print(json.dumps({'type':'result','result':'done','usage':{}}), flush=True)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setattr(harness, "locate", lambda _one: str(script))
    monkeypatch.setattr(providers, "resolve_agent", lambda *_a, **_kw: (one, ""))
    monkeypatch.setattr(harness, "_HELP", {})
    monkeypatch.setattr(harness, "_DECLARED", {})
    monkeypatch.setattr(harness, "_HELP_LOCKS", {})
    heard = []
    researcher = providers.harness_researcher(
        preferred=one.id, model="sonnet", effort="low",
    )
    researcher.on_text = lambda text: (
        heard.append((time.monotonic(), text)),
        sentinel.write_text("seen", encoding="utf-8"),
    )

    began = time.monotonic()
    assert researcher.ask("brief") == "done"
    total = heard[0][0] - began
    after_provider_emission = heard[0][0] - float(emitted.read_text(encoding="utf-8"))

    assert heard and heard[0][1].startswith("The first fragment")
    assert 0.14 <= total < 0.75, f"full cold configured startup took {total:.3f}s"
    assert after_provider_emission < 0.25, (
        f"local post-emission delay was {after_provider_emission:.3f}s"
    )
    assert set(harness.declared(str(script))) >= {"--safe-mode", "--allowedTools"}


def test_mistral_sse_stream_preserves_typed_text_search_results_and_usage(monkeypatch):
    from app.providers import mistral

    seen: list[str] = []
    events = [
        {"event": "message.output.delta", "data": {
            "type": "message.output.delta", "output_index": 0,
            "content": "The result is "}},
        {"event": "message.output.delta", "data": {
            "type": "message.output.delta", "output_index": 0,
            "content": [{"type": "text", "text": "grounded."},
                        {"type": "citation", "url": "https://source.example"}]}},
        {"event": "tool.execution.started", "data": {
            "type": "tool.execution.started", "id": "call-1",
            "arguments": {"query": "source query"}}},
        {"event": "tool.execution.done", "data": {
            "type": "tool.execution.done", "id": "call-1",
            "info": {"result": {"0": {
                "url": "https://source.example", "title": "Source",
                "snippets": ["The result is grounded."],
            }}}}},
        {"event": "conversation.response.done", "data": {
            "type": "conversation.response.done",
            "usage": {"prompt_tokens": 12, "completion_tokens": 5,
                      "connectors": {"web_search": 1}}}},
    ]

    def fake_sse(_url, _payload, _headers, _timeout, callback, *, cancel_event=None):
        assert cancel_event is None
        for one in events:
            callback(one)
        return len(events), ""

    monkeypatch.setattr(mistral, "post_sse_or_why", fake_sse)
    reply = mistral.converse_stream("brief", api_key="test-key", on_text=seen.append)
    assert seen == ["The result is ", "grounded."]
    assert reply.text == "The result is grounded."
    assert reply.queries == ["source query"]
    assert reply.sources["https://source.example"]["text"] == "The result is grounded."
    assert (reply.tokens_in, reply.tokens_out, reply.tool_calls) == (12, 5, 1)


def test_mistral_sse_eof_without_response_done_is_not_success(monkeypatch):
    from app.providers import mistral

    def fake_sse(_url, _payload, _headers, _timeout, callback, *, cancel_event=None):
        callback({"type": "message.output.delta", "output_index": 0,
                  "content": "partial answer"})
        return 1, ""

    monkeypatch.setattr(mistral, "post_sse_or_why", fake_sse)
    reply = mistral.converse_stream("brief", api_key="test-key")
    assert reply.text == ""
    assert "before its completion event" in reply.error


def test_mistral_toolless_completion_omits_the_web_search_tool(monkeypatch):
    from app.providers import mistral

    sent = {}

    def fake_sse(_url, payload, _headers, _timeout, callback, *, cancel_event=None):
        sent.update(payload)
        callback({"type": "message.output.delta", "output_index": 0,
                  "content": "classified"})
        callback({"type": "conversation.response.done", "usage": {
            "prompt_tokens": 11, "completion_tokens": 2,
        }})
        return 2, ""

    monkeypatch.setattr(mistral, "post_sse_or_why", fake_sse)
    reply = mistral.converse_stream("classify only", api_key="test-key", search=False)

    assert reply.text == "classified"
    assert "tools" not in sent
    assert sent["store"] is False


def test_classifier_completion_passes_explicit_no_tools_to_the_api(monkeypatch):
    from app.providers import apiagent, mistral

    seen = {}

    def fake_stream(prompt, *, model, timeout, search, on_text, cancel_event):
        seen.update(prompt=prompt, search=search)
        return mistral.Reply(text='{"decision":"uncertain"}')

    monkeypatch.setattr(mistral, "converse_stream", fake_stream)
    researcher = apiagent.ApiAgentResearcher(apiagent.MISTRAL)
    reply = researcher.ask("saved listing and catalog definitions", allow_tools=False)

    assert reply == '{"decision":"uncertain"}'
    assert seen == {"prompt": "saved listing and catalog definitions", "search": False}


def test_cli_classifier_request_fails_closed_before_spawn(monkeypatch):
    one = _row("claude-code")
    researcher = harness.HarnessResearcher(one)

    def should_not_run(*_args, **_kwargs):
        pytest.fail("a CLI without a verified no-tools mode must not spawn")

    monkeypatch.setattr(researcher, "_run", should_not_run)
    with pytest.raises(harness.NoHarness, match="no verified tool-less completion"):
        researcher.ask("saved listing classification", allow_tools=False)


def test_sse_callback_error_is_not_relabelled_as_a_transport_failure(monkeypatch):
    from app.providers import _http

    class Response:
        def __enter__(self):
            return iter([b'data: {"type":"example"}\n', b"\n"])

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(_http.urllib.request, "urlopen", lambda *_a, **_kw: Response())

    def broken(_event):
        raise ValueError("cancel in the caller")

    with pytest.raises(ValueError, match="cancel in the caller"):
        _http.post_sse_or_why("https://api.example/sse", {}, {}, 1, broken)


def test_sse_cancellation_closes_a_blocked_response(monkeypatch):
    from app.providers import _http

    entered = threading.Event()
    closed = threading.Event()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()
            return False

        def __iter__(self):
            entered.set()
            closed.wait(1)
            if closed.is_set():
                return
            yield b"data: {}\n"

        def close(self):
            closed.set()

    monkeypatch.setattr(_http.urllib.request, "urlopen", lambda *_a, **_kw: Response())
    cancel = threading.Event()
    outcomes = []

    def read():
        try:
            _http.post_sse_or_why("https://api.example/sse", {}, {}, 2,
                                  lambda _event: None, cancel_event=cancel)
        except _http.StreamCancelled:
            outcomes.append("cancelled")

    worker = threading.Thread(target=read)
    worker.start()
    assert entered.wait(0.5)
    began = time.monotonic()
    cancel.set()
    worker.join(0.3)
    elapsed = time.monotonic() - began

    assert not worker.is_alive(), "the reader left the provider socket blocked after cancel"
    assert closed.is_set(), "cancel did not close the streaming response"
    assert outcomes == ["cancelled"]
    assert elapsed < 0.25


def test_api_agent_publishes_first_sse_delta_without_waiting_for_completion(monkeypatch, tmp_path):
    from app.providers import apiagent, mistral

    entered = threading.Event()
    release = threading.Event()

    def fake_stream(_prompt, *, model, timeout, on_text, search, cancel_event=None):
        assert search is True
        on_text("The first sentence is visible.")
        entered.set()
        assert release.wait(1)
        return mistral.Reply(text='{"findings":[]}')

    monkeypatch.setattr(mistral, "converse_stream", fake_stream)
    researcher = apiagent.ApiAgentResearcher(apiagent.MISTRAL, home=tmp_path)
    seen: list[tuple[float, str]] = []
    researcher.on_text = lambda text: seen.append((time.monotonic(), text))
    outcome = []
    worker = threading.Thread(target=lambda: outcome.append(researcher.ask("brief")))
    began = time.monotonic()
    worker.start()
    assert entered.wait(0.5)
    deadline = time.monotonic() + 0.25
    while not seen and time.monotonic() < deadline:
        time.sleep(0.005)
    first_seen = time.monotonic()
    release.set()
    worker.join(1)

    assert seen and seen[0][1].startswith("The first sentence")
    assert first_seen - began < 0.2
    assert outcome == ['{"findings":[]}']


def test_api_job_cancellation_closes_its_sse_reader(monkeypatch, tmp_path):
    from app.providers import _http, apiagent, mistral

    entered = threading.Event()
    closed = threading.Event()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()
            return False

        def __iter__(self):
            yield (b'data: {"type":"message.output.delta","output_index":0,'
                   b'"content":"The partial answer"}\n')
            yield b"\n"
            entered.set()
            while not closed.is_set():
                time.sleep(0.002)
            return

        def close(self):
            closed.set()

    monkeypatch.setattr(mistral, "require", lambda _key: "fixture-key")
    monkeypatch.setattr(_http.urllib.request, "urlopen", lambda *_a, **_kw: Response())
    researcher = apiagent.ApiAgentResearcher(apiagent.MISTRAL, home=tmp_path)
    researcher._cancel_tick = 0.001
    seen: list[str] = []
    researcher.on_text = seen.append

    class Cancelled(Exception):
        pass

    checks = 0

    def check_cancelled():
        nonlocal checks
        checks += 1
        if checks > 1:
            raise Cancelled

    researcher.check_cancelled = check_cancelled
    began = time.monotonic()
    with pytest.raises(Cancelled):
        researcher.ask("brief")
    cancel_latency = time.monotonic() - began
    assert entered.wait(0.3)
    assert closed.wait(0.3), "job cancellation left its SSE response open"
    snapshots = list(seen)
    time.sleep(0.05)
    assert seen == snapshots, "the API worker published a draft after cancellation"
    assert cancel_latency < 0.2


def test_concurrent_capability_reads_share_one_help_process(monkeypatch):
    monkeypatch.setattr(harness, "_HELP", {})
    monkeypatch.setattr(harness, "_DECLARED", {})
    monkeypatch.setattr(harness, "_HELP_LOCKS", {})
    calls = []
    gate = threading.Barrier(3)

    def slow_help(executable, *_argv, **_kwargs):
        calls.append(executable)
        time.sleep(0.1)
        return "--safe-mode\n--allowedTools"

    monkeypatch.setattr(harness, "_ask", slow_help)

    def read():
        gate.wait()
        return harness.declared("fake-cli")

    workers = [threading.Thread(target=read) for _ in range(2)]
    for worker in workers:
        worker.start()
    gate.wait()
    for worker in workers:
        worker.join(timeout=1)
        assert not worker.is_alive()
    assert calls == ["fake-cli"]


def test_structured_output_does_not_leak_json_into_live_draft():
    researcher = harness.HarnessResearcher(_row())
    seen: list[str] = []
    researcher.on_text = seen.append
    researcher._draft_from_event({
        "event": "step_update",
        "step_update": {"step_type": "agent_response", "state": "ACTIVE",
                         "text_delta": "{\"findings\":["},
    })
    assert seen == []


def test_partial_assistant_text_is_not_logged_again_when_the_final_event_arrives():
    researcher = harness.HarnessResearcher(_row("claude-code"))
    researcher.on_text = lambda _text: None
    partial = {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {
            "type": "text_delta", "text": "The search is underway."}},
    }
    final = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "The search is underway."},
    ]}}
    researcher._draft_from_event(partial)
    assert researcher._narrate(json.dumps(final)) == ""


def test_live_draft_stays_bounded_and_restores_the_phase_message(monkeypatch):
    writes: list[dict] = []

    def capture(_conn, _job, **changes):
        writes.append(changes)

    monkeypatch.setattr(state, "update_job", capture)
    progress = Progress("job", object())
    progress.set(0.2, "harness plane (subscription)")
    progress.draft("x" * 20_000, force=True)
    assert len(writes[-1]["message"]) <= 8_192
    assert writes[-1]["message"].startswith("Writing: ")
    progress.draft("", force=True)
    assert writes[-1]["message"] == "harness plane (subscription)"


def test_effort_discovery_can_be_read_without_waiting_for_a_cli(monkeypatch, tmp_path):
    one = _row("antigravity-cli")
    monkeypatch.setattr(harness, "locate", lambda _one: str(tmp_path / "agy"))
    monkeypatch.setattr(harness, "_HELP", {})
    monkeypatch.setattr(harness, "_DECLARED", {})
    monkeypatch.setattr(harness, "_EFFORTS", {})
    monkeypatch.setattr(harness, "_EFFORT_PENDING", set())
    started = threading.Event()

    def slow_help(_executable, *_argv, **_kwargs):
        started.set()
        time.sleep(0.25)
        return "--effort (low, medium, high)"

    monkeypatch.setattr(harness, "_ask", slow_help)
    began = time.monotonic()
    first = harness.efforts_for_each([one])
    elapsed = time.monotonic() - began
    assert elapsed < 0.1, f"cold effort discovery blocked for {elapsed:.3f}s"
    assert first == {one.id: []}
    assert started.wait(0.5)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        rows = harness.efforts_for_each([one])
        if rows[one.id]:
            break
        time.sleep(0.01)
    assert rows == {one.id: ["low", "medium", "high"]}

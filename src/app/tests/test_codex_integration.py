"""The research path uses isolated transport and accounts for actual usage."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.agentledger import Ledger
from app.providers import codex_profile, harness
from app.providers.codex_transport import DeliveryUncertain, TransportUnavailable
from app.providers.harness import NoHarness
from app.tests.harness_fixtures import row


def _researcher(monkeypatch, tmp_path):
    executable = tmp_path / "fixture-codex"
    executable.write_text("fixture", encoding="utf-8")
    chosen = replace(row("codex"), executable=str(executable))
    harness._CODEX_SUPPORT.clear()
    monkeypatch.setattr(harness, "locate", lambda _: str(executable))
    monkeypatch.setattr(harness, "_ask", lambda *args, **kwargs: "--listen")
    monkeypatch.setattr(codex_profile, "profile", lambda *args, **kwargs: kwargs)
    return harness.HarnessResearcher(chosen, model="selected-model", effort="low",
                                     app_state_path=tmp_path / "app.sqlite")


def test_fresh_protocol_contexts_preserve_selection_count_usage_and_hide_json(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path)
    calls, drafts = [], []
    researcher.on_text = drafts.append

    def run(profile, request, **callbacks):
        calls.append((profile, request.prompt))
        thread = f"thread-{len(calls)}"
        callbacks["on_delivery"]("unknown", thread, "")
        callbacks["on_delivery"]("accepted", thread, "turn")
        callbacks["on_text"]('{"risks":[]')
        return SimpleNamespace(text='{"risks":[],"specs":[]}', thread_id=thread,
            turn_id="turn", usage={"last": {"inputTokens": 12, "outputTokens": 4}},
            metrics={"reused_worker": len(calls) > 1})

    monkeypatch.setattr(codex_profile, "transport", lambda: SimpleNamespace(run=run))
    first = researcher._run("Research the first product")
    second = researcher._run("Research a different product")
    assert first == second == '{"risks":[],"specs":[]}'
    assert calls[0][0]["model"] == "selected-model"
    assert calls[0][0]["effort"] == "low"
    assert researcher.tokens_used == 32
    assert not any('"risks"' in draft for draft in drafts)
    assert researcher.runtime["context_id"] == "thread-2"
    ledger = Ledger(tmp_path / "app.sqlite")
    conn = ledger.connect()
    try:
        records = conn.execute("SELECT run_id FROM agent_runs").fetchall()
    finally:
        conn.close()
    assert len(records) == 2
    assert all(ledger.lookup(record[0])["state"] == "succeeded" for record in records)
    assert all(ledger.attempts(record[0])[0]["delivery"] == "accepted" for record in records)


def test_uncertain_delivery_does_not_fall_back_to_a_second_process(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(researcher, "_run_codex", lambda *args: (_ for _ in ()).throw(
        DeliveryUncertain("request may have been accepted")))
    monkeypatch.setattr(researcher, "_invoke", lambda *args: calls.append("replayed"))
    with pytest.raises(DeliveryUncertain):
        researcher._run("one request")
    assert calls == []


def test_cancellation_is_recorded_as_cancelled_not_failed(monkeypatch, tmp_path):
    from app.web.jobs import Cancelled

    researcher = _researcher(monkeypatch, tmp_path)

    def run(profile, request, **callbacks):
        callbacks["on_delivery"]("accepted", "thread", "turn")
        raise Cancelled()

    monkeypatch.setattr(codex_profile, "transport", lambda: SimpleNamespace(run=run))
    with pytest.raises(Cancelled):
        researcher._run("one request")
    ledger = Ledger(tmp_path / "app.sqlite")
    conn = ledger.connect()
    try:
        run_id = conn.execute("SELECT run_id FROM agent_runs").fetchone()[0]
    finally:
        conn.close()
    assert ledger.lookup(run_id)["state"] == "cancelled"
    assert ledger.attempts(run_id)[0]["outcome"] == "cancelled"


def test_a_failed_attempt_records_why_not_only_its_class(monkeypatch, tmp_path):
    """The run history read "DeliveryUncertain" for every failed turn, with no
    reason, which is a blank failure on the screen that shows the history."""
    researcher = _researcher(monkeypatch, tmp_path)

    def run(profile, request, **callbacks):
        callbacks["on_delivery"]("accepted", "thread", "turn")
        raise DeliveryUncertain("Codex delivery became uncertain: model overloaded")

    monkeypatch.setattr(codex_profile, "transport", lambda: SimpleNamespace(run=run))
    with pytest.raises(DeliveryUncertain):
        researcher._run("one request")
    ledger = Ledger(tmp_path / "app.sqlite")
    conn = ledger.connect()
    try:
        run_id = conn.execute("SELECT run_id FROM agent_runs").fetchone()[0]
    finally:
        conn.close()
    assert ledger.attempts(run_id)[0]["error"] == (
        "DeliveryUncertain: Codex delivery became uncertain: model overloaded")


def test_an_unanswered_help_probe_is_asked_again_not_remembered(monkeypatch, tmp_path):
    """`_ask` answers "" when the probe times out. Remembering that as "no
    app-server" demoted the binary to a process for the life of the app."""
    researcher = _researcher(monkeypatch, tmp_path)
    answers = iter(["", "--listen"])
    monkeypatch.setattr(harness, "_ask", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(codex_profile, "transport", lambda: SimpleNamespace(run=lambda profile, request, **callbacks: SimpleNamespace(
        text="answer", thread_id="thread", turn_id="turn", usage={}, events=(), metrics={})))
    researcher.transport_mode = "persistent"
    with pytest.raises(TransportUnavailable, match="did not describe its app-server"):
        researcher._run("one request")
    assert researcher._run("one request") == "answer"


def test_pre_delivery_unavailability_falls_back_only_in_auto_mode(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path)
    monkeypatch.setattr(researcher, "_run_codex", lambda *args: (_ for _ in ()).throw(
        TransportUnavailable("unsupported protocol")))
    monkeypatch.setattr(researcher, "_invoke", lambda *args: "legacy answer")
    assert researcher._run("one request") == "legacy answer"
    researcher.transport_mode = "persistent"
    with pytest.raises(TransportUnavailable):
        researcher._run("one request")


def test_tool_dependent_codex_ask_uses_exec_before_delivery_in_auto(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path)
    researcher.transport_mode = "auto"
    observed = []
    monkeypatch.setattr(
        researcher, "_run",
        lambda prompt: observed.append((researcher.transport_mode, prompt)) or "answer",
    )

    assert researcher.ask("Build a pack using the MCP catalog") == "answer"
    assert observed[0][0] == "exec"
    assert "Build a pack using the MCP catalog" in observed[0][1]
    assert researcher.transport_mode == "auto"


def test_tool_dependent_codex_ask_in_persistent_mode_refuses_before_delivery(
    monkeypatch, tmp_path,
):
    researcher = _researcher(monkeypatch, tmp_path)
    researcher.transport_mode = "persistent"
    monkeypatch.setattr(researcher, "_run", lambda *_: pytest.fail("prompt was delivered"))

    with pytest.raises(NoHarness, match="persistent transport has web/MCP tools disabled"):
        researcher.ask("Build a pack using the MCP catalog")
    assert researcher.transport_mode == "persistent"


def test_toolless_codex_completion_uses_persistent_protocol_and_restores_auto(
    monkeypatch, tmp_path,
):
    researcher = _researcher(monkeypatch, tmp_path)
    researcher.transport_mode = "auto"
    observed = []
    monkeypatch.setattr(
        researcher, "_run",
        lambda prompt: observed.append((researcher.transport_mode, prompt)) or "answer",
    )

    assert researcher.ask("Classify this saved listing", allow_tools=False) == "answer"
    assert observed[0][0] == "persistent"
    assert "Classify this saved listing" in observed[0][1]
    assert researcher.transport_mode == "auto"


def test_host_read_codex_answer_uses_toolless_completion(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path)
    reader = SimpleNamespace(
        page_titles={"https://example.com/manual": "Manual"},
        search_coverage={"pages_read": 1},
        telemetry={"stages": []},
    )
    monkeypatch.setattr(
        researcher, "_read_web_pages",
        lambda *args, **kwargs: (reader, [("https://example.com/manual", "host-read evidence")], None),
    )
    observed = []
    monkeypatch.setattr(
        researcher, "_run",
        lambda prompt: observed.append((researcher.transport_mode, prompt)) or "grounded answer",
    )

    assert researcher._ask_with_pages(["query"], "research prompt") == "grounded answer"
    assert observed[0][0] == "persistent"
    assert "host-read evidence" in observed[0][1]
    assert researcher.transport_mode == "auto"


def test_host_read_codex_answer_respects_explicit_exec_mode(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path)
    researcher.transport_mode = "exec"
    reader = SimpleNamespace(
        page_titles={"https://example.com/manual": "Manual"},
        search_coverage={"pages_read": 1},
        telemetry={"stages": []},
    )
    monkeypatch.setattr(
        researcher, "_read_web_pages",
        lambda *args, **kwargs: (reader, [("https://example.com/manual", "host-read evidence")], None),
    )
    observed = []
    monkeypatch.setattr(
        researcher, "_run",
        lambda prompt: observed.append((researcher.transport_mode, prompt)) or "grounded answer",
    )

    assert researcher._ask_with_pages(["query"], "research prompt") == "grounded answer"
    assert observed[0][0] == "exec"
    assert researcher.transport_mode == "exec"


def _install_failed_host_reader(monkeypatch, researcher):
    reader = SimpleNamespace(
        page_titles={},
        search_coverage={"search_errors": ["host search offline"], "queries_searched": 0, "pages_read": 0},
        telemetry={"stages": []},
        sources={},
        search_provider="openserp",
    )
    monkeypatch.setattr(researcher, "_read_web_pages", lambda *args, **kwargs: (reader, [], None))
    monkeypatch.setattr(researcher, "_echo", lambda *_args, **_kwargs: None)


def test_auto_uses_exec_before_native_web_prompt_and_restores_mode(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path)
    _install_failed_host_reader(monkeypatch, researcher)
    researcher.transport_mode = "auto"
    observed = []

    def ask(prompt):
        observed.append((researcher.transport_mode, prompt))
        return "answer from native web search"

    monkeypatch.setattr(researcher, "ask", ask)
    result = researcher._ask_with_pages(["query"], "research prompt")
    assert result == "answer from native web search"
    assert observed[0][0] == "exec"
    assert "Search the web with your own tools" in observed[0][1]
    assert researcher.transport_mode == "auto"
    observed.clear()
    researcher.transport_mode = "exec"
    assert researcher._ask_with_pages(["query"], "research prompt") == "answer from native web search"
    assert observed[0][0] == "exec"
    assert researcher.transport_mode == "exec"


def test_auto_restores_mode_when_native_web_exec_fails(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path)
    _install_failed_host_reader(monkeypatch, researcher)
    researcher.transport_mode = "auto"

    def fail(_prompt):
        assert researcher.transport_mode == "exec"
        raise RuntimeError("native web CLI failed")

    monkeypatch.setattr(researcher, "ask", fail)
    with pytest.raises(RuntimeError, match="native web CLI failed"):
        researcher._ask_with_pages(["query"], "research prompt")
    assert researcher.transport_mode == "auto"


def test_persistent_mode_rejects_native_web_fallback_before_inference(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path)
    _install_failed_host_reader(monkeypatch, researcher)
    researcher.transport_mode = "persistent"
    calls = []
    monkeypatch.setattr(researcher, "ask", lambda prompt: calls.append(prompt))
    with pytest.raises(NoHarness, match="Persistent Codex transport has web tools disabled"):
        researcher._ask_with_pages(["query"], "research prompt")
    assert calls == []
    assert researcher.transport_mode == "persistent"


def test_profiles_reuse_only_matching_accounts_without_importing_user_config(monkeypatch, tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    (original / "auth.json").write_text('{"account":"first"}', encoding="utf-8")
    (original / "config.toml").write_text('[mcp_servers.private]\ncommand="private-tool"', encoding="utf-8")
    executable = tmp_path / "fake-codex.exe"
    executable.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(original))
    monkeypatch.setenv("UNRELATED_SECRET", "must not be inherited")
    try:
        first = codex_profile.profile(str(executable), model="chosen", namespace="installation")
        repeat = codex_profile.profile(str(executable), model="chosen", namespace="installation")
        assert first.home_dir == repeat.home_dir
        from pathlib import Path
        config = Path(first.home_dir) / "config.toml"
        assert "private-tool" not in config.read_text(encoding="utf-8")
        assert "UNRELATED_SECRET" not in first.env
        (original / "auth.json").write_text('{"account":"different"}', encoding="utf-8")
        different = codex_profile.profile(str(executable), model="chosen", namespace="installation")
        assert different.home_dir != first.home_dir
        assert (original / "config.toml").read_text(encoding="utf-8").endswith('command="private-tool"')
    finally:
        codex_profile.shutdown()

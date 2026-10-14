"""Every agent on the desktop roster takes the persistent path it has, or says it has none."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agentledger import Ledger
from app.providers import harness, resident
from app.providers.codex_transport import TransportUnavailable
from app.providers.resident import ResidentResult


def _researcher(monkeypatch, tmp_path, agent: str, **kwargs):
    executable = tmp_path / agent
    executable.write_text("fixture", encoding="utf-8")
    chosen = replace(harness.row_for(agent) if hasattr(harness, "row_for") else _known(agent),
                     executable=str(executable))
    monkeypatch.setattr(harness, "locate", lambda _: str(executable))
    return harness.HarnessResearcher(chosen, app_state_path=tmp_path / "app.sqlite", **kwargs)


def _known(agent: str):
    return next(h for h in harness.KNOWN if h.id == agent)


def _install(monkeypatch, result: ResidentResult, seen: list | None = None):
    def run(profile, request, **kwargs):
        if seen is not None:
            seen.append((profile, request))
        request.on_delivery("unknown", "ctx", "")
        request.on_delivery("accepted", "ctx", "turn")
        return result

    monkeypatch.setattr(resident, "transport", lambda: SimpleNamespace(run=run))


def _profile(monkeypatch, researcher, wire: str):
    monkeypatch.setattr(researcher, "_resident_profile", lambda: resident.ResidentProfile(
        wire, ("agent",), "work", {}))


def _attempts(tmp_path):
    ledger = Ledger(tmp_path / "app.sqlite")
    conn = ledger.connect()
    try:
        ids = [r[0] for r in conn.execute("SELECT run_id FROM agent_runs").fetchall()]
    finally:
        conn.close()
    return ledger, ids


# ── the roster ───────────────────────────────────────────────────────────────


def test_the_desktop_roster_is_covered_by_a_persistent_protocol_or_an_honest_gap():
    roster = {h.id: h.protocol for h in harness.KNOWN}
    covered = {"codex"} | {i for i, p in roster.items() if p in harness.RESIDENT_PROTOCOLS}
    assert covered == {"codex", "claude-code", "mistral-vibe"}
    # The one agent with no persistent protocol is named, so a new row cannot be
    # added without deciding which of the two it is.
    assert set(roster) - covered == {"antigravity-cli"}


def test_an_agent_with_only_a_print_mode_uses_a_process_in_auto_and_refuses_in_persistent(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "antigravity-cli")
    said: list[str] = []
    monkeypatch.setattr(researcher, "_invoke", lambda prompt, on_line: "from a process")
    researcher.transport_mode = "auto"
    assert researcher._run("research", said.append) == "from a process"
    assert any("no persistent protocol" in line for line in said)
    researcher.transport_mode = "persistent"
    with pytest.raises(TransportUnavailable, match="no persistent protocol"):
        researcher._run("research")


def test_exec_mode_never_touches_a_resident_worker(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "claude-code")
    researcher.transport_mode = "exec"
    monkeypatch.setattr(resident, "transport", lambda: (_ for _ in ()).throw(AssertionError("pool used")))
    monkeypatch.setattr(researcher, "_invoke", lambda prompt, on_line: "from a process")
    assert researcher._run("research") == "from a process"


def test_a_run_the_reader_can_answer_keeps_its_own_process_in_every_mode(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "claude-code")
    monkeypatch.setattr(researcher, "_can_converse", lambda: True)
    monkeypatch.setattr(resident, "transport", lambda: (_ for _ in ()).throw(AssertionError("pool used")))
    monkeypatch.setattr(researcher, "_invoke", lambda prompt, on_line: "answerable")
    for mode in ("auto", "persistent"):
        researcher.transport_mode = mode
        assert researcher._run("research") == "answerable"


# ── Claude Code ──────────────────────────────────────────────────────────────


def test_claude_reads_cost_usage_and_text_from_the_agents_own_result(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "claude-code", model="opus", effort="low")
    _profile(monkeypatch, researcher, "claude")
    envelope = {"type": "result", "is_error": False, "result": '{"risks":[]}',
                "usage": {"input_tokens": 10, "output_tokens": 2, "cache_read_input_tokens": 5},
                "total_cost_usd": 0.02}
    _install(monkeypatch, ResidentResult('{"risks":[]}', "sess", "turn", envelope["usage"], envelope))
    assert researcher._run("Research it") == '{"risks":[]}'
    assert researcher.tokens_used == 17
    assert researcher.cost_usd == 0.02
    assert researcher.runtime["context_id"] == "sess"
    ledger, ids = _attempts(tmp_path)
    assert ledger.lookup(ids[0])["state"] == "succeeded"
    assert ledger.attempts(ids[0])[0]["delivery"] == "accepted"


def test_claude_an_error_the_agent_reported_fails_the_run_as_it_does_from_a_process(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "claude-code")
    _profile(monkeypatch, researcher, "claude")
    envelope = {"type": "result", "is_error": True, "subtype": "error_max_turns",
                "result": "ran out of turns", "usage": {"input_tokens": 3}}
    _install(monkeypatch, ResidentResult("ran out of turns", "s", "t", {}, envelope))
    with pytest.raises(RuntimeError):
        researcher._run("Research it")
    ledger, ids = _attempts(tmp_path)
    assert ledger.lookup(ids[0])["state"] == "failed"
    assert researcher.tokens_used == 3  # spent, so metered even though it failed


def test_claude_streamed_lines_become_log_lines_and_a_hidden_draft(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "claude-code")
    _profile(monkeypatch, researcher, "claude")
    said, drafts = [], []
    researcher.on_text = drafts.append
    envelope = {"type": "result", "is_error": False, "result": "done", "usage": {}}

    def run(profile, request, **kwargs):
        request.on_line(json.dumps({"type": "system", "subtype": "init", "model": "opus"}))
        request.on_line(json.dumps({"type": "stream_event", "event": {
            "type": "content_block_delta", "delta": {"type": "text_delta", "text": '{"risks":['}}}))
        return ResidentResult("done", "s", "t", {}, envelope)

    monkeypatch.setattr(resident, "transport", lambda: SimpleNamespace(run=run))
    researcher._run("Research it", said.append)
    assert any(line.startswith("started opus") for line in said)
    assert not any('"risks"' in draft for draft in drafts)


def test_claude_profile_is_the_process_vector_plus_stream_input_in_an_owned_folder(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "claude-code", model="opus", effort="low")
    exe = tmp_path / "claude-code"
    monkeypatch.setattr(harness, "declared", lambda _exe: frozenset({
        "--input-format", "--no-session-persistence", "--model", "--effort", "--allowedTools",
        "--output-format", "--verbose", "--max-budget-usd", "--max-turns"}))
    monkeypatch.setattr(harness, "command_for", lambda one, **kw: [
        str(exe), "-p", "--output-format", "stream-json", "--verbose", "--allowedTools", "WebSearch,WebFetch"])
    monkeypatch.setenv("UNRELATED_SECRET", "kept out? no: the process adapter inherits it too")
    try:
        profile = researcher._resident_profile()
        assert profile.wire == "claude"
        assert profile.argv[-3:] == ("--input-format", "stream-json", "--no-session-persistence")
        assert Path(profile.cwd).is_dir() and Path(profile.cwd) != Path.cwd()
        assert not any(Path(profile.cwd).iterdir())  # an empty folder: nothing to read
        assert profile.env["PWD"] == profile.cwd
        again = researcher._resident_profile()
        assert again.identity() == profile.identity()  # an identical profile finds its worker
    finally:
        resident.shutdown()


def test_claude_without_stream_input_is_unavailable_not_broken(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "claude-code")
    monkeypatch.setattr(harness, "declared", lambda _exe: frozenset({"--output-format"}))
    with pytest.raises(TransportUnavailable, match="stream-json input"):
        researcher._resident_profile()
    monkeypatch.setattr(researcher, "_resident_profile", lambda: (_ for _ in ()).throw(
        TransportUnavailable("old CLI")))
    monkeypatch.setattr(researcher, "_invoke", lambda prompt, on_line: "from a process")
    assert researcher._run("research") == "from a process"


# ── Mistral Vibe ─────────────────────────────────────────────────────────────


def test_vibe_profile_runs_the_acp_server_beside_vibe_with_its_own_home(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "mistral-vibe", model="devstral")
    acp = tmp_path / "vibe-acp"
    acp.write_text("fixture", encoding="utf-8")
    acp.chmod(0o755)
    monkeypatch.setenv("MISTRAL_API_KEY", "sk-test")
    try:
        profile = researcher._resident_profile()
        assert profile.wire == "acp" and profile.argv == (str(acp),)
        home = Path(profile.env["VIBE_HOME"])
        config = (home / "config.toml").read_text(encoding="utf-8")
        assert "mcp_servers = []" in config and "enabled = false" in config  # no session log per request
        assert 'active_model = "devstral"' in config
        assert profile.env["MISTRAL_API_KEY"] == "sk-test" and profile.env["VIBE_ACTIVE_MODEL"] == "devstral"
        assert Path(profile.cwd).is_dir() and str(home).startswith(str(Path(profile.cwd).parent))
        assert researcher.model == "devstral"
    finally:
        resident.shutdown()


def test_vibe_without_the_acp_server_is_unavailable(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "mistral-vibe")
    monkeypatch.setattr(harness.shutil, "which", lambda *args, **kwargs: None)
    with pytest.raises(TransportUnavailable, match="vibe-acp"):
        researcher._resident_profile()


def test_vibe_counts_the_tokens_the_session_reports(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "mistral-vibe")
    _profile(monkeypatch, researcher, "acp")
    _install(monkeypatch, ResidentResult("answer", "sess", "7", {"inputTokens": 7, "outputTokens": 3}, {}))
    assert researcher._run("Research it") == "answer"
    assert researcher.tokens_used == 10
    ledger, ids = _attempts(tmp_path)
    assert ledger.lookup(ids[0])["state"] == "succeeded"


def test_vibe_in_persistent_mode_refuses_a_native_web_fallback_before_inference(monkeypatch, tmp_path):
    researcher = _researcher(monkeypatch, tmp_path, "mistral-vibe")
    reader = SimpleNamespace(
        page_titles={}, sources={}, search_provider="openserp", telemetry={"stages": []},
        search_coverage={"search_errors": ["offline"], "queries_searched": 0, "pages_read": 0})
    monkeypatch.setattr(researcher, "_read_web_pages", lambda *a, **k: (reader, [], None))
    monkeypatch.setattr(researcher, "_echo", lambda *a, **k: None)
    calls: list[str] = []
    monkeypatch.setattr(researcher, "ask", lambda prompt: calls.append(prompt))
    researcher.transport_mode = "persistent"
    with pytest.raises(harness.NoHarness, match="Persistent Mistral transport has web tools disabled"):
        researcher._ask_with_pages(["query"], "research prompt")
    assert calls == []
    # auto asks for a process instead, then puts the mode back
    researcher.transport_mode = "auto"
    seen: list[str] = []
    monkeypatch.setattr(researcher, "ask", lambda prompt: seen.append(researcher.transport_mode) or "native")
    assert researcher._ask_with_pages(["query"], "research prompt") == "native"
    assert seen == ["exec"] and researcher.transport_mode == "auto"


# ── the setting ──────────────────────────────────────────────────────────────


def _saved(tmp_path, values):
    from app import prefs
    from app.web import state

    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    try:
        prefs.write(conn, values)
    finally:
        conn.close()
    return path


@pytest.mark.parametrize("agent", ["claude-code", "mistral-vibe", "antigravity-cli", "codex"])
def test_one_setting_governs_every_agent_and_the_old_name_still_reads(monkeypatch, tmp_path, agent):
    from app import prefs
    from app.providers import harness_researcher

    monkeypatch.delenv("KRIKO_AGENT_TRANSPORT", raising=False)
    monkeypatch.delenv("KRIKO_CODEX_TRANSPORT", raising=False)
    found = _known(agent)
    monkeypatch.setattr("app.providers.resolve_agent", lambda *a, **k: (found, ""))
    monkeypatch.setattr("app.providers._is_api_agent", lambda _: False)
    monkeypatch.setattr(harness.HarnessResearcher, "settle_effort", lambda *a, **k: ("", ""), raising=False)
    monkeypatch.setattr(harness, "settle_effort", lambda one, model, effort: (model, effort))
    old = _saved(tmp_path, {prefs.CODEX_TRANSPORT: "persistent"})
    assert harness_researcher(preferred=agent, app_state_path=old).transport_mode == "persistent"
    new = _saved(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path,
                 {prefs.AGENT_TRANSPORT: "exec", prefs.CODEX_TRANSPORT: "persistent"})
    assert harness_researcher(preferred=agent, app_state_path=new).transport_mode == "exec"
    monkeypatch.setenv("KRIKO_CODEX_TRANSPORT", "persistent")  # the environment wins, under either name
    assert harness_researcher(preferred=agent, app_state_path=new).transport_mode == "persistent"
    monkeypatch.setenv("KRIKO_AGENT_TRANSPORT", "exec")
    assert harness_researcher(preferred=agent, app_state_path=new).transport_mode == "exec"

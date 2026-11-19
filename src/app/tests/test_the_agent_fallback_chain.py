"""The ordered agent chain: which failures move a run on, what order it tries
agents in, when a failing agent is left alone, and the run that moves."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import prefs
from app.providers import agent_chain, apiagent, harness, resolve_agent
from app.providers import fallback
from app.providers.fallback import (
    AUTH, LIMIT, NETWORK, START, TIMEOUT, Breakers, ChainResearcher, classify,
)
from app.web import state


def _agent(ident: str):
    return next(one for one in harness.KNOWN if one.id == ident)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(fallback, "BREAKERS", Breakers(clock=fake))
    return fake


@pytest.fixture
def machine(monkeypatch):
    here = SimpleNamespace(clis=[], keyed=[])
    monkeypatch.setattr(harness, "available", lambda: list(here.clis))
    monkeypatch.setattr(apiagent, "available", lambda *args, **kwargs: list(here.keyed))
    return here


def _store_order(path: Path, order: str, pick: str = "") -> Path:
    conn = state.connect(path)
    values = {prefs.AGENT_ORDER: order}
    if pick:
        values[prefs.HARNESS] = pick
    prefs.write(conn, values)
    conn.close()
    return path


@pytest.mark.parametrize("message, failure", [
    ("Claude usage limit reached, resets 3pm", LIMIT),
    ("Claude Code exited 1: not logged in", AUTH),
    ("Claude Code did not finish within 600s", TIMEOUT),
    ("NoHarness: Codex is not installed", START),
    ("Mistral API error: HTTP 503 Service Unavailable", NETWORK),
    ("the harness answered without a findings list", ""),
    ("Claude Code exited 1: unexpected token in the envelope", ""),
])
def test_only_the_failures_another_agent_can_answer_move_the_run(message, failure):
    assert classify(RuntimeError(message)) == failure


def test_a_timeout_or_dropped_connection_is_a_failure_to_move_on_from():
    assert classify(TimeoutError("read timed out")) == TIMEOUT
    assert classify(ConnectionResetError("reset by peer")) == NETWORK


def test_a_cancel_or_the_runs_own_budget_never_changes_agent():
    class Cancelled(Exception):
        pass

    class BudgetExceeded(RuntimeError):
        pass

    assert classify(Cancelled("usage limit")) == ""
    assert classify(BudgetExceeded("budget exhausted")) == ""


def test_the_pick_leads_then_the_stored_order_then_the_rest(machine, tmp_path):
    machine.clis = [_agent("claude-code"), _agent("codex"), _agent("opencode")]
    path = _store_order(tmp_path / "app.sqlite", "opencode,codex")
    chain = agent_chain("codex", app_state_path=path)
    assert [one.id for one in chain] == ["codex", "opencode", "claude-code"]


def test_the_stored_order_drives_selection_when_no_agent_is_picked(machine, tmp_path):
    machine.clis = [_agent("claude-code"), _agent("codex")]
    path = _store_order(tmp_path / "app.sqlite", "codex,claude-code")
    assert resolve_agent("", app_state_path=path) == (_agent("codex"), "")


def test_the_stored_order_is_the_fallback_after_a_failed_pick(machine, clock, tmp_path):
    machine.clis = [_agent("claude-code"), _agent("codex"), _agent("opencode")]
    path = _store_order(tmp_path / "app.sqlite", "opencode,codex")
    fallback.BREAKERS.record_failure("claude-code", LIMIT, "usage limit reached")
    assert [one.id for one in agent_chain("claude-code", app_state_path=path)] == [
        "opencode", "codex"]


def test_an_api_agent_runs_only_when_the_reader_listed_it(machine, tmp_path):
    machine.clis = [_agent("codex")]
    machine.keyed = [apiagent.MISTRAL]
    assert [one.id for one in agent_chain("", app_state_path=None)] == ["codex"]
    path = _store_order(tmp_path / "app.sqlite", "mistral-api,codex")
    assert agent_chain("", app_state_path=path)[0] is apiagent.MISTRAL


def test_a_listed_agent_that_is_not_installed_is_skipped(machine, tmp_path):
    machine.clis = [_agent("codex")]
    path = _store_order(tmp_path / "app.sqlite", "hermes,codex")
    assert [one.id for one in agent_chain("", app_state_path=path)] == ["codex"]


def test_a_cooling_agent_is_skipped_until_its_cooldown_ends(machine, clock, tmp_path):
    machine.clis = [_agent("codex"), _agent("claude-code")]
    path = _store_order(tmp_path / "app.sqlite", "codex,claude-code")
    fallback.BREAKERS.record_failure("codex", LIMIT, "usage limit reached")
    assert [one.id for one in agent_chain("", app_state_path=path)] == ["claude-code"]
    clock.advance(601)
    assert [one.id for one in agent_chain("", app_state_path=path)] == [
        "codex", "claude-code"]


def test_three_quick_failures_open_a_breaker_and_the_probe_doubles_it(clock):
    breakers = Breakers(clock=clock)
    for _ in range(2):
        breakers.record_failure("codex", START, "not on PATH")
    assert breakers.available("codex")
    breakers.record_failure("codex", START, "not on PATH")
    assert not breakers.available("codex")
    assert breakers.status("codex")["state"] == "cooling"
    clock.advance(59)
    assert not breakers.available("codex")
    clock.advance(2)
    assert breakers.available("codex")
    breakers.record_failure("codex", START, "not on PATH")
    assert not breakers.available("codex")
    clock.advance(119)
    assert not breakers.available("codex")
    clock.advance(2)
    assert breakers.available("codex")


def test_failures_outside_the_window_do_not_add_up(clock):
    breakers = Breakers(clock=clock)
    breakers.record_failure("codex", TIMEOUT)
    breakers.record_failure("codex", TIMEOUT)
    clock.advance(301)
    breakers.record_failure("codex", TIMEOUT)
    assert breakers.available("codex")


def test_a_quota_wall_cools_down_at_once_and_the_cooldown_is_capped(clock):
    breakers = Breakers(clock=clock)
    breakers.record_failure("claude-code", LIMIT, "usage limit reached")
    assert not breakers.available("claude-code")
    clock.advance(601)
    breakers.record_failure("claude-code", LIMIT, "usage limit reached")
    clock.advance(1199)
    assert not breakers.available("claude-code")
    clock.advance(2)
    assert breakers.available("claude-code")
    for _ in range(4):
        breakers.record_failure("claude-code", LIMIT, "usage limit reached")
        clock.advance(fallback.MAX_COOLDOWN_SECONDS)
        assert breakers.available("claude-code")


def test_a_sign_in_failure_is_reported_as_signed_out(clock):
    breakers = Breakers(clock=clock)
    breakers.record_failure("codex", AUTH, "not logged in")
    assert breakers.status("codex")["state"] == "signed_out"
    clock.advance(601)
    assert breakers.status("codex")["state"] == "ready"


def test_a_success_forgets_the_failures_before_it(clock):
    breakers = Breakers(clock=clock)
    for _ in range(3):
        breakers.record_failure("codex", START)
    clock.advance(61)
    breakers.record_success("codex")
    breakers.record_failure("codex", START)
    breakers.record_failure("codex", START)
    assert breakers.available("codex")


class FakeResearcher:
    def __init__(self, name, outcome=None):
        self.name = name
        self.outcome = outcome
        self.calls = 0

    def ask(self, prompt):
        self.calls += 1
        if self.outcome is not None:
            raise self.outcome
        return f"{self.name}: {prompt}"


def _chain(*pairs):
    agents = [SimpleNamespace(id=ident, label=ident.title()) for ident, _ in pairs]
    fakes = {ident: FakeResearcher(ident, outcome) for ident, outcome in pairs}
    return agents, fakes


def test_a_quota_wall_moves_the_same_step_to_the_next_agent(clock):
    agents, fakes = _chain(("claude", RuntimeError("usage limit reached")), ("codex", None))
    lines = []
    research = ChainResearcher(agents, lambda agent: fakes[agent.id],
                               breakers=Breakers(clock=clock), on_switch=lines.append)
    assert research.ask("brief") == "codex: brief"
    assert fakes["claude"].calls == 1 and fakes["codex"].calls == 1
    assert research.answered_by is agents[1]
    assert lines == [research.switches[0]]
    assert lines[0].startswith("Switched to Codex: its account hit a usage or billing limit.")


def test_a_step_that_returned_is_not_run_again(clock):
    agents, fakes = _chain(("claude", None), ("codex", None))
    research = ChainResearcher(agents, lambda agent: fakes[agent.id],
                               breakers=Breakers(clock=clock))
    research.ask("first")
    fakes["claude"].outcome = RuntimeError("usage limit reached")
    assert research.ask("second") == "codex: second"
    assert fakes["claude"].calls == 2 and fakes["codex"].calls == 1


def test_an_error_another_agent_would_repeat_is_raised_unchanged(clock):
    error = ValueError("the answer had no findings list")
    agents, fakes = _chain(("claude", error), ("codex", None))
    lines = []
    research = ChainResearcher(agents, lambda agent: fakes[agent.id],
                               breakers=Breakers(clock=clock), on_switch=lines.append)
    with pytest.raises(ValueError) as raised:
        research.ask("brief")
    assert raised.value is error
    assert fakes["codex"].calls == 0 and lines == []


def test_the_last_agent_that_fails_raises_its_own_error(clock):
    error = RuntimeError("usage limit reached")
    agents, fakes = _chain(("claude", error))
    research = ChainResearcher(agents, lambda agent: fakes[agent.id],
                               breakers=Breakers(clock=clock))
    with pytest.raises(RuntimeError) as raised:
        research.ask("brief")
    assert raised.value is error


def test_an_agent_cooling_down_is_passed_over(clock):
    agents, fakes = _chain(("claude", RuntimeError("usage limit reached")),
                           ("codex", None), ("opencode", None))
    breakers = Breakers(clock=clock)
    breakers.record_failure("codex", LIMIT, "usage limit reached")
    research = ChainResearcher(agents, lambda agent: fakes[agent.id], breakers=breakers)
    assert research.ask("brief") == "opencode: brief"
    assert fakes["codex"].calls == 0


def test_settings_made_on_the_chain_follow_the_agent_that_answers(clock):
    agents, fakes = _chain(("claude", RuntimeError("usage limit reached")), ("codex", None))
    research = ChainResearcher(agents, lambda agent: fakes[agent.id],
                               breakers=Breakers(clock=clock))
    handler = object()
    research.on_action = handler
    research.ask("brief")
    assert fakes["codex"].on_action is handler


# ── the run itself: two real CLIs, the first walled mid-run ──────────────────

PAGE = (
    "Owners report that the timing chain kit on this engine is unobtainable in "
    "some markets. Several have waited months for the part."
)
QUOTE = "the timing chain kit on this engine is unobtainable in some markets"


def _cli(tmp_path: Path, name: str, *, stdout: str = "", stderr: str = "",
         exit_code: int = 0) -> harness.Harness:
    out, err = tmp_path / f"{name}.out", tmp_path / f"{name}.err"
    out.write_text(stdout, encoding="utf-8")
    err.write_text(stderr, encoding="utf-8")
    script = tmp_path / f"{name}.py"
    script.write_text(
        "import pathlib, sys\n"
        f"sys.stdout.write(pathlib.Path({str(out)!r}).read_text(encoding='utf-8'))\n"
        f"sys.stderr.write(pathlib.Path({str(err)!r}).read_text(encoding='utf-8'))\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    return harness.Harness(name, f"Fake {name}", sys.executable, (str(script), "-p"),
                           structured=True)


def _answer(findings: list[dict]) -> str:
    return json.dumps({
        "type": "result",
        "result": "Here is what I found.\n\n```json\n"
        + json.dumps({"findings": findings}) + "\n```",
        "usage": {"input_tokens": 1200, "output_tokens": 340},
        "total_cost_usd": 0.0,
    })


class _Progress:
    job_id = "job-1"

    def __init__(self):
        self.lines: list[str] = []

    def set(self, fraction, message=""):
        if message:
            self.lines.append(message)

    def log(self, message):
        self.lines.append(message)

    def check(self):
        pass

    def replies(self):
        return []

    def partial(self, result):
        pass

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def test_a_run_whose_agent_hits_a_quota_wall_finishes_on_the_next(
    tmp_path, monkeypatch, clock
):
    from app.providers.harness import HarnessResearcher
    from app.web import tasks
    from app.web.settings import Settings
    from kriko.store.db import connect

    conn = connect(tmp_path / "k.sqlite")
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')")
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES ('s1', 'probe', 'product', 'Thing s1')")
    conn.commit()
    conn.close()
    settings = Settings(store_path=tmp_path / "k.sqlite",
                        app_state_path=tmp_path / "app.sqlite",
                        analysis_log_path=tmp_path / "a.jsonl")

    walled = _cli(tmp_path, "walled", stderr="Usage limit reached for this plan.",
                  exit_code=1)
    answering = _cli(tmp_path, "answering", stdout=_answer([{
        "title": "Timing chain kit unobtainable",
        "domain": "engine", "severity": "high", "quote": QUOTE,
        "document_text": PAGE, "source_url": "https://forum.example/thread/1",
        "component": "timing chain kit",
    }]))
    monkeypatch.setattr(harness, "available", lambda: [walled, answering])
    monkeypatch.setattr(apiagent, "available", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "app.providers.harness_researcher",
        lambda **kwargs: HarnessResearcher(kwargs["agent"], timeout=60),
    )

    progress = _Progress()
    result = tasks.research(settings, {"subject_id": "s1", "backend": "harness"}, progress)

    assert result["outcome"] == "1 claim(s) kept", progress.text
    assert "Switched to Fake answering: its account hit a usage or billing limit." in progress.text
    assert fallback.BREAKERS.status(walled.id)["state"] == "cooling"

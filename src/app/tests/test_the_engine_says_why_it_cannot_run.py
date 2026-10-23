"""What the engine says when it cannot run, and when a turn refused.

Two lines a reader meets at the worst moment.

A refused API-agent turn used to end its job log with a summary shaped exactly
like a completed answer — *"answered in 3 s: 0 retrieval request(s), 0 billable,
0 result(s), 0 cached, $0.00"* — so a refusal arrived as an answer that came
back empty. The last word about a failed turn is the failure.

And the startup roster (`GET /api/agent-availability`) echoed the reader's
stored `preferred_harness` while omitting it from the list of agents that can
run, with nothing said. The reason already existed inside `keys.require`; it
just never travelled.
"""

from __future__ import annotations

import pytest

from app import prefs, sharekeys
from app.web import state
from app.web.settings import Settings


def test_a_refused_api_agent_turn_does_not_end_its_log_like_an_answer():
    """The last thing said about a failed turn names the failure."""
    from app.providers import apiagent, mistral

    refusal = mistral.Reply()
    refusal.error = "Mercury is unreachable"
    researcher = apiagent.ApiAgentResearcher(
        apiagent.MISTRAL, converse=lambda prompt, **kw: refusal)
    lines: list[str] = []
    researcher.on_action = lines.append

    with pytest.raises(RuntimeError, match="Mercury is unreachable"):
        researcher.ask("Research the Widget", allow_tools=False)

    assert lines, "the run said nothing at all"
    assert "Mercury is unreachable" in lines[-1]
    assert "answered in" not in lines[-1]
    assert "did not answer" in lines[-1]


def test_the_roster_carries_why_the_stored_pick_is_missing(tmp_path, monkeypatch):
    """A stored pick that cannot run arrives with the engine's own reason.

    The reader's case: `preferred_harness` is `kriko-agent` and no key is saved
    anywhere. The sentence is the resolver's own, so a key never saved and a
    trial that was spent stay different answers, and an agent that *is* in the
    roster carries no note at all.
    """
    from app import keys
    from app.providers import apiagent, harness
    from app.web.routers.prefs import agent_availability

    # The machine's own keys and grants are not this test's subject.
    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")
    monkeypatch.setattr(sharekeys, "home", lambda: tmp_path)
    monkeypatch.setenv("KRIKO_SHARE_PEPPER", "a-build-pepper-for-tests")
    monkeypatch.delenv("MERCURY_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    settings = Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
    )

    def choose(pick: str) -> None:
        conn = state.connect(settings.app_state_path)
        try:
            prefs.write(conn, {prefs.HARNESS: pick})
        finally:
            conn.close()

    def availability() -> dict:
        conn = state.connect(settings.app_state_path)
        try:
            return agent_availability(conn)
        finally:
            conn.close()

    choose(apiagent.KRIKO_AGENT.id)
    body = availability()
    assert body["chosen"][prefs.HARNESS] == apiagent.KRIKO_AGENT.id
    assert apiagent.KRIKO_AGENT.id not in {row["id"] for row in body["harnesses"]}
    assert "needs a key" in body["chosen_note"]
    # The way in the reader actually has, not only the one for a developer.
    assert "Shared access" in body["chosen_note"]

    # A trial that was spent is not reported as a key that was never saved.
    monkeypatch.setattr(sharekeys, "TRIAL_FILE", tmp_path / "trial_access.json")
    sharekeys.write_trial(
        sharekeys.make_trial({"mercury": "sk-mercury", "deepseek": "sk-deepseek"},
                             questions=1),
        where=sharekeys.TRIAL_FILE)
    sharekeys.charge(tmp_path)
    assert "trial for this computer is used up" in availability()["chosen_note"]

    # A CLI the reader stored but this machine does not have says how to get it.
    cli = next(one for one in harness.KNOWN if one.install_hint)
    monkeypatch.setattr(harness, "available", lambda: [])
    choose(cli.id)
    assert availability()["chosen_note"] == cli.install_hint

    # An agent that can run needs no note: a client draws nothing the engine
    # did not report.
    monkeypatch.setenv("MERCURY_API_KEY", "sk-own-mercury")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-own-deepseek")
    choose(apiagent.KRIKO_AGENT.id)
    body = availability()
    assert apiagent.KRIKO_AGENT.id in {row["id"] for row in body["harnesses"]}
    assert body["chosen_note"] == ""

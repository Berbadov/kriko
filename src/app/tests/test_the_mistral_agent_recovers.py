"""The two Mistral agents recover instead of failing a reader's turn.

Both failures were reported together: runs ended with `TurnRejected: [WinError
5] Access is denied` and then `TurnOutOfTime`, and the API agent sometimes
answered with no web search at all.

* **The hosted tool-less session is the fragile half of the CLI plane.** On
  Windows `vibe-acp` has answered `session/new` with access denied, and the
  turn died there. In `auto` mode a fresh process must answer instead.
* **Mistral's built-in `web_search` connector is not supported everywhere.**
  When it does not run, the reply carries no queries and no sources even though
  it answered; Kriko's own Exa/Tavily/DeepSeek search must answer instead.
"""

import sys
from dataclasses import replace

import pytest

from app.providers import apiagent, mistral
from app.tests.harness_fixtures import row


def _vibe():
    from app.providers import harness

    # A fake executable keeps the suite's guard from refusing to start the
    # reader's own CLI; the protocol stays `vibe`, which is what is under test.
    return harness.HarnessResearcher(
        replace(row("mistral-vibe"), executable=sys.executable))


@pytest.fixture(autouse=True)
def _fresh_health(monkeypatch):
    from app.providers import harness

    monkeypatch.setattr(harness, "_RESIDENT_UNHEALTHY", {})


def test_a_rejected_hosted_session_is_answered_by_a_fresh_process(monkeypatch):
    from app.providers.codex_transport import TurnRejected

    researcher = _vibe()
    researcher.transport_mode = "auto"

    def rejected(*_args, **_kwargs):
        raise TurnRejected("[WinError 5] Access is denied")

    monkeypatch.setattr(researcher, "_run_resident", rejected)
    handed = []
    monkeypatch.setattr(
        researcher, "_invoke",
        lambda prompt, on_line: handed.append(prompt) or "answered",
    )
    said = []
    researcher.on_action = said.append

    assert researcher.ask("brief", allow_tools=False) == "answered"
    assert handed, "the run did not fall back to a fresh process"
    assert "hosted session was unavailable" in " ".join(said)
    # The process has tools, so it is not told it has none.
    from app.providers import harness

    assert harness.TOOLLESS_FALLBACK_NOTE in handed[0]
    assert harness.TOOLLESS_NOTE not in handed[0]


def test_an_explicit_persistent_choice_still_reports_the_rejection(monkeypatch):
    from app.providers.codex_transport import TurnRejected

    researcher = _vibe()
    researcher.transport_mode = "persistent"

    def rejected(*_args, **_kwargs):
        raise TurnRejected("[WinError 5] Access is denied")

    monkeypatch.setattr(researcher, "_run_resident", rejected)
    monkeypatch.setattr(
        researcher, "_invoke",
        lambda *_args, **_kwargs: pytest.fail(
            "an explicit persistent choice must not be replayed behind the reader's back"),
    )

    with pytest.raises(TurnRejected):
        researcher.ask("brief", allow_tools=False)


def test_a_hosted_session_that_recently_failed_is_skipped(monkeypatch):
    from app.providers import harness

    researcher = _vibe()
    researcher.transport_mode = "auto"
    harness._mark_resident_unhealthy(researcher.harness)
    monkeypatch.setattr(
        researcher, "_run_resident",
        lambda *_args, **_kwargs: pytest.fail(
            "a hosted session that just failed must not be tried again this soon"),
    )
    handed = []
    monkeypatch.setattr(
        researcher, "_invoke",
        lambda prompt, on_line: handed.append(prompt) or "answered",
    )

    assert researcher.ask("brief", allow_tools=False) == "answered"
    assert harness.TOOLLESS_FALLBACK_NOTE in handed[0]


def test_a_successful_hosted_session_clears_the_cooldown(monkeypatch):
    from app.providers import harness

    researcher = _vibe()
    researcher.transport_mode = "auto"
    # An expired entry: the hosted session is tried, answers, and the memory
    # of the earlier failure goes away.
    harness._RESIDENT_UNHEALTHY[researcher.harness.id] = 0.0
    monkeypatch.setattr(researcher, "_run", lambda prompt: "answered")

    assert researcher.ask("brief", allow_tools=False) == "answered"
    assert researcher.harness.id not in harness._RESIDENT_UNHEALTHY


def test_an_answer_with_no_search_falls_back_to_krikos_search(monkeypatch, tmp_path):
    from app import keys

    first = mistral.Reply(
        text="answered from memory", tokens_in=10, tokens_out=5)
    fallback = mistral.Reply(
        text="answered from the web",
        tokens_in=10, tokens_out=5,
        queries=["widget pump failure"],
        sources={"https://forum.example": {"title": "Forum", "text": "it fails"}},
    )
    monkeypatch.setattr(keys, "search_providers", lambda: ["exa"])
    monkeypatch.setattr(keys, "require", lambda _name: "test-key")
    called = {}

    def fake_fallback(prompt, **kwargs):
        called.update(prompt=prompt, **kwargs)
        return fallback

    monkeypatch.setattr(apiagent, "openai_compatible_converse", fake_fallback)
    researcher = apiagent.ApiAgentResearcher(
        apiagent.MISTRAL, home=tmp_path, timeout=10)
    researcher._stream_converse = lambda *_args, **_kwargs: first

    assert researcher.ask("brief") == "answered from the web"
    assert called["base_url"] == mistral.base_url()
    assert called["api_key"] == "test-key"
    assert researcher.searched == ["widget pump failure"]
    assert researcher.sources["https://forum.example"] == "it fails"


def test_without_a_search_key_the_providers_own_error_is_the_answer(monkeypatch, tmp_path):
    from app import keys

    monkeypatch.setattr(keys, "search_providers", lambda: [])
    monkeypatch.setattr(
        apiagent, "openai_compatible_converse",
        lambda *_args, **_kwargs: pytest.fail("nothing can search here"),
    )
    researcher = apiagent.ApiAgentResearcher(
        apiagent.MISTRAL, home=tmp_path, timeout=10)
    researcher._stream_converse = lambda *_args, **_kwargs: mistral.Reply(
        error="api.mistral.ai answered HTTP 400 (the request was refused as malformed)")

    with pytest.raises(RuntimeError, match="HTTP 400"):
        researcher.ask("brief")


def test_search_returned_reads_queries_and_sources():
    assert mistral.search_returned(mistral.Reply(text="x")) is False
    assert mistral.search_returned(mistral.Reply(queries=["q"])) is True
    assert mistral.search_returned(
        mistral.Reply(sources={"https://a.example": {"title": "", "text": "t"}})) is True

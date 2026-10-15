"""An agent is handed the pages Kriko read, whichever agent it is.

Measured on one product (Razer BlackShark V2 X quick look): the agents Kriko
read pages for answered in 15 s (Codex) and 26 s (Vibe); Claude Code, which
searched and opened pages itself turn by turn, took 53 s. And a Vibe
pack-authoring run whose session had no tools tried search, open and `curl`
some fifteen times, each refused, and ended after five minutes with no claim.
"""

from app.providers import harness
from app.tests.harness_fixtures import row

URL = "https://forum.example/widget-charging-port"
QUOTE = "The charging port of my Widget stopped working after two months."
PAGE = f"Widget forum thread. {QUOTE} Others reported the same."


def test_claude_code_is_read_for_like_the_other_agents(monkeypatch):
    searched, read, prompts = [], [], []
    monkeypatch.setattr(
        "app.providers.openserp.searcher",
        lambda *a, **k: (lambda query, limit=5: searched.append(query) or [
            {"url": URL, "title": "Widget charging port", "site": "forum.example"}]))
    monkeypatch.setattr(
        "app.providers.fetch.reader",
        lambda *a, **k: (lambda url: read.append(url) or PAGE))
    researcher = harness.HarnessResearcher(row("claude-code"))
    monkeypatch.setattr(researcher, "_run", lambda prompt: prompts.append(prompt) or "{}")

    researcher.ask_quick("Widget")

    assert "claude-code" in harness.HOST_READ_HARNESSES
    assert searched and read == [URL]
    assert len(prompts) == 1 and f"SOURCE URL: {URL}" in prompts[0]
    assert researcher.sources == {URL: PAGE}


def test_a_session_with_no_tools_is_told_so_before_it_tries_one(monkeypatch):
    prompts = []
    researcher = harness.HarnessResearcher(row("mistral-vibe"))
    monkeypatch.setattr(researcher, "_run", lambda prompt: prompts.append(prompt) or "{}")

    researcher.ask("Write the pack.")

    assert prompts[0].startswith("Write the pack.")
    assert "no tools of any kind" in prompts[0]


def test_a_process_with_tools_is_not_told_it_has_none(monkeypatch):
    prompts = []
    researcher = harness.HarnessResearcher(row("mistral-vibe"))
    researcher.transport_mode = "exec"
    monkeypatch.setattr(researcher, "_run", lambda prompt: prompts.append(prompt) or "{}")

    researcher.ask("Write the pack.")

    assert "no tools of any kind" not in prompts[0]

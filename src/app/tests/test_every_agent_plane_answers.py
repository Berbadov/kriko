"""Every one of the five planes answers one question, by its own path.

The reader's words: *"Claude Code, Antigravity, Codex, Mistral and local LLM
must work without problems"*. A plane works when the app's own Quick Look — the
brief, the host read, the transport, the parser, the grounding — comes back
with a risk whose quote is on a page the reader was shown.

What each CLI's *protocol* does with its stdout is proved separately
(`test_the_fourth_agent_and_its_protocol.py`, `test_codex_integration.py`,
`test_the_harness_research_plane.py`), because that is one plane at a time and
a different question. What is proved here is the part that is shared and that
therefore has to hold for all five at once: the same brief reaches the same
place, and the same answer comes back out of it.

Nothing here needs a network, an account, a key or an installed CLI. A plane
that is not installed on this machine is still described — `harness.KNOWN` is
the roster — and the row is what the transport reads.
"""

import json

import pytest

from app import quicklook
from app.providers import harness, local_agent
from app.tests.harness_fixtures import row

PRODUCT = "Widget"
URL = "https://example.test/widget-report"
QUOTE = "The charging port may stop working after exposure."
PAGE = (
    "Widget owners report that the charging port fails after ordinary use. "
    "The manufacturer says: The charging port may stop working after exposure. "
    "This longer page excerpt exists so the host reader accepts it as a full page."
)

#: The roster as the reader named it. `harness.KNOWN` is a closed engineering
#: vocabulary (see its own comment), so this list is the claim, not data.
FIVE = ("claude-code", "antigravity-cli", "codex", "mistral-vibe")


def _reply() -> str:
    return json.dumps({
        "assumed": "the MK2", "category": "gadget", "pack": "", "pack_identity": {},
        "price": {}, "specs": [],
        "risks": [{"title": "Charging port failure", "why": "It may fail.",
                   "check": "Check the port.", "severity": "medium",
                   "url": URL, "quote": QUOTE}],
    })


@pytest.fixture
def host_read(monkeypatch):
    """The host's search and page read, with no socket and no service.

    And the dial: this file is about the plane that is *handed* the pages, which
    is Kriko's search (`prefs.SEARCH_KRIKO`). The reader's default is the
    agent's own search, where Kriko reads nothing — tested in
    `test_every_agent_is_handed_its_pages.py`.
    """
    from app import prefs

    monkeypatch.setattr(prefs, "DEFAULT_HARNESS_SEARCH", prefs.SEARCH_KRIKO)
    monkeypatch.setattr(
        "app.providers.openserp.searcher",
        lambda _url, **_kwargs: lambda query, limit: [{"url": URL, "title": "Report"}])
    monkeypatch.setattr(
        "app.providers.fetch.reader", lambda **_kwargs: lambda url: PAGE)


@pytest.mark.parametrize("ident", FIVE)
def test_a_coding_agent_plane_answers_a_quick_look_from_the_pages_it_was_handed(
        ident, host_read, monkeypatch):
    researcher = harness.HarnessResearcher(row(ident))
    seen: list[str] = []
    # The one place a CLI's own output becomes a reply. Stands in for the
    # spawn, which the per-protocol tests drive for real.
    monkeypatch.setattr(researcher, "_run", lambda prompt: seen.append(prompt) or _reply())

    reply = researcher.ask_quick(PRODUCT)
    found = quicklook.parse(reply, researcher.sources)

    assert len(seen) == 1, "one question, one answer"
    assert "# Quick look:" in seen[0]
    assert PRODUCT in seen[0]
    assert f"SOURCE URL: {URL}" in seen[0], "the plane must be handed the page it cites"
    assert QUOTE in seen[0]
    assert [one["title"] for one in found["risks"]] == ["Charging port failure"]
    assert found["risks"][0]["sources"][0]["quote"] == QUOTE
    assert researcher.coverage["status"] == "supported_findings"


def test_the_local_plane_answers_the_same_quick_look_from_the_pages_it_read():
    """No CLI, no socket, no search service: this machine's model answers."""
    from app.tests.test_local_quicklook_output import PipelineModel

    model = PipelineModel(findings=[{"title": "Charging port failure",
                                     "why": "It may fail.",
                                     "needle": "the charging port fails"}])
    asker = local_agent.LocalAsker(
        model, model,
        lambda query, limit, **_options: [{"url": URL, "title": "Report"}],
        lambda url, **_options: PAGE,
        model="small", search_provider="stub")

    reply = asker.ask_quick(PRODUCT, page={"facts": {"ld:name": PRODUCT}})
    found = quicklook.parse(reply, asker.sources)

    assert [one["title"] for one in found["risks"]] == ["Charging port failure"]
    assert found["risks"][0]["sources"][0]["url"] == URL
    assert list(asker.sources) == [URL]


def test_the_five_planes_are_one_roster_with_a_launch_vector_each():
    """A plane the picker offers but the transport cannot describe is a plane
    that fails at the reader's first click, not at the screen."""
    ids = [one.id for one in harness.KNOWN]
    assert set(FIVE) <= set(ids), ids
    for ident in FIVE:
        one = row(ident)
        assert one.executable
        assert one.protocol
        assert one.args or one.prompt_flag, f"{ident} has nothing to run"


def test_every_plane_shares_one_brief_and_one_parser():
    """The five must not drift into five protocols: the same question, the same
    reply shape, the same grounding. `HarnessResearcher` inherits `brief()` on
    purpose, and this is that intention as an assertion."""
    from kriko.research.agent import AgentResearcher

    assert harness.HarnessResearcher.name == "harness"
    assert issubclass(harness.HarnessResearcher, AgentResearcher)
    assert local_agent.LocalAsker.name == "local"
    # `ask_quick` is the shared entry point every door calls; a plane that
    # cannot take it is a plane the Quick Look job cannot run.
    for plane in (local_agent.LocalAsker, harness.HarnessResearcher):
        assert callable(getattr(plane, "ask_quick", None))


def test_a_plane_that_is_not_installed_says_so_rather_than_failing_a_run(monkeypatch):
    """The screen's answer and the run's answer must be the same one."""
    from app import providers

    monkeypatch.setattr(harness, "locate", lambda _one: "")

    assert harness.chosen("codex") is None
    with pytest.raises(harness.NoHarness, match="no coding-agent CLI on PATH"):
        providers.harness_researcher(preferred="codex")


def test_the_local_plane_is_not_ready_without_a_model_and_says_why(monkeypatch):
    """The other half of "each agent works": a plane that cannot run names the
    reason instead of returning nothing."""
    from app import localplane
    from app.providers import local_discovery

    local_discovery.forget_discovery()
    monkeypatch.setattr(local_discovery, "discover", lambda *_a, **_k: [
        {"name": "Ollama", "url": "http://127.0.0.1:11434", "up": False, "models": []}])
    monkeypatch.setattr(local_discovery, "search_answers", lambda *_a, **_k: False)

    plan = localplane.resolve(None, url="http://127.0.0.1:11434", with_search=False)

    assert plan["ready"] is False
    assert "Nothing answers" in plan["reason"]

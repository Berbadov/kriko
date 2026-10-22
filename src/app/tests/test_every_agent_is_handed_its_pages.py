"""An agent is handed the pages Kriko read, whichever agent it is.

Measured on one product (Razer BlackShark V2 X quick look): the agents Kriko
read pages for answered in 15 s (Codex) and 26 s (Vibe); Claude Code, which
searched and opened pages itself turn by turn, took 53 s. And a Vibe
pack-authoring run whose session had no tools tried search, open and `curl`
some fifteen times, each refused, and ended after five minutes with no claim.

That measurement is why `kriko` is still here to be chosen — and the reader's
default is the other answer, the agent's own search, because Kriko's is the
experimental one. Both are tested below: the dial has to work in both
directions or the default is just a story about the code.
"""

from app import prefs
from app.providers import harness
from app.tests.harness_fixtures import row

URL = "https://forum.example/widget-charging-port"
QUOTE = "The charging port of my Widget stopped working after two months."
PAGE = f"Widget forum thread. {QUOTE} Others reported the same."


def _edges(monkeypatch, searched, read):
    monkeypatch.setattr(
        "app.providers.openserp.searcher",
        lambda *a, **k: (lambda query, limit=5: searched.append(query) or [
            {"url": URL, "title": "Widget charging port", "site": "forum.example"}]))
    monkeypatch.setattr(
        "app.providers.fetch.reader",
        lambda *a, **k: (lambda url: read.append(url) or PAGE))


def test_claude_code_is_read_for_when_krikos_search_is_chosen(monkeypatch):
    searched, read, prompts = [], [], []
    _edges(monkeypatch, searched, read)
    researcher = harness.HarnessResearcher(row("claude-code"), search=prefs.SEARCH_KRIKO)
    monkeypatch.setattr(researcher, "_run", lambda prompt: prompts.append(prompt) or "{}")

    researcher.ask_quick("Widget")

    assert "claude-code" in harness.HOST_READ_HARNESSES
    assert searched and read == [URL]
    assert len(prompts) == 1 and f"SOURCE URL: {URL}" in prompts[0]
    assert researcher.sources == {URL: PAGE}


def test_the_agents_own_search_is_the_default_and_reads_nothing(monkeypatch):
    """The reader's default: the CLI reaches the web itself, Kriko reads nothing."""
    searched, read, prompts = [], [], []
    _edges(monkeypatch, searched, read)
    researcher = harness.HarnessResearcher(row("claude-code"))
    monkeypatch.setattr(researcher, "_run", lambda prompt: prompts.append(prompt) or "{}")

    researcher.ask_quick("Widget")

    assert researcher.search_source == prefs.DEFAULT_HARNESS_SEARCH == prefs.SEARCH_OWN
    assert searched == [] and read == [], "Kriko did not search or read for it"
    assert researcher.sources is None, "so a quote is not checked against pages it never saw"
    assert "Search the web with your own tools" in prompts[0]


def test_the_host_read_plane_decides_the_kinds_and_says_them(monkeypatch):
    """The reader's words: the source selection is the agent's, and observable."""
    researcher = harness.HarnessResearcher(row("claude-code"), search=prefs.SEARCH_KRIKO)

    queries = researcher._planned_queries("Widget owner reports and recall notices", "en")

    said = list(researcher.actions)
    assert "searching kinds: forums, recalls" in said, said
    assert any(line.startswith("searching kind forums: ") for line in said), said
    # The words an engine is asked carry the kind's own word: a search that does
    # not ask for a thread does not return one.
    forum_line = next(line for line in said if line.startswith("searching kind forums: "))
    assert "forum" in forum_line.casefold()
    assert forum_line.split(": ", 1)[1] in queries


def test_a_bare_product_name_asks_for_no_kind_and_none_is_invented(monkeypatch):
    """Nothing is guessed: no kind in the question, and a query's own kind named."""
    researcher = harness.HarnessResearcher(row("claude-code"), search=prefs.SEARCH_KRIKO)

    queries = researcher._planned_queries("Widget", "en")

    said = list(researcher.actions)
    assert queries and said
    assert not any(line.startswith("searching kinds: ") for line in said), said
    # The default angles stand in, and each is labelled by what its own words
    # name: the first asks for owner reports without saying "forum", so it gets
    # no kind rather than a guessed one.
    assert said[0] == 'searching: "Widget" problems owner reports'
    assert any(line.startswith("searching kind reviews: ") for line in said), said


def test_a_session_with_no_tools_is_told_so_before_it_tries_one(monkeypatch):
    prompts = []
    researcher = harness.HarnessResearcher(row("mistral-vibe"))
    monkeypatch.setattr(researcher, "_run", lambda prompt: prompts.append(prompt) or "{}")

    researcher.ask("Write the pack.", allow_tools=False)

    assert prompts[0].startswith("Write the pack.")
    assert "no tools of any kind" in prompts[0]


def test_a_process_with_tools_is_not_told_it_has_none(monkeypatch):
    prompts = []
    researcher = harness.HarnessResearcher(row("mistral-vibe"))
    researcher.transport_mode = "exec"
    monkeypatch.setattr(researcher, "_run", lambda prompt: prompts.append(prompt) or "{}")

    researcher.ask("Write the pack.")

    assert "no tools of any kind" not in prompts[0]

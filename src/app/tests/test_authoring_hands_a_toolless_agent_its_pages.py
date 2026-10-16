"""A toolless agent that authors a catalog is handed the pages, never a search.

Mistral Vibe (persistent ACP) and Codex (app-server) run with no tools at all:
every permission request is refused. A product check's authoring brief used to
say "research the category first" and went to such a session as a bare prompt,
so the agent tried WebSearch, ToolSearch, curl and bash a dozen times, every one
was refused, and it shipped a catalog with no claims, reported as a success.

Each test here drives the real job runner (the `world` fixture of
`test_category_packs`) with a real `HarnessResearcher` for mistral-vibe. Only
the edges are stubbed: the search service and page reader (`HostPages`) and the
session door, `_run`, which records every prompt the agent is handed.
"""

from types import SimpleNamespace

import pytest

from app import categorypack
from app.tests.harness_fixtures import row
from app.tests.test_category_packs import (
    FORUM,
    MICE,
    PAGES,
    V6_PAGE,
    V8_PAGE,
    V8_QUOTE,
    _check,
    _fenced,
    _risk,
    _script_v6,
    _script_v8,
    _wait,
)
from app.tests.test_category_packs import world as _category_world

# The fixture, re-exported under its own name so this module's tests can ask for it.
world = _category_world

TITLE = "Scyrox V8 Gaming Mouse"
V6_TITLE = "Scyrox V6 Gaming Mouse"
AUTHOR = "# Author a Kriko knowledge pack"
EXTEND = "# Extend an existing Kriko pack"


class HostPages:
    """The search service and page reader, answering one search at a time.

    `state` says what the next search finds: the test pages ("found"), searches
    that ran and found nothing ("empty"), or searches that all failed ("dead").
    Every search is recorded, one list of queries per read.
    """

    def __init__(self, pages):
        self.pages = pages
        self.state = "found"
        self.searches = []

    def __call__(self, queries, **_kwargs):
        queries = list(queries)
        self.searches.append(queries)
        if self.state == "found":
            found = {"queries_searched": len(queries), "search_errors": 0,
                     "unique_hits": len(self.pages), "pages_read": len(self.pages)}
            pages = list(self.pages.items())
        elif self.state == "empty":
            found = {"queries_searched": len(queries), "search_errors": 0,
                     "unique_hits": 0, "pages_read": 0}
            pages = []
        else:
            found = {"queries_searched": 0, "search_errors": len(queries),
                     "unique_hits": 0, "pages_read": 0}
            pages = []
        reader = SimpleNamespace(
            sources={url: text for url, text in pages},
            page_titles={url: url for url, _ in pages},
            search_coverage={**found, "pages_unreadable": 0, "pages_timed_out": 0,
                             "publishers_read": len(pages)},
            telemetry={"stages": []},
            search_provider="openserp",
        )
        return reader, pages, None


def _wire(client, monkeypatch, pages, transport):
    """A real mistral-vibe researcher whose search and session are stubbed.

    `_run` is the one door every prompt leaves through, so the stub records
    what the session was handed at the point it would have been sent. It is set
    on the instance because the suite refuses to start a real coding agent
    (`conftest`), and the `transport_mode` the researcher runs with is real.
    Returns the list of prompts, in order.
    """
    from app import providers
    from app.providers import harness

    handed = []
    researcher = harness.HarnessResearcher(row("mistral-vibe"))
    researcher.transport_mode = transport
    monkeypatch.setattr(researcher, "_read_web_pages", pages)

    def session(prompt, on_line=None):
        handed.append(prompt)
        if prompt.startswith("# Quick look"):
            # A host-read look is the compact brief, which names the product
            # unindented; `Script.reply` matches the full brief's indentation.
            for title, payload in client.script.quick.items():
                if f"\n{title}\n" in prompt:
                    return _fenced(payload)
        return client.script.reply(prompt)

    monkeypatch.setattr(researcher, "_run", session)
    monkeypatch.setattr(providers, "harness_researcher", lambda **_: researcher)
    return handed


def _quick(client, title):
    response = client.post("/api/extension/research-plane", json={
        "q": title, "allow_draft": True})
    assert response.status_code == 200, response.text
    quick = _wait(client, response.json()["job_id"])
    assert quick["state"] == "succeeded", quick["message"]
    return quick


def _add_to_pack(client, quick):
    added = client.post(f"/api/extension/quick-looks/{quick['job_id']}/pack")
    assert added.status_code == 200, added.text
    return _wait(client, added.json()["job_id"])


# ── the reproduction: the agent is handed what Kriko read ─────────────────


@pytest.mark.parametrize("transport", ["persistent", "auto"])
def test_a_toolless_agent_authoring_a_catalog_is_handed_the_pages_kriko_read(
        world, monkeypatch, transport):
    _script_v8(world.script)
    pages = HostPages({V8_PAGE: PAGES[V8_PAGE], FORUM: PAGES[FORUM]})
    handed = _wire(world, monkeypatch, pages, transport)

    quick, deepen = _check(world, TITLE)

    assert quick["state"] == "succeeded", quick["message"]
    assert deepen["state"] == "succeeded", deepen["message"]
    [authoring] = [one for one in handed if one.startswith(AUTHOR)]
    # Kriko searched for the product itself, once for the look and once for the pack.
    assert len(pages.searches) == 2
    assert all(query.startswith(f'"{TITLE}"') for query in pages.searches[-1])
    assert f"SOURCE URL: {V8_PAGE}" in authoring
    assert f"SOURCE URL: {FORUM}" in authoring
    assert V8_QUOTE in authoring
    # And the brief says the search is over, so the agent does not start one.
    assert "## Research already done" in authoring
    assert "Do not try to search or open pages yourself" in authoring


def test_a_toolless_amend_is_handed_the_pages_for_the_product_it_adds(world, monkeypatch):
    _script_v8(world.script)
    _check(world, TITLE)                       # the catalog exists, authored once
    _script_v6(world.script)
    pages = HostPages({V6_PAGE: PAGES[V6_PAGE]})
    handed = _wire(world, monkeypatch, pages, "persistent")

    _, deepen = _check(world, V6_TITLE)

    assert deepen["state"] == "succeeded", deepen["message"]
    [extension] = [one for one in handed if one.startswith(EXTEND)]
    assert f"SOURCE URL: {V6_PAGE}" in extension
    assert "## Research already done" in extension


# ── the safety net: no pages, no agent sent to browse ─────────────────────


@pytest.mark.parametrize(("state", "transport", "reason"), [
    ("empty", "persistent", "found no results"),
    ("empty", "auto", "found no results"),
    ("dead", "persistent", "web tools disabled"),
])
def test_a_toolless_agent_is_not_sent_to_browse_when_no_page_could_be_read(
        world, monkeypatch, state, transport, reason):
    _script_v8(world.script)
    pages = HostPages({V8_PAGE: PAGES[V8_PAGE], FORUM: PAGES[FORUM]})
    handed = _wire(world, monkeypatch, pages, transport)
    look = _quick(world, TITLE)                # pages are there for the look
    pages.state = state

    deepen = _add_to_pack(world, look)

    assert deepen["state"] == "failed"
    assert reason in deepen["message"]
    assert not [one for one in handed if one.startswith(AUTHOR)]


def test_an_agent_outside_host_read_is_asked_the_authoring_brief_as_before(monkeypatch):
    from app.providers import harness

    researcher = harness.HarnessResearcher(row("claude-code"))
    monkeypatch.setattr(harness, "HOST_READ_HARNESSES", harness.HOST_READ_HARNESSES - {"claude-code"})

    def no_reader(*_args, **_kwargs):
        raise AssertionError("Claude searches for itself; Kriko reads no pages for it")

    prompts = []
    monkeypatch.setattr(researcher, "_read_web_pages", no_reader)
    monkeypatch.setattr(researcher, "_run", lambda prompt, *_a, **_k: prompts.append(prompt) or "{}")

    researcher.ask_author(f"{AUTHOR} for {TITLE}", product=TITLE)

    assert len(prompts) == 1
    assert prompts[0].startswith(f"{AUTHOR} for {TITLE}")
    assert "Research already done" not in prompts[0]


def test_a_dead_search_in_auto_mode_lets_the_cli_search_and_says_no_page_was_read(monkeypatch):
    """Auto mode may switch a toolless CLI to its process, which has web tools.

    That run must be told it searches, not that it has no tools: the note about
    pages already read is only true when Kriko read some.
    """
    from app.providers import harness
    from app.tests.test_harness_quicklook import _dead_search

    _dead_search(monkeypatch, [])
    researcher = harness.HarnessResearcher(row("mistral-vibe"))
    researcher.transport_mode = "auto"
    seen = []

    def session(prompt, *_args, **_kwargs):
        seen.append((researcher.transport_mode, prompt))
        return "{}"

    monkeypatch.setattr(researcher, "_run", session)

    researcher.ask_author(f"{AUTHOR} for {TITLE}", product=TITLE)

    [(mode, prompt)] = seen
    assert mode == "exec"
    assert "No pages were read for you" in prompt
    assert "Research already done" not in prompt


# ── a catalog authored with no claims is said so, and is not a success ────


def test_a_product_check_that_files_no_claim_says_so_in_its_log_and_result(world):
    _script_v8(world.script)
    world.script.quick[TITLE]["risks"] = []
    world.script.author[TITLE] = dict(MICE, claims=[])

    _, deepen = _check(world, TITLE)

    assert deepen["state"] == "succeeded", deepen["message"]
    assert deepen["result"]["no_claims"] == (
        "the agent proposed no claims and the quick look found no risk to file")
    assert "no claims: the agent proposed no claims" in deepen["log"]


def test_a_product_check_that_files_claims_reports_no_gap(world):
    _script_v8(world.script)

    _, deepen = _check(world, TITLE)

    assert deepen["state"] == "succeeded", deepen["message"]
    assert deepen["result"]["no_claims"] == ""
    assert "no claims:" not in deepen["log"]


def test_a_claim_left_out_for_its_quote_is_the_reason_the_check_has_no_claim(world):
    _script_v8(world.script)
    world.script.quick[TITLE]["risks"] = [
        _risk("Scroll wheel wears", V8_PAGE, "a quote the page does not contain")]
    world.script.author[TITLE] = dict(MICE, claims=[])

    _, deepen = _check(world, TITLE)

    assert deepen["state"] == "succeeded", deepen["message"]
    assert deepen["result"]["no_claims"].startswith("1 claim(s) left out")
    assert "the quote is not on the page" in deepen["result"]["no_claims"]


# ── harvest: a look whose check filed nothing is unfilled, not filed ──────


def test_a_look_whose_check_filed_no_claim_is_named_as_needing_an_agent(world):
    _script_v8(world.script)
    _check(world, TITLE)                       # the catalog, with its first claims
    _script_v6(world.script)
    world.script.quick[V6_TITLE]["risks"] = [
        _risk("Side buttons rattle", V6_PAGE, "a quote that is not on its page")]
    _, deepen = _check(world, V6_TITLE)
    assert deepen["result"]["no_claims"].startswith("1 claim(s) left out")

    done = _wait(world, world.post("/api/packs/harvest").json()["job_id"])

    assert done["state"] == "succeeded", done["message"]
    assert [one["product"] for one in done["result"]["needs_agent"]] == [V6_TITLE]


def test_attach_counts_the_claims_a_subject_already_holds(world):
    _script_v8(world.script)
    _check(world, TITLE)

    attached = categorypack.attach(world.settings.store_path, "gaming-mice", TITLE, [])

    assert attached["claims_added"] == 0
    assert attached["subject_claims"] >= 1


def test_attach_counts_no_claims_for_a_subject_nobody_holds(world):
    _script_v8(world.script)
    _check(world, TITLE)

    attached = categorypack.attach(
        world.settings.store_path, "gaming-mice", "Logitech G Pro X Superlight", [])

    assert attached["subject_claims"] == 0

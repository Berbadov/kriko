"""A host-read CLI gets its pages from the reader's own search when one leads.

Codex and Mistral Vibe are handed pages Kriko reads itself (their persistent
sessions have no web tools). That path used OpenSERP only: the reader's
configured DeepSeek/Exa chain, which chat and the local plane already use, was
never asked. In the field that meant the host search step took 19 seconds and
`api.deepseek.com timed out` filled the log, while a working hosted key sat
unused.

`localplane.hosted_search` is the one gate for "a hosted provider leads here",
so tests keep their fence: it is patched off everywhere, and this file patches
it on.
"""

from app import localplane
from app.providers import harness
from app.tests.harness_fixtures import row

URLS = ["https://example.test/widget-one", "https://example.test/widget-two"]


def _page(url: str) -> str:
    return ("Widget owners report the charging port fails after ordinary use. "
            "The manufacturer says exposure may stop the port working. "
            f"This longer excerpt for {url} keeps the host reader satisfied "
            "that the page is a full page and about the product.")


class FakeChain:
    providers = ["deepseek", "exa"]

    def __init__(self) -> None:
        self.queries: list[str] = []

    def __call__(self, query, limit=5, timeout=None, **_options):
        self.queries.append(query)
        return [{"title": f"page {index}", "site": "example.test", "url": url}
                for index, url in enumerate(URLS)]


def _reader(monkeypatch):
    monkeypatch.setattr("app.providers.fetch.reader", lambda **_kwargs: _page)


def _no_openserp(*_args, **_kwargs):
    raise AssertionError("OpenSERP was asked although the reader's chain leads")


def _researcher(tmp_path):
    return harness.HarnessResearcher(row("codex"),
                                     app_state_path=str(tmp_path / "app.sqlite"))


def test_a_host_read_turn_searches_through_the_readers_chain(tmp_path, monkeypatch):
    chain = FakeChain()
    monkeypatch.setattr(localplane, "hosted_search", lambda path=None: True)
    monkeypatch.setattr("app.providers.websearch.build", lambda *a, **k: chain)
    monkeypatch.setattr("app.providers.openserp.searcher", _no_openserp)
    _reader(monkeypatch)
    researcher = _researcher(tmp_path)

    reader, pages, _identity = researcher._read_web_pages(["widget failures"],
                                                          product="Widget")

    assert chain.queries, "the reader's chain was never asked"
    assert pages, "no page was read through the reader's chain"
    assert researcher.search_provider == "deepseek,exa"


def test_without_a_hosted_leader_opensrp_still_searches(tmp_path, monkeypatch):
    called = []

    def searcher(*_args, **_kwargs):
        def search(query, limit=5, **_options):
            called.append(query)
            return [{"title": "page", "site": "example.test", "url": URLS[0]}]
        return search

    monkeypatch.setattr(localplane, "hosted_search", lambda path=None: False)
    monkeypatch.setattr("app.providers.openserp.searcher", searcher)
    _reader(monkeypatch)
    researcher = _researcher(tmp_path)

    _reader_obj, pages, _identity = researcher._read_web_pages(
        ["widget failures"], product="Widget")

    assert called, "OpenSERP was never asked"
    assert pages
    assert researcher.search_provider == "openserp"


def test_a_chain_that_cannot_be_built_falls_back_instead_of_failing(tmp_path, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("MissingKey: DEEPSEEK_API_KEY")

    def searcher(*_args, **_kwargs):
        def search(query, limit=5, **_options):
            return [{"title": "page", "site": "example.test", "url": URLS[0]}]
        return search

    monkeypatch.setattr(localplane, "hosted_search", lambda path=None: True)
    monkeypatch.setattr("app.providers.websearch.build", broken)
    monkeypatch.setattr("app.providers.openserp.searcher", searcher)
    _reader(monkeypatch)
    researcher = _researcher(tmp_path)

    _reader_obj, pages, _identity = researcher._read_web_pages(
        ["widget failures"], product="Widget")

    assert pages
    assert researcher.search_provider == "openserp"
    assert "web search is unavailable" in " ".join(researcher.actions)

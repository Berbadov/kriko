"""The fixed web a task runs against.

Replaces the two sockets every Kriko plane reaches the web through: the search
service (`openserp.searcher`) and the page reader (`fetch.reader`). Both are
looked up on their module at call time, so swapping the attribute is the whole
seam; no plane is edited and none knows.

It answers the way the real ones do and no better. Every query returns every
page, in the file's order, as a noisy engine would; the plane's own relevance
and publisher checks decide what is read. It records what was asked and what
was opened, which is how a task can tell what an agent *did* with the settings
it was given, from outside the agent.
"""

from contextlib import contextmanager
from urllib.parse import urlparse


class FakeWeb:
    def __init__(self, pages: list[dict], language: str = "en"):
        self.pages = {page["url"]: page for page in pages}
        #: The search language the run was set to; a hosted provider answers in it.
        self.language = language
        #: (query, language) for every search, in order.
        self.searches: list[tuple[str, str]] = []
        #: Every page open, in order, repeats kept: a page opened twice cost
        #: two fetches, and the count is a measurement.
        self.opened: list[str] = []

    @property
    def queries(self) -> list[str]:
        return [query for query, _language in self.searches]

    @property
    def languages(self) -> set[str]:
        return {language for _query, language in self.searches}

    def _searcher(self, base_url: str = "", engine: str = "", *, language: str = "en"):
        def search(query: str, limit: int = 5) -> list[dict]:
            self.searches.append((str(query), str(language)))
            return [
                {"url": url, "title": page.get("title", ""),
                 "site": (urlparse(url).hostname or "")}
                for url, page in self.pages.items()
            ][: max(1, int(limit))]
        return search

    def _reader(self, timeout: float = 0.0):
        from app.providers import fetch

        def read(url: str):
            self.opened.append(url)
            page = self.pages.get(url)
            return fetch.Fetched(page["text"] if page else "")
        return read

    def _hosted(self, provider: str, app_state_path, *, trial_reservation_id: str = ""):
        return lambda: self._searcher(language=self.language)

    @contextmanager
    def installed(self):
        """The fixed web in place of the real one, put back afterwards.

        Every search provider the chain can build is the fake, hosted ones
        included: a DeepSeek key in the shell must not turn a trial into a
        live search.
        """
        from app.providers import fetch, openserp, websearch

        before = (openserp.searcher, fetch.reader, websearch._hosted_factory)
        openserp.searcher, fetch.reader = self._searcher, self._reader
        websearch._hosted_factory = self._hosted
        try:
            yield self
        finally:
            openserp.searcher, fetch.reader, websearch._hosted_factory = before

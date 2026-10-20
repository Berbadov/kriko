"""Federate named search APIs; count every request and preserve global source IDs."""

import asyncio

from app.searchbench.retrieval import Retrieval, canonical


class FederatedRetrieval:
    def __init__(self, wire, *, count=3, page_chars=3000):
        self.backends = [Retrieval(wire, v, count=count, page_chars=page_chars)
                         for v in ("deepseek-content", "exa-lite", "tavily-fast")]
        self.sources, self.owners = {}, {}
        self.count = count
        self.failures = []

    @property
    def first_result_s(self):
        times = [b.first_result_s for b in self.backends if b.first_result_s is not None]
        return min(times) if times else None

    @property
    def cache_hits(self):
        return sum(b.cache_hits for b in self.backends)

    def remember(self, source, owner):
        url = canonical(source["url"])
        saved = self.sources.setdefault(url, {**source, "id": f"S{len(self.sources) + 1}"})
        if source.get("has_page_content") and not saved.get("has_page_content") or source.get("fetched"):
            saved.update({key: value for key, value in source.items() if key != "id"})
        self.owners.setdefault(url, [])
        if owner not in self.owners[url]:
            self.owners[url].append(owner)
        return dict(saved)

    async def search(self, query):
        results = await asyncio.gather(*(b.search(query) for b in self.backends), return_exceptions=True)
        lists = []
        for backend, result in zip(self.backends, results):
            if isinstance(result, BaseException):
                self.failures.append({"provider": backend.provider, "error": type(result).__name__})
                lists.append([])
            else:
                lists.append(result)
        selected, seen = [], set()
        for rank in range(max((len(items) for items in lists), default=0)):
            for backend, items in zip(self.backends, lists):
                if rank >= len(items):
                    continue
                url = canonical(items[rank]["url"])
                if url not in seen and len(selected) >= 2 * self.count:
                    continue
                source = self.remember(items[rank], backend)
                if source["url"] not in seen:
                    seen.add(source["url"])
                    selected.append(source)
        # All retained IDs have been given to the model, so the audit never sees
        # evidence that was withheld from that model.
        # A duplicate at a later rank can add richer content. Return the final
        # merged record so the researcher and later auditor see identical text.
        return [dict(self.sources[source["url"]]) for source in selected]

    async def fetch(self, url):
        url = canonical(url)
        if url not in self.owners:
            raise ValueError("Fetch requires a URL returned by search")
        error = None
        for backend in self.owners[url]:
            try:
                return self.remember(await backend.fetch(url), backend)
            except Exception as failure:
                error = failure
        raise ValueError("No provider could read this source") from error

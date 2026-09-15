"""Search, through Tavily.

The second search provider, and the reason there is a *choice* at all: which
engine reads the web for a research run changes what the model ever sees, and
that is upstream of every other knob in `app/protocols.py`. A plane wired to
one provider is a plane whose results nobody can compare.

The shape returned is `ApiResearcher`'s — `{"url", "title", "site"}` — not
Tavily's. The engine must not learn a vendor's response schema; that is the
whole reason the callable is injected, and it is why adding a provider is this
file plus one row in `keys.PROVIDERS` rather than a change anywhere else.
"""

from urllib.parse import urlsplit

from app.keys import require
from app.providers._http import post_json

#: Overridable through `TAVILY_BASE_URL`, like Exa's, for anyone proxying it.
DEFAULT_BASE_URL = "https://api.tavily.com"


def searcher(api_key: str = "", base_url: str = ""):
    """`search(query, limit) -> [{"url", "title", "site"}]`."""
    key = api_key or require("tavily")
    endpoint = (base_url or _base_url()).rstrip("/") + "/search"

    def search(query: str, limit: int = 5) -> list[dict]:
        payload = {
            "api_key": key,
            "query": query,
            "max_results": max(1, int(limit)),
            # `basic` rather than `advanced`: the reader's page text is fetched
            # separately by `app/providers/fetch.py`, so paying Tavily to
            # summarise or re-read pages would be paying twice for the half
            # that then gets thrown away.
            "search_depth": "basic",
            "include_answer": False,
        }
        body = post_json(endpoint, payload, {"content-type": "application/json"})
        results = body.get("results")
        if not isinstance(results, list):
            return []
        out = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            out.append(
                {
                    "url": url,
                    "title": str(item.get("title") or "").strip(),
                    "site": urlsplit(url).netloc,
                }
            )
        return out

    return search


def _base_url() -> str:
    import os

    return os.environ.get("TAVILY_BASE_URL") or DEFAULT_BASE_URL

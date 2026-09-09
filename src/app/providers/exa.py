"""Search, through Exa.

Exa first because the pack pipeline already speaks it — `packs/cars/pipeline/
ledger/acquire.py` has used `EXA_API_KEY` since before the pivot, so a reader
who has ever run the pipeline already has the key this reads.

The shape returned is `ApiResearcher`'s, not Exa's: `{"url", "title", "site"}`.
The engine must not learn a vendor's response schema — that is the whole reason
the callable is injected — so the translation happens here and nowhere else.
"""

from urllib.parse import urlsplit

from app.keys import require
from app.providers._http import post_json

#: Overridable through `EXA_BASE_URL` for anyone proxying it, the same way
#: the LLM adapter takes a base URL: a fork should not have to patch source to
#: point at its own gateway.
DEFAULT_BASE_URL = "https://api.exa.ai"


def searcher(api_key: str = "", base_url: str = ""):
    """`search(query, limit) -> [{"url", "title", "site"}]`.

    The key is read once, when the plane is built, rather than per request:
    a run that starts must not stop halfway because a settings write happened
    to land between two queries.
    """
    key = api_key or require("exa")
    endpoint = (base_url or _base_url()).rstrip("/") + "/search"

    def search(query: str, limit: int = 5) -> list[dict]:
        payload = {
            "query": query,
            "numResults": max(1, int(limit)),
            # Exa's own judgement of whether to run this as a neural or a
            # keyword search. A research query is a sentence more often than a
            # phrase, and picking wrong costs a whole query's worth of budget.
            "type": "auto",
        }
        body = post_json(endpoint, payload, {"x-api-key": key})
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

    return os.environ.get("EXA_BASE_URL") or DEFAULT_BASE_URL

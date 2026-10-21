"""Search, through DeepSeek's search tool.

The product search benchmark (`app/searchbench`) already drives this service
and settled its wire shape: `POST /v1/tools/search` with a bearer key and
`{"query", "count", "need_content"}`, answered with `results: [{url, title,
snippet | content}]`. This is the same request, made for the app rather than for
a benchmark, and the benchmark is deliberately not imported: production code
does not depend on a harness (CLAUDE.md, layering).

The shape returned is `{"url", "title", "site"}` plus a `snippet` when there is
one: the same hit every other adapter returns, so the engine never learns whose
schema it was.

Two things differ from Exa and Tavily and both are on purpose.

* **A failure is raised, not swallowed.** Exa's adapter returns `[]` for a
  vendor that is down, which a lone provider can afford. This one is a
  *fallback* (`websearch.py`), and a fallback that cannot tell "the service
  refused my key" from "nothing found" cannot say why it did not help.
  `SearchFailed` carries the reason `post_json_or_why` already words without
  quoting the request, so the key never reaches a log through it.
* **Paced.** The service allows a handful of searches a second for the whole
  account; the benchmark paces at 0.23 s and so does this, through the shared
  limiter, so a chat turn and a research run cannot together exceed it.
"""

import os
from urllib.parse import urlsplit

from app.agentresources import pace
from app.keys import require
from app.providers._http import SearchFailed, post_json_or_why

DEFAULT_BASE_URL = "https://api.deepseek.com"

#: The service refuses a longer query outright (the benchmark raises on it).
#: A longer one is cut at a word, not refused: a chat turn's query is a
#: sentence the reader never counted.
MAX_QUERY_CHARS = 128

#: Seconds between two searches. Taken from the benchmark's measured quota.
PACE_SECONDS = 0.23

MAX_COUNT = 10


def clipped(query: str) -> str:
    """`query` cut to the service's limit at a word boundary."""
    text = " ".join(str(query or "").split())
    if len(text) <= MAX_QUERY_CHARS:
        return text
    cut = text[:MAX_QUERY_CHARS]
    head, space, _ = cut.rpartition(" ")
    return (head if space and len(head) >= MAX_QUERY_CHARS // 2 else cut).strip()


def searcher(api_key: str = "", base_url: str = ""):
    """`search(query, limit) -> [{"url", "title", "site"}]`; raises `SearchFailed`.

    The key is read once, when the searcher is built, so a settings write that
    lands between two queries cannot change a run halfway.
    """
    key = api_key or require("deepseek")
    endpoint = (base_url or _base_url()).rstrip("/") + "/v1/tools/search"

    def search(query: str, limit: int = 5, **_ignored) -> list[dict]:
        text = clipped(query)
        if not text:
            return []
        check = getattr(search, "check_cancelled", None)
        if check is not None:
            check()
        pace("deepseek:search", PACE_SECONDS, check)
        count = max(1, min(int(limit), MAX_COUNT))
        body, why = post_json_or_why(
            endpoint, {"query": text, "count": count, "need_content": False},
            {"Authorization": f"Bearer {key}"})
        if check is not None:
            check()
        if why:
            raise SearchFailed(why)
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            return []
        out: list[dict] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url.lower().startswith(("http://", "https://")):
                continue
            hit = {"url": url, "title": str(item.get("title") or "").strip(),
                   "site": urlsplit(url).netloc}
            snippet = item.get("snippet") or item.get("summary") or ""
            if snippet:
                hit["snippet"] = str(snippet)[:1000]
            out.append(hit)
            if len(out) >= count:
                break
        return out

    search.check_cancelled = None  # type: ignore[attr-defined]
    return search


def _base_url() -> str:
    return os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL

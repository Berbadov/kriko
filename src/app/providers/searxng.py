"""SearXNG as a local search target, beside OpenSERP.

SearXNG aggregates engines on the machine that runs it and answers one merged
page of results, so this adapter asks once per query. It speaks the same
`search(query, limit)` shape as `openserp.searcher`, which is what the engine
and the local pipeline expect, so it can stand in without those learning a
second vocabulary.

It is not the default and it is not bundled: SearXNG is a Python service, not
a binary, so a reader who wants it runs it (Docker or a checkout) and points
`search_base_url` at it. Its JSON format has to be enabled in `settings.yml`:

    search:
      formats:
        - html
        - json

    searxng.searcher("http://127.0.0.1:8888")
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

DEFAULT_BASE_URL = "http://127.0.0.1:8888"
TIMEOUT = 12.0
USER_AGENT = "kriko-local-search/0.1"


class LocalSearchError(Exception):
    """A search that could not produce results, with the reason in the text."""


def _read(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as error:
        raise LocalSearchError(f"SearXNG did not answer: {error}") from error


def searcher(base_url: str = "", *, language: str = "en", timeout: float = TIMEOUT,
             safe: int = 0, transport: Callable[[str, float], bytes] | None = None):
    """`search(query, limit) -> [{"url", "title", "site"}]`.

    `transport` exists for tests: the default reads HTTP, a test hands in a
    function that returns the bytes a SearXNG instance would have sent.
    """
    endpoint = (base_url or DEFAULT_BASE_URL).rstrip("/")
    read = transport or _read
    default_timeout = timeout
    stats = {"queries": 0, "hits": 0}

    def search(query: str, limit: int = 5, *, timeout: float | None = None,
               **_unused) -> list[dict]:
        params = urllib.parse.urlencode({
            "q": query, "format": "json", "language": language,
            "safesearch": str(safe), "pageno": "1"})
        url = f"{endpoint}/search?{params}"
        budget = timeout if timeout is not None else default_timeout
        deadline = time.monotonic() + budget
        stats["queries"] += 1
        try:
            body = read(url, max(0.001, deadline - time.monotonic()))
            payload = json.loads(body.decode("utf-8"))
        except LocalSearchError:
            raise
        except (OSError, urllib.error.URLError) as error:
            raise LocalSearchError(f"SearXNG did not answer: {error}") from error
        except (ValueError, UnicodeDecodeError) as error:
            raise LocalSearchError(
                "SearXNG answered without JSON; enable `search.formats: [html, json]` "
                f"in its settings.yml ({error})") from error
        if not isinstance(payload, dict):
            raise LocalSearchError("SearXNG answered with something that is not a result page")
        hits = []
        for row in payload.get("results") or []:
            if not isinstance(row, dict) or not row.get("url"):
                continue
            hits.append({"url": str(row["url"]), "title": str(row.get("title") or ""),
                         "site": str(row.get("engine") or ""),
                         "snippet": str(row.get("content") or "")})
            if len(hits) >= max(1, limit):
                break
        stats["hits"] += len(hits)
        return hits

    search.stats = stats  # type: ignore[attr-defined]
    search.supports_timeout = True  # type: ignore[attr-defined]
    #: What this searcher waits on its own, as the ceiling a chain above it uses.
    search.default_timeout = float(default_timeout)  # type: ignore[attr-defined]
    return search

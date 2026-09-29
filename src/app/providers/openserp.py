"""Search through a self-hosted SERP service.

OpenSERP is the reference target: a single native binary serving
`/mega/search` and per-engine endpoints on localhost, no container, no key.
The wire shape is deliberately thin — one GET, JSON out — so any local SERP
that can answer `?text=` with `results: [{url, title, snippet}]` works
unchanged, including a SearXNG instance with its JSON format enabled.

What this adapter adds over pointing the paid plane's Exa socket at a
localhost URL is the failure contract: a SERP that answers with a challenge
page is *not* a result set, and `LocalSearchError` is what tells the plane's
politeness scheduler to mark the source hot and rotate — the fail-fast rule
the reader set: never wait on a challenge, move to the next engine.

Politeness lives in the scheduler, not here. This adapter does one query at
a time and reports what it saw; pacing, rotation and cooldown are the
scheduler's to enforce, in one place.
"""

import json
import urllib.parse
import urllib.request

from app.providers._http import TIMEOUT
from kriko.research.politeness import LocalSearchError

DEFAULT_BASE_URL = "http://127.0.0.1:7000"
DEFAULT_ENGINE = "duckduckgo"

#: Same markers the politeness module reads, checked here because the SERP
#: itself is the first thing a challenge hits — a block page that reaches
#: the plane as a "result set" would be a block page the scheduler never
#: hears about.
_BLOCK_MARKERS = (
    "captcha", "challenge", "unusual traffic", "are you a robot",
    "access denied", "blocked", "attention required",
)


def searcher(base_url: str = "", engine: str = ""):
    """`search(query, limit) -> [{"url", "title", "site"}]`.

    Same injected shape as the paid plane's search sockets, so the local
    plane is wired exactly like the paid one and the engine never learns
    which kind of searcher it was handed.
    """
    endpoint = (base_url or DEFAULT_BASE_URL).rstrip("/")
    chosen = engine or DEFAULT_ENGINE
    stats = {"queries": 0, "hits": 0, "challenges": 0}

    def search(query: str, limit: int = 5) -> list[dict]:
        params = urllib.parse.urlencode({
            "text": query, "engines": chosen,
            "limit": max(1, int(limit)), "format": "json",
        })
        request = urllib.request.Request(
            f"{endpoint}/mega/search?{params}",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request,
                                        timeout=TIMEOUT) as response:
                body = response.read().decode("utf-8", "replace")
        except Exception as error:  # noqa: BLE001 — network, rotate
            raise LocalSearchError(str(error)) from error
        stats["queries"] += 1
        head = body[:4096].casefold()
        if any(marker in head for marker in _BLOCK_MARKERS):
            stats["challenges"] += 1
            raise LocalSearchError("the SERP answered with a challenge page")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise LocalSearchError("the SERP did not answer with JSON") \
                from error
        results = payload.get("results") if isinstance(payload, dict) else []
        out = []
        for hit in results or []:
            if not isinstance(hit, dict):
                continue
            url = str(hit.get("url", "")).strip()
            if not url:
                continue
            site = str(hit.get("domain", "")).strip()
            if not site:
                netloc = urllib.parse.urlsplit(url).netloc
                site = netloc.split("@")[-1].split(":")[0]
            out.append({
                "url": url,
                "title": str(hit.get("title", "")).strip(),
                "site": site,
            })
        stats["hits"] += len(out)
        return out

    search.stats = stats
    return search

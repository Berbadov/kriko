"""wikipedia.py — scrape Wikipedia engine/transmission articles for fitment data.

Targets pages like "Renault K9K engine" or "Volkswagen EA211 engine" which contain
structured tables mapping application (car model + year) to engine variant.

Usage (called by extract_fitment.py):
    from knowledge.fitment.sources.wikipedia import fetch_engine_article
    text = fetch_engine_article("K9K engine Renault")
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "KrikoBot/1.0 (automotive reliability research; +https://github.com/kriko)"
}
_TIMEOUT = 15


def fetch_engine_article(search_query: str) -> str | None:
    """Search Wikipedia and return the plain-text content of the best matching article.

    Uses the Wikipedia API (free, no key needed). Returns raw wikitext or None on failure.
    """
    try:
        # Step 1: search for the article title
        search_resp = httpx.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": search_query,
                "srlimit": 3,
                "format": "json",
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        search_resp.raise_for_status()
        results = search_resp.json().get("query", {}).get("search", [])
        if not results:
            log.warning("Wikipedia: no results for %r", search_query)
            return None

        title = results[0]["title"]
        log.info("Wikipedia: using article %r for query %r", title, search_query)

        # Step 2: fetch article plain text via extracts API
        content_resp = httpx.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "extracts",
                "titles": title,
                "explaintext": True,
                "exsectionformat": "plain",
                "format": "json",
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        content_resp.raise_for_status()
        pages = content_resp.json().get("query", {}).get("pages", {})
        page = next(iter(pages.values()))
        text = page.get("extract", "") or ""
        if not text:
            log.warning("Wikipedia: empty extract for %r", title)
            return None
        return text

    except Exception as exc:
        log.warning("Wikipedia fetch failed for %r: %s", search_query, exc)
        return None

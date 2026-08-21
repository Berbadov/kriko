"""Ledger acquisition: discover → rank → fetch → ingest for a part. No LLM.

This is the ledger-plane replacement for auto.py's curated-YAML discovery
flow (spec §2.2). Differences from the legacy path, all deliberate:

- **Ranked before fetching** (backlog B8): the legacy pipeline extracted the
  first N sources in Exa discovery order; here every result is scored by
  part-code specificity in the title, failure-signal in the title, and source
  class (blocked domains excluded, forums allowed but ranked below editorial
  — the ledger's aggregation is what makes forum anecdotes safe, spec §2.2).
- **Full text**: no doc.text[:6000]/[:8000] cap anywhere — chunking +
  the deterministic chunk gate handle volume downstream.
- **Lands in `documents`** with the part as `target_hint` (a HINT, never
  attribution — entity resolution decides that from the evidence's own text).

CLI (via run.py):  python -m ops.ledger_run acquire --part dw5 \
                       --part-type transmission --max-sources 15
"""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlparse

from knowledge.ledger.ingest import ingest_document
from knowledge.parts.search_templates import (
    _part_meta, _search_code, templates_for_part,
)
from knowledge.sources.base import Document
from knowledge.sources.curated import _fetch_html
from knowledge.sources.youtube import get_transcript
from knowledge.stoplists import (
    FORUM_DOMAINS,
    is_blocked_source_domain,
    is_german_text,
    mentions_foreign_manufacturer_code,
)

log = logging.getLogger(__name__)

# Small closed vocabulary for ranking only (allowed constant per CLAUDE.md):
# a title saying "problems/arıza/recall" is more likely to describe chronics
# than a title saying "review" or "price". Substring stems (TR agglutinates).
_TITLE_FAILURE_STEMS = (
    "problem", "arıza", "ariza", "sorun", "kronik", "fail", "fault", "recall",
    "issue", "broken", "repair", "worn", "wear", "leak", "defect", "chronic",
)

# Marketplace/classified noise — same role as auto.py's _EXCLUDE_DOMAINS, kept
# minimal: blocked-source domains come from stoplists (the ledger blocklist),
# forums are allowed here (see module docstring).
_EXCLUDE_DOMAINS = (
    "pinterest.com", "ebay.com", "ebay.co.uk", "ebay.de", "ebay.fr",
    "sahibinden.com", "arabam.com", "otomoto.pl", "mobile.de",
    "autotrader.co.uk", "gumtree.com",
)


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _part_tokens(part_id: str) -> list[str]:
    """Discriminative tokens for ranking: the bare code plus the part stub's
    known_also_as aliases (catalog-derived, never hand-enumerated here)."""
    meta = _part_meta(part_id)
    tokens = {_search_code(part_id)}
    tokens.update(str(a) for a in meta.get("known_also_as") or [])
    # Longest-first so word-boundary matching prefers specific aliases
    return sorted(tokens, key=len, reverse=True)


def rank_sources(results: list[dict], part_id: str) -> list[dict]:
    """Score and order discovered sources (best first). Stable for ties.

    result dicts: {"url", "title", "site_or_channel", "type": "page"|"youtube"}.
    Scoring (deterministic, no LLM):
      +2 per part-code/alias token in the title (the strongest chronic signal)
      +1 if the title carries failure vocabulary
      -1 for forum domains (allowed — aggregation makes them safe — but ranked
         below editorial/specialist sources)
    """
    token_res = [(t, re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE))
                 for t in _part_tokens(part_id)]

    def score(r: dict) -> float:
        title = r.get("title") or ""
        s = 0.0
        for _, tre in token_res:
            if tre.search(title):
                s += 2.0
        lowered = title.lower()
        if any(stem in lowered for stem in _TITLE_FAILURE_STEMS):
            s += 1.0
        if _host(r.get("url", "")) in FORUM_DOMAINS:
            s -= 1.0
        return s

    return sorted(results, key=score, reverse=True)


def _search_web(part_id: str, part_type: str, fuel: str, max_per_query: int,
                exa=None, known_urls: set[str] | None = None) -> list[dict]:
    """Exa discovery over the part's search templates. `exa` injectable."""
    if exa is None:
        from exa_py import Exa
        exa = Exa(api_key=os.environ.get("EXA_API_KEY"))
    known = known_urls if known_urls is not None else set()
    found: list[dict] = []
    for _, query in templates_for_part(part_id, part_type, {"fuel": fuel}):
        try:
            resp = exa.search(query, num_results=max_per_query, type="auto",
                              exclude_domains=list(_EXCLUDE_DOMAINS))
        except Exception as exc:
            log.warning("Exa search failed for %r: %s", query, exc)
            continue
        for r in resp.results:
            url = r.url
            if url in known or is_blocked_source_domain(url):
                continue
            known.add(url)
            found.append({"url": url, "type": "page",
                          "site_or_channel": _host(url),
                          "title": (getattr(r, "title", "") or query)[:120]})
    return found


def _search_youtube(part_id: str, part_type: str, fuel: str, max_per_query: int,
                    known_ids: set[str] | None = None) -> list[dict]:
    """yt-dlp ytsearch discovery (no API key)."""
    import yt_dlp

    known = known_ids if known_ids is not None else set()
    found: list[dict] = []
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
            "playlist_items": f"1-{max_per_query}"}
    for _, query in templates_for_part(part_id, part_type, {"fuel": fuel}):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{max_per_query}:{query}",
                                        download=False)
                videos = [v for v in (info.get("entries") or []) if v and v.get("id")]
        except Exception as exc:
            log.warning("yt-dlp search failed for %r: %s", query, exc)
            continue
        for v in videos:
            if v["id"] in known:
                continue
            known.add(v["id"])
            found.append({"url": f"https://www.youtube.com/watch?v={v['id']}",
                          "type": "youtube", "video_id": v["id"],
                          "site_or_channel": (v.get("channel") or v.get("uploader")
                                              or "YouTube")[:60],
                          "title": (v.get("title") or "")[:120]})
    return found


def _fetch_page_text(url: str) -> str | None:
    """Full article text (no truncation — chunking handles volume)."""
    import trafilatura

    html = _fetch_html(url)
    if not html:
        return None
    return trafilatura.extract(html, include_comments=False, include_tables=False)


def _known_targets(conn, part_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT url FROM documents WHERE target_hint=?", (part_id,)).fetchall()
    return {r["url"] for r in rows}


def acquire_part(conn, part_id: str, part_type: str, *, fuel: str = "",
                 max_sources: int = 15, max_per_query: int = 5,
                 youtube: bool = True, exa=None,
                 page_fetcher=None, transcript_fetcher=None) -> dict:
    """Discover, rank, fetch, and ingest sources for a part into `documents`.

    Returns a summary dict. Fetchers are injectable for offline tests:
    page_fetcher(url) -> text|None, transcript_fetcher(video_id) -> text|None.
    """
    page_fetcher = page_fetcher or _fetch_page_text
    transcript_fetcher = transcript_fetcher or get_transcript
    meta = _part_meta(part_id)
    own_makes = {str(meta.get("manufacturer") or "").lower()} - {""}

    known = _known_targets(conn, part_id)
    results = _search_web(part_id, part_type, fuel, max_per_query,
                          exa=exa, known_urls=set(known))
    if youtube:
        results += _search_youtube(part_id, part_type, fuel, max_per_query)

    ranked = rank_sources(results, part_id)[:max_sources]

    summary = {"discovered": len(results), "fetched": 0, "ingested": 0,
               "skipped_german": 0, "skipped_foreign": 0, "skipped_fetch": 0,
               "skipped_duplicate": 0}
    for r in ranked:
        if r["url"] in known:
            summary["skipped_duplicate"] += 1
            continue
        if r["type"] == "youtube":
            text = transcript_fetcher(r["video_id"])
        else:
            text = page_fetcher(r["url"])
        if not text:
            summary["skipped_fetch"] += 1
            continue
        summary["fetched"] += 1
        if is_german_text(text):
            summary["skipped_german"] += 1
            continue
        if own_makes and mentions_foreign_manufacturer_code(text, own_makes):
            summary["skipped_foreign"] += 1
            continue
        ingest_document(
            conn,
            Document(text=text, url=r["url"],
                     site_or_channel=r.get("site_or_channel", ""),
                     meta={"part_hint": part_id, "title": r.get("title", "")}),
            source_type=r["type"], target_hint=part_id)
        summary["ingested"] += 1
    conn.commit()
    return summary


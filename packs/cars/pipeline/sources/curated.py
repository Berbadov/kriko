"""Curated source loader — fetch Documents from manually vetted URLs.

Each make+model has a YAML file in packs/cars/pipeline/sources/curated/ listing
specific YouTube video IDs and page URLs that a human has reviewed.

YouTube entries → fetched via yt-dlp (get_transcript)
Page entries    → fetched via trafilatura (universal article extractor)

Fetched text is dropped if it's predominantly German (is_german_text) — the
extraction LLM has been observed echoing German source text verbatim instead
of translating it (see packs/cars/pipeline/stoplists.py). Interim gate, not a
translation fix.

Fetched text is also dropped if it's about a different manufacturer's part
entirely (document_is_foreign_to_part) — e.g. a "K9K engine problems" search
surfacing a page that's actually about VW's 1.5 TDI. Extraction can turn a
100%-off-topic page into claims that still read as plausible for the part
being researched, so this has to be caught before extraction runs, not after
(see packs/cars/pipeline/stoplists.py; docs/design_flaws.md remediation, 2026-07-05).

Usage:
    from packs.cars.pipeline.sources.curated import CuratedSource
    docs = CuratedSource().fetch("renault", "megane")
"""

import logging
from pathlib import Path

import yaml

from packs.cars.pipeline.sources import dates
from packs.cars.pipeline.sources.base import Document
from packs.cars.pipeline.sources.youtube import get_transcript
from packs.cars.pipeline.stoplists import document_is_foreign_to_part, is_german_text

log = logging.getLogger(__name__)

CURATED_DIR = Path(__file__).parent / "curated"

# Browser-like UA + Accept-Encoding without zstd. Many Turkish auto sites
# (arabakolik.net, yoldakiusta.com, …) serve zstd-compressed responses that
# trafilatura.fetch_url cannot decode ("invalid ZSTD file") and 403 a bare UA.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "tr,en;q=0.9",
}


def _fetch_html(url: str) -> str | None:
    """Fetch raw HTML, working around zstd-only / UA-gated sites.

    Tries requests with a browser UA first (decodes gzip/deflate, avoids the
    zstd path), then falls back to trafilatura.fetch_url for anything requests
    can't reach.
    """
    try:
        import requests

        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=20)
        resp.raise_for_status()
        if resp.text:
            return resp.text
    except Exception as exc:
        log.debug("requests fetch failed for %s (%s); trying trafilatura", url, exc)

    try:
        import trafilatura

        return trafilatura.fetch_url(url)
    except Exception as exc:
        log.debug("trafilatura fetch_url failed for %s: %s", url, exc)
        return None


class CuratedSource:
    def fetch(self, make: str, model: str, pending_only: bool = False) -> list[Document]:
        path = CURATED_DIR / f"{make.lower()}_{model.lower()}.yaml"
        if not path.exists():
            log.debug("No curated sources for %s %s (looked at %s)", make, model, path)
            return []

        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if pending_only:
            entries = [e for e in entries if e.get("status", "pending") == "pending"]
        docs: list[Document] = []

        for entry in entries:
            try:
                doc = self._fetch_entry(entry, make, model)
                if doc:
                    docs.append(doc)
            except Exception as exc:
                log.warning("Failed to fetch curated entry %s: %s", entry.get("url") or entry.get("video_id"), exc)

        log.info("CuratedSource: %d/%d documents fetched for %s %s", len(docs), len(entries), make, model)
        return docs

    def _fetch_entry(self, entry: dict, make: str, model: str) -> Document | None:
        channel = entry.get("site_or_channel", "")

        if entry["type"] == "youtube":
            video_id = entry["video_id"]
            text, published_at = get_transcript(video_id)
            if not text:
                log.warning("No transcript for video_id=%s", video_id)
                return None
            if is_german_text(text):
                log.warning("Skipping German-language transcript for video_id=%s", video_id)
                return None
            if document_is_foreign_to_part(text, make, model):
                log.warning("Skipping off-topic (different manufacturer) transcript for video_id=%s", video_id)
                return None
            return Document(
                text=text[:8000],
                url=f"https://www.youtube.com/watch?v={video_id}",
                site_or_channel=channel,
                meta={"make": make, "model": model, "video_id": video_id},
                published_at=published_at,
            )

        if entry["type"] == "page":
            try:
                import trafilatura
            except ImportError:
                log.error("trafilatura not installed — run: pip install trafilatura")
                return None
            url = entry["url"]
            html = _fetch_html(url)
            if not html:
                log.warning("Could not fetch page: %s", url)
                return None
            text = trafilatura.extract(html, include_comments=False, include_tables=False)
            if not text:
                log.warning("trafilatura extracted no content from: %s", url)
                return None
            if is_german_text(text):
                log.warning("Skipping German-language page: %s", url)
                return None
            if document_is_foreign_to_part(text, make, model):
                log.warning("Skipping off-topic (different manufacturer) page: %s", url)
                return None
            return Document(
                text=text[:8000],
                url=url,
                site_or_channel=channel,
                meta={"make": make, "model": model},
                published_at=dates.page_published_at(html, source=url),
            )

        log.warning("Unknown curated entry type: %s", entry.get("type"))
        return None


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    make  = sys.argv[1] if len(sys.argv) > 1 else "renault"
    model = sys.argv[2] if len(sys.argv) > 2 else "megane"
    docs  = CuratedSource().fetch(make, model)
    for d in docs:
        print(f"\n{d.site_or_channel} — {d.url}")
        print(d.text[:300] + ("…" if len(d.text) > 300 else ""))

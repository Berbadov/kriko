"""Specialist repair & technical sources.

These are the highest-quality sources: independent garages, parts-supplier
technical blogs, and engine remanufacturers.

HUMAN DECISION #5: which exact sites are in-scope per model (liveness + ToS)
must be confirmed before this adapter ships to production.
"""

import logging

import httpx
from selectolax.parser import HTMLParser

from knowledge.sources.base import Document

log = logging.getLogger(__name__)

# HUMAN DECISION #5: confirm ToS + liveness before enabling each entry.
SPECIALIST_SOURCES: list[dict] = [
    {
        "site": "enginefinders.co.uk",
        "url_template": "https://www.enginefinders.co.uk/search?q={make}+{model}+problems",
        "content_selector": "article, .post-content, .entry-content",
    },
    # Add entries here as new specialist sources are verified.
]


class SpecialistSource:
    def fetch(self, make: str, model: str) -> list[Document]:
        docs: list[Document] = []
        for source in SPECIALIST_SOURCES:
            try:
                url = source["url_template"].format(make=make.lower(), model=model.lower())
                resp = httpx.get(url, timeout=15, follow_redirects=True,
                                 headers={"User-Agent": "KrikoBot/0.1 (reliability research)"})
                resp.raise_for_status()
                tree = HTMLParser(resp.text)
                text = " ".join(
                    node.text(strip=True)
                    for node in tree.css(source["content_selector"])
                    if node.text(strip=True)
                )
                if text:
                    docs.append(Document(
                        text=text[:8000],
                        url=url,
                        site_or_channel=source["site"],
                        meta={"make": make, "model": model},
                    ))
            except Exception as exc:
                log.warning("specialist source %s failed: %s", source["site"], exc)
        return docs

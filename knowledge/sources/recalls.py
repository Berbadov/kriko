"""Recalls adapter — safety-critical only.

Strictly maps manufacturer safety recalls (airbags, brakes) for a given
variant. NOT used for mechanical wear items (EGR, DPF, injectors).

Sources:
- car-recalls.eu (EU safety recall aggregator)
- Renault/manufacturer VIN lookup pages

HUMAN DECISION #5: confirm data licensing and ToS for each source.
"""

import logging

import httpx
from selectolax.parser import HTMLParser

from knowledge.sources.base import Document

log = logging.getLogger(__name__)

CAR_RECALLS_URL = "https://www.car-recalls.eu/search/?q={make}+{model}"


class RecallsSource:
    def fetch(self, make: str, model: str) -> list[Document]:
        docs: list[Document] = []
        try:
            url = CAR_RECALLS_URL.format(make=make.lower(), model=model.lower())
            resp = httpx.get(url, timeout=15, follow_redirects=True,
                             headers={"User-Agent": "KrikoBot/0.1 (recall research)"})
            resp.raise_for_status()
            tree = HTMLParser(resp.text)
            # car-recalls.eu lists recalls in .recall-item or table rows
            text = " ".join(
                node.text(strip=True)
                for node in tree.css(".recall-item, .recall-description, table td")
                if node.text(strip=True)
            )
            if text:
                docs.append(Document(
                    text=text[:10000],
                    url=url,
                    site_or_channel="car-recalls.eu",
                    meta={"make": make, "model": model, "type": "recall"},
                ))
        except Exception as exc:
            log.warning("RecallsSource failed for %s %s: %s", make, model, exc)
        return docs

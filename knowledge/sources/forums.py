"""Semi-structured owner & engine forums.

High specificity. Real diagnostic threads with anecdotal data. Two or more
independent sources from different sites are required to verify a claim.

HUMAN DECISION #5: which exact forums/subreddits are in-scope per model
(liveness + ToS) must be confirmed before this adapter ships.
"""

import logging

import httpx
from selectolax.parser import HTMLParser

from knowledge.sources.base import Document

log = logging.getLogger(__name__)

# HUMAN DECISION #5: confirm ToS + liveness for each entry.
FORUM_SOURCES: dict[str, list[dict]] = {
    "megane": [
        {
            "site": "renaultforums.co.uk",
            "url_template": "https://www.renaultforums.co.uk/search?q={engine_hint}+problem",
            "content_selector": ".postbody, .post-message, .message-content",
        },
        {
            "site": "cliosport.net",
            "url_template": "https://www.cliosport.net/search?q={engine_hint}+issue",
            "content_selector": ".messageContent, .message-body",
        },
    ],
    "clio": [
        {
            "site": "cliosport.net",
            "url_template": "https://www.cliosport.net/search?q={engine_hint}+problem",
            "content_selector": ".messageContent, .message-body",
        },
    ],
}


class ForumSource:
    def fetch(self, make: str, model: str) -> list[Document]:
        docs: list[Document] = []
        sources = FORUM_SOURCES.get(model.lower(), [])
        for source in sources:
            try:
                url = source["url_template"].format(
                    make=make.lower(), model=model.lower(), engine_hint=""
                )
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
                log.warning("forum source %s failed: %s", source["site"], exc)
        return docs

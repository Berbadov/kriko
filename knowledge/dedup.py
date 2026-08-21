"""Deduplication — merge same-claim candidates, collapse non-independent sources.

Two sources are non-independent if: same domain, same channel/author, or
near-identical wording. Derivative reposts collapse to a single source.

This module runs OFFLINE only — never on the /analyze request path.
"""

import logging

from knowledge.title_sim import title_tokens
from knowledge.extract import CandidateClaim
from knowledge.sources.base import Document

log = logging.getLogger(__name__)


def same_claim(a: CandidateClaim, b: CandidateClaim) -> bool:
    """Do these two candidates describe the same underlying issue?

    Uses title-word Jaccard — fast, no LLM, no API calls, scales to thousands.
    Threshold 0.4: "H5F timing chain stretch" vs "1.2 TCe timing chain wear" → same.
    """
    if a.domain != b.domain:
        return False

    tok_a = title_tokens(a.title)
    tok_b = title_tokens(b.title)
    if not tok_a or not tok_b:
        return False

    jaccard = len(tok_a & tok_b) / len(tok_a | tok_b)
    return jaccard >= 0.4


def is_independent(a_doc: Document, b_doc: Document) -> bool:
    """Two source documents are NOT independent if they share domain/channel
    or have near-identical wording. Derivative reposts collapse to a single source.
    """
    def _domain(url: str) -> str:
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc.lower().lstrip("www.")
        except Exception:
            return url

    if _domain(a_doc.url) == _domain(b_doc.url):
        return False

    if a_doc.site_or_channel and b_doc.site_or_channel:
        if a_doc.site_or_channel.lower() == b_doc.site_or_channel.lower():
            return False

    # Near-identical wording check (cheap, no LLM): Jaccard on word sets
    words_a = set(a_doc.text.lower().split())
    words_b = set(b_doc.text.lower().split())
    if words_a and words_b:
        overlap = len(words_a & words_b) / len(words_a | words_b)
        if overlap > 0.85:
            return False

    return True


def merge_candidates(
    candidates: list[tuple[CandidateClaim, Document]]
) -> list[tuple[CandidateClaim, list[Document]]]:
    """Group candidates that describe the same claim, collecting their source docs.

    Returns a list of (representative_claim, [unique_source_docs]).
    """
    groups: list[tuple[CandidateClaim, list[Document]]] = []

    for claim, doc in candidates:
        placed = False
        for rep, docs in groups:
            if same_claim(rep, claim):
                if all(is_independent(doc, d) for d in docs):
                    docs.append(doc)
                placed = True
                break
        if not placed:
            groups.append((claim, [doc]))

    return groups

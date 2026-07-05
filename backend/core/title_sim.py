"""Title similarity via Jaccard on tokenised word sets.

Shared between the offline dedup pipeline (knowledge/dedup.py) and the serving
plane (resolver.py) so both use the same tokeniser and threshold.

Two titles are "similar" when their word-set Jaccard ≥ 0.4 after stripping
stopwords and non-alphanumeric characters.
"""

import re

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "for", "with", "and",
    "or", "to", "is", "are", "was", "were", "has", "have", "had",
    "its", "it", "this", "that", "from", "by", "be", "not", "no",
}


def title_tokens(title: str) -> set[str]:
    """Lowercase, strip punctuation, split, remove stopwords and single chars."""
    words = re.sub(r"[^a-z0-9 ]", " ", title.lower()).split()
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def title_similar(title_a: str, title_b: str, threshold: float = 0.4) -> bool:
    """Return True when the title-word Jaccard similarity ≥ threshold."""
    tok_a = title_tokens(title_a)
    tok_b = title_tokens(title_b)
    if not tok_a or not tok_b:
        return False
    return len(tok_a & tok_b) / len(tok_a | tok_b) >= threshold

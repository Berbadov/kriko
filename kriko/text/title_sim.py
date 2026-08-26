"""Title similarity — the deduplication a reader actually experiences.

Content hashing gives *storage* identity, and it works: the same URL, the same
quote, the same normalised value all collapse. It does almost nothing for
claims, because claim titles are written by language models and language models
do not write the same sentence twice. The live car catalog holds three separate
titles for one physical EGR failure, produced by the same pipeline on the same
day. Two independent packs will produce three more.

So this is not a nicety layered on top of the real mechanism — for claims it *is*
the mechanism, and it has to run at read time, because which of several near-
duplicate claims is "best" depends on the reader's context and installed packs.

Two titles are the same claim when their word-set Jaccard is at least 0.4 after
stopwords are removed. The threshold is inherited from the pipeline that
produced this data; a different corpus would want a different number, which is
why it is an argument and not a constant.
"""

import re

# Deliberately English-only. The tokeniser strips non-ASCII, so Turkish titles
# compare on their shared technical nouns (part names, codes) — which is the
# signal that matters and the part that does not get translated.
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "for", "with", "and",
    "or", "to", "is", "are", "was", "were", "has", "have", "had",
    "its", "it", "this", "that", "from", "by", "be", "not", "no",
})

DEFAULT_THRESHOLD = 0.4


def title_tokens(title: str) -> set[str]:
    """Lowercase, strip punctuation, drop stopwords and single characters."""
    words = re.sub(r"[^a-z0-9 ]", " ", title.lower()).split()
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def similarity(title_a: str, title_b: str) -> float:
    tokens_a, tokens_b = title_tokens(title_a), title_tokens(title_b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def title_similar(title_a: str, title_b: str,
                  threshold: float = DEFAULT_THRESHOLD) -> bool:
    return similarity(title_a, title_b) >= threshold


def cluster(items, key, group=None, threshold: float = DEFAULT_THRESHOLD):
    """Group near-duplicate items, greedily, in the order given.

    `key(item)` supplies the title; `group(item)` supplies a hard partition that
    similarity may not cross — two claims about different subsystems are never
    the same claim however alike their words. Callers pass items already sorted
    best-first, so the first member of each cluster is the one worth keeping and
    the rest are the duplicates it absorbs.

    Greedy rather than exhaustive: it is O(n·clusters) instead of O(n²), and
    with a best-first input the representative is chosen before any comparison
    is made, so the cheaper algorithm loses nothing that matters.
    """
    group = group or (lambda _: "")
    clusters: list[list] = []
    heads: list[tuple[str, str]] = []      # (group, title) per cluster

    for item in items:
        item_group, title = group(item), key(item)
        for index, (head_group, head_title) in enumerate(heads):
            if head_group == item_group and title_similar(title, head_title, threshold):
                clusters[index].append(item)
                break
        else:
            clusters.append([item])
            heads.append((item_group, title))

    return clusters

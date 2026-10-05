"""Which part of a long page a model is shown.

Every plane hands a model a bounded window of each document
(`Spend.context_chars`, a local page's `PAGE_CHARS`). Taken from the top, that
window is whatever the page put first: its navigation, a cookie notice, the
site's other products. The part that is about the subject is often past the
cut, so the run spends its tokens on the menu and misses the finding.

`focus` keeps the opening (the title says what the page is), then the blocks
that mention the run's own terms most, in the page's own order. The terms come
from the caller (the task's label, identity and queries), so nothing here
knows a category: it counts words, it does not read them.
"""

import re
from typing import Iterable

#: Words shorter than this match too much to say what a block is about.
_MIN_WORD = 3
#: Where blocks the window skipped were, so a model does not read two
#: distant blocks as one passage.
GAP = "\n\n[…]\n\n"
_WORD = re.compile(r"\w+")


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.casefold()) if len(w) >= _MIN_WORD}


def _blocks(text: str, limit: int) -> list[str]:
    """Paragraphs, and a paragraph too long to rank whole split into lines."""
    out: list[str] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if len(block) > limit // 4:
            out.extend(line.strip() for line in block.split("\n") if line.strip())
        else:
            out.append(block)
    return out


def focus(text: str, limit: int, terms: Iterable[str] = ()) -> str:
    """At most `limit` characters of `text`, the subject's part first.

    A text that fits is returned unchanged, and so is the plain head when
    no term was given: without terms there is nothing to rank by.
    """
    if len(text) <= limit:
        return text
    wanted = set()
    for term in terms:
        wanted |= _words(str(term))
    if not wanted:
        return text[:limit]
    blocks = _blocks(text, limit)
    if not blocks:
        return text[:limit]

    def score(block: str) -> int:
        found = [w for w in _WORD.findall(block.casefold()) if w in wanted]
        # Distinct terms first: a block naming the product and its fault
        # beats one repeating the brand.
        return len(set(found)) * 4 + len(found)

    order = sorted(range(1, len(blocks)), key=lambda i: (-score(blocks[i]), i))
    chosen = [0]
    used = len(blocks[0])
    for index in order:
        if score(blocks[index]) == 0:
            break
        cost = len(blocks[index]) + len(GAP)
        if used + cost > limit:
            continue
        chosen.append(index)
        used += cost
    # Room left after every block that mentions the subject goes to the
    # page's own order, so a short window is never emptier than the head.
    for index in range(1, len(blocks)):
        if index in chosen:
            continue
        cost = len(blocks[index]) + len(GAP)
        if used + cost > limit:
            break
        chosen.append(index)
        used += cost
    chosen.sort()
    parts: list[str] = []
    previous = -1
    for index in chosen:
        if parts:
            parts.append(GAP if index != previous + 1 else "\n\n")
        parts.append(blocks[index])
        previous = index
    return "".join(parts)[:limit]


def terms_of(task) -> tuple[str, ...]:
    """What a research task is about, in its own words: label, identity
    values, search names and the queries it runs."""
    identity = getattr(task, "identity", {}) or {}
    return (
        str(getattr(task, "subject_label", "") or ""),
        *(str(value) for value in identity.values()),
        *(getattr(task, "search_names", ()) or ()),
        *task.rendered_queries(),
    )

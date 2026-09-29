"""Deterministic span grounding for extracted text."""

import re
import unicodedata

#: Characters an extractor or a model is free to swap without changing the
#: sentence. The same rule `app/factcheck.py` applies to a stored quote years
#: later, applied here to a quote seconds after it was produced: a curly
#: apostrophe or a collapsed run of whitespace is not evidence the quote was
#: invented, and rejecting it on that basis would teach nobody anything except
#: to distrust the gate.
_SAME_CHARS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", "…": "...",
}


def find_span(source: str, quote: str, start: int = 0) -> tuple[int | None, int | None]:
    """Return the first exact quote span, preferring the requested offset."""
    if not quote:
        return None, None
    position = source.find(quote, max(0, start))
    if position < 0:
        position = source.find(quote)
    if position < 0:
        return None, None
    return position, position + len(quote)


def is_grounded(source: str, quote: str) -> bool:
    """Whether ``quote`` occurs verbatim in ``source``."""
    return bool(quote) and quote in source


def comparable(text: str) -> str:
    """The comparable form of a quote or a document, for the grounding check.

    Deliberately loose about whitespace and case and strict about everything
    else — a model that reconstructs a sentence from memory still has to fail,
    and the two things this folds away are cosmetic in every language this
    runs against. Case-folding does not make a fabricated quote harder to
    catch: truth does not live in capitalisation.
    """
    text = unicodedata.normalize("NFKC", text or "")
    for needle, plain in _SAME_CHARS.items():
        text = text.replace(needle, plain)
    return re.sub(r"\s+", " ", text).strip().casefold()


#: Every character `_SAME_CHARS` treats as interchangeable, mapped to a regex
#: that matches any member of its family — "’" matches "'" and "’" alike.
_FAMILIES: dict[str, list[str]] = {}
for _needle, _plain in _SAME_CHARS.items():
    _FAMILIES.setdefault(_plain, [_plain]).append(_needle)
_ANY_OF = {
    member: "(?:" + "|".join(re.escape(one) for one in members) + ")"
    for members in _FAMILIES.values()
    for member in members
}
_LONGEST_FIRST = sorted(_ANY_OF, key=len, reverse=True)


def _word_pattern(word: str) -> str:
    out, at = [], 0
    while at < len(word):
        member = next((one for one in _LONGEST_FIRST if word.startswith(one, at)), "")
        if member:
            out.append(_ANY_OF[member])
            at += len(member)
        else:
            out.append(re.escape(word[at]))
            at += 1
    return "".join(out)


def loose_span(source: str, quote: str) -> str:
    """The text of ``source`` that ``quote`` matches loosely, or ``""``.

    Loose the way `comparable` is — whitespace, case, curly quotes and dashes —
    but the answer is the *source's own characters*, not a yes. That matters
    wherever the quote is kept: ingestion checks `is_grounded`, which is exact,
    so a quote a model re-typed with a straight apostrophe is replaced by the
    page's text rather than refused, and the stored quote is then a substring
    of the stored page, which is the claim the evidence chain makes.

    Stricter than `comparable` on one point: no NFKC folding, because a
    compatibility form changes length and a span has to map back onto the
    source. A quote that differs from its page only by a ligature is not found.
    """
    words = (quote or "").split()
    if not words:
        return ""
    found = re.search(r"\s+".join(map(_word_pattern, words)), source or "", re.IGNORECASE)
    return found.group(0) if found else ""

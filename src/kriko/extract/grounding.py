"""Deterministic span grounding for extracted text."""


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

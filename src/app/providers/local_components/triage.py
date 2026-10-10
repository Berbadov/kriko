"""Choosing the pages a small context actually has room for.

The old agent sent five pages of six thousand characters each — up to thirty
thousand characters — to a socket that says it has twelve thousand, and the
model answered from whatever fell off the end of its context first. That is
the exact failure the reader paid for a *small* model to be spared: it did not
choose badly, it was handed more than it could hold.

Triage is the fix, in two moves:

* **Rank.** Score every page by the words it shares with the task and the
  queries that found it. A lexical score, not a model call — ranking is
  arithmetic and the model's calls are the run's slowest currency.
* **Fit.** Spend the model's own context on the best pages: the budget comes
  from the completion socket itself, minus the task and room for the reply,
  and each kept page gets an equal share, so what the model sees is the
  whole of a few good pages rather than the head of everything.

The truncation is the grounding contract, kept from the old code: the text
kept in ``sources`` is the same characters the model saw, so a quote from
beyond what the model saw could only have been invented.
"""

#: Chars of the budget kept for the answer itself. A quick look's reply is a
#: fenced JSON object of a few risks; this is room for a slow model's prose
#: around it, not a datasheet.
REPLY_ROOM = 2500

#: Below this many characters a page is not worth sending at all: a share of
#: the budget that cannot hold a paragraph cannot hold a quote either.
MIN_PAGE_CHARS = 800

#: The context a socket that says nothing about itself is given. The
#: completion socket's own default, repeated here so a change to either side
#: of this contract is a deliberate one.
DEFAULT_CONTEXT = 12000


def budget_of(complete) -> int:
    """The chars of context this model's completion socket says it has.

    ``OpenAICompatSocket.context_chars`` is the one honest source: the socket
    is built per model, and a model that says nothing defaults rather than
    guesses.
    """
    allowed = getattr(complete, "prompt_chars_allowed", None)
    if callable(allowed):
        # The socket already reserves output tokens; choose subtracts this
        # fixed room for legacy callables only.
        return allowed() + REPLY_ROOM
    value = getattr(complete, "context_chars", 0)
    return value if isinstance(value, int) and value > 0 else DEFAULT_CONTEXT


_STOP = {"the", "a", "an", "of", "and", "or", "to", "is", "are", "it", "in",
         "for", "with", "this", "that", "what", "when", "which", "how", "on",
         "at", "be", "was", "one", "any", "all", "its", "their", "they",
         "you", "your", "known", "go", "goes", "wrong", "about"}


def _words(text: str) -> set[str]:
    """The words that could be shared, casefolded, minus English function
    words. No product vocabulary lives here; the words come from the task."""
    words = set()
    for one in str(text).casefold().split():
        stripped = one.strip(".,:;!?()[]{}\"'`*_->#$%&@/\\|~+=\u201c\u201d")
        if len(stripped) > 2 and stripped not in _STOP:
            words.add(stripped)
    return words


def score(url: str, text: str, wanted: set[str]) -> int:
    """How much of the task's own words a page carries, url included."""
    hits = len(_words(text) & wanted)
    host_words = {one for one in url.casefold().split("/")[2].split(".")
                  if len(one) > 2} if url.startswith(("http://", "https://")) else set()
    return hits + len(host_words & wanted)


def choose(pages, *, task: str, queries: list[str], budget: int,
           at_most: int, page_cap: int) -> list[tuple[str, str]]:
    """The pages worth the context they cost, best first, fitted to the budget.

    Returns ``(url, text)`` pairs whose text is what the model will see —
    the same text the caller must keep as its ``sources``.
    """
    wanted = _words(task)
    for one in queries:
        wanted |= _words(one)
    from .identity import codes, contains
    anchors = codes(task)
    ranked = sorted(pages, key=lambda page: (
        -sum(contains(page[1], code) for code in anchors),
        -score(page[0], page[1], wanted)))

    room = budget - len(task) - REPLY_ROOM
    kept: list[tuple[str, str]] = []
    for url, text in ranked:
        if len(kept) >= at_most:
            break
        if room // (len(kept) + 1) < MIN_PAGE_CHARS:
            break
        kept.append((url, text))
    if not kept:
        # A budget too small for even one page still gets one, whole and
        # capped: a run that answers from a truncated page beats a run that
        # answers from no page, and the grounding contract survives because
        # the cap is applied to what the model sees.
        if not ranked or room <= len(ranked[0][0]) + 16:
            return []
        url, text = ranked[0]
        from kriko.research.window import focus
        return [(url, focus(text, min(page_cap, room - len(url) - 16),
                            queries + sorted(anchors)))]
    per_page = min(page_cap, room // len(kept))
    from kriko.research.window import focus

    return [(url, focus(text, max(0, per_page - len(url) - 16),
                        queries + sorted(anchors)))
            for url, text in kept]

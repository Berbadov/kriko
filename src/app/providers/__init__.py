"""The paid research plane's three sockets.

`kriko/research/api.py` has always been able to run a per-token research plane.
It has never been able to *start* one, because it takes its three abilities as
injected callables and nothing supplied them — `get_researcher({"backend":
"api"})` raised `TypeError` on a missing argument. That was deliberate: the
engine owns no socket, so the thing that knows how to reach `api.exa.ai` cannot
live in `kriko/`. It lives here.

Three modules, one callable each, shaped exactly as `ApiResearcher.__init__`
documents them:

    exa.searcher()   -> search(query, limit) -> [{"url", "title", "site"}]
    fetch.reader()   -> fetch(url)           -> plain text, or ""
    llm.completer()  -> complete(prompt)     -> the model's reply

**Stdlib HTTP, on purpose.** `exa-py` and `openai` are both in the `pipeline`
optional extra, which the desktop binary does not carry; making them core
dependencies would charge every reader who never sets a key for three JSON
requests. `urllib.request` is enough for all three, and it is enough in a
PyInstaller onefile with no extra hidden imports.

**No accounting here.** Cost is charged in exactly one place —
`ApiResearcher._charge`, which raises `BudgetExceeded` — and an adapter that
kept its own running total would be a second answer to "how much did this
cost". These functions make one request and return its result.
"""

from app.providers import exa, fetch, llm

__all__ = ["exa", "fetch", "llm", "api_researcher", "MissingKey"]


class MissingKey(RuntimeError):
    """The paid plane was asked for and there is no key to pay with.

    A distinct type because the answer is a screen, not a stack trace: the
    caller turns this into "set a key in Settings → Research" rather than
    reporting a failed run.
    """


def api_researcher(*, price_per_call: float = 0.0):
    """The per-token plane, wired to the keys this installation actually has.

    Raises `MissingKey` rather than building a researcher that would fail on
    its first request. The default plane is still `agent`; nothing calls this
    unless a reader chose the paid one.
    """
    from kriko.research import ApiResearcher

    model = llm.model_name()
    researcher = ApiResearcher(
        exa.searcher(),
        fetch.reader(),
        llm.completer(model=model),
        price_per_call=price_per_call,
    )
    # Stamped on the instance rather than passed to the constructor: the engine
    # has no field for either, and it should not — "which vendor" is a fact
    # about this installation's sockets, and `kriko/` owns none. `app/web/
    # tasks.py` reads them duck-typed for the provenance row, exactly as it
    # already reads `tokens_used`.
    researcher.model = model
    researcher.search_provider = "exa"
    return researcher

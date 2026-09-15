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

from app.providers import exa, fetch, harness, llm

__all__ = [
    "exa", "fetch", "harness", "llm",
    "api_researcher", "harness_researcher",
    "MissingKey", "NoHarness",
]

NoHarness = harness.NoHarness


class MissingKey(RuntimeError):
    """The paid plane was asked for and there is no key to pay with.

    A distinct type because the answer is a screen, not a stack trace: the
    caller turns this into "set a key in Settings → Research" rather than
    reporting a failed run.
    """


def _searcher(app_state_path, preferred: str = ""):
    """The search provider this installation should use, and why that one.

    Order: what the reader chose, then what has a key, then Exa — and the
    reason the choice comes first is that a provider with a key is not
    necessarily the one they want their queries going to. `MissingKey` if
    neither is configured, because a paid plane that cannot search is not a
    degraded plane, it is a run that fails on its first query.
    """
    from app import keys

    wanted = preferred
    if not wanted and app_state_path is not None:
        from app import prefs
        from app.web import state

        conn = state.connect(app_state_path)
        try:
            wanted = prefs.read(conn).get(prefs.SEARCH, "")
        finally:
            conn.close()
    have = keys.search_providers()
    if wanted and wanted in have:
        picked = wanted
    elif have:
        picked = have[0]
    else:
        raise MissingKey(
            "no search key is set. The paid plane searches and reads: add an "
            "Exa or Tavily key in Settings → Research."
        )
    if picked == "tavily":
        from app.providers import tavily

        return tavily.searcher(), "tavily"
    return exa.searcher(), "exa"


def api_researcher(*, price_per_call: float = 0.0, app_state_path=None, spend=None,
                   model: str = "", search: str = ""):
    """The per-token plane, wired to the keys this installation actually has.

    Raises `MissingKey` rather than building a researcher that would fail on
    its first request. The default plane is still `agent`; nothing calls this
    unless a reader chose the paid one.

    `spend` is the protocol — how much context per call and how many documents
    per call (B123). Named explicitly by the benchmark, which is measuring one;
    chosen from this installation's own measurements otherwise, and `STANDARD`
    when there are none. The picking is here rather than in `kriko/` for the
    layering reason `app/protocols.py` opens with: choosing means reading
    interface state, and the engine may not.
    """
    from kriko.research import ApiResearcher

    model = llm.model_name(model or _preferred_model(app_state_path))
    if spend is None:
        from app import protocols

        spend = (
            protocols.spend_for(app_state_path, model)
            if app_state_path is not None
            else None
        )
    found, provider = _searcher(app_state_path, search)
    researcher = ApiResearcher(
        found,
        fetch.reader(),
        llm.completer(model=model),
        price_per_call=price_per_call,
        spend=spend,
    )
    # Stamped on the instance rather than passed to the constructor: the engine
    # has no field for either, and it should not — "which vendor" is a fact
    # about this installation's sockets, and `kriko/` owns none. `app/web/
    # tasks.py` reads them duck-typed for the provenance row, exactly as it
    # already reads `tokens_used`.
    researcher.model = model
    researcher.search_provider = provider
    # Stamped like `model` and for the same reason: `app/web/tasks.py` reads it
    # duck-typed, and a measurement whose settings were not recorded cannot be
    # compared with the next one.
    researcher.protocol = researcher.spend.name
    return researcher


def _preferred_model(app_state_path) -> str:
    """The model the reader chose, or `""` for the environment's own."""
    if app_state_path is None:
        return ""
    from app import prefs
    from app.web import state

    try:
        conn = state.connect(app_state_path)
    except Exception:  # noqa: BLE001 — a preference is never why a run fails
        return ""
    try:
        return prefs.read(conn).get(prefs.MODEL, "")
    finally:
        conn.close()


def harness_researcher(*, preferred: str = "", timeout: float = 0.0,
                       app_state_path=None):
    """The $0 plane that actually runs, wired to whichever CLI is installed.

    The sibling of `api_researcher` in shape and its opposite in cost: this one
    spends nothing of Kriko's because the subscription is the reader's own. It
    raises `NoHarness` rather than returning a researcher that would fail on
    its first subject, for the same reason the paid plane raises `MissingKey` —
    "no agent installed" is a screen with an answer on it, not a failed run.
    """
    if not preferred and app_state_path is not None:
        from app import prefs
        from app.web import state

        try:
            conn = state.connect(app_state_path)
        except Exception:  # noqa: BLE001 — see `_preferred_model`
            conn = None
        if conn is not None:
            try:
                preferred = prefs.read(conn).get(prefs.HARNESS, "")
            finally:
                conn.close()
    found = harness.chosen(preferred)
    if found is None:
        names = ", ".join(h.executable for h in harness.KNOWN)
        raise harness.NoHarness(
            f"no coding-agent CLI on PATH (looked for: {names})"
        )
    researcher = harness.HarnessResearcher(
        found, timeout=timeout or harness.TIMEOUT_SECONDS
    )
    return researcher

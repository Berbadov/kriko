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


def completer_for(model: str):
    """The adapter that speaks to whoever serves this model.

    Routed on the *model name* rather than on a provider setting, because the
    reader picks a model and should not also have to tell us who sells it —
    and because with a model chosen per stage of a run (`app/prefs.py`'s
    roles), a single provider setting could not describe a run that used two.

    `models.toml` is the routing table, which is the same file the reader edits
    to correct a price: pointing a gateway at a new model and naming its
    provider is one row, not a release. An unlisted model falls to the
    OpenAI-shaped adapter, which is the format everything but Anthropic
    implements.
    """
    from app import modelcatalogue
    from app.web.settings import KRIKO_HOME

    provider = modelcatalogue.provider_for(model, KRIKO_HOME)
    if provider not in ("openai", "anthropic"):
        raise MissingKey(f"no completion adapter for {provider}")
    if provider == "anthropic":
        # The prefix check is a fallback for a model released after the
        # reader's catalogue was written: `claude-` is Anthropic's own
        # namespace, so sending it to an OpenAI-shaped endpoint could only
        # ever fail.
        from app.providers import anthropic_llm

        return anthropic_llm.completer(model=model)
    return llm.completer(model=model)
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
    wanted = wanted.strip()
    have = keys.search_providers()
    if wanted:
        if wanted not in have:
            raise MissingKey(f"selected search provider {wanted!r} is unavailable — add its key or change the selection")
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
        completer_for(model),
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
        return prefs.for_role(conn, "extract")
    finally:
        conn.close()


def harness_researcher(*, preferred: str = "", timeout: float = 0.0,
                       app_state_path=None, model: str = "", effort: str = ""):
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
    note = ""
    if found is None and preferred:
        # The reader's preference names a CLI that is not installed here —
        # `harness.chosen(preferred)` says so by returning `None` rather than
        # silently substituting anything, which is correct for *it*. But a
        # run failing outright when a different, perfectly usable CLI is
        # sitting right there is the crash this function exists to avoid: an
        # unknown or uninstalled choice must fall back visibly, not refuse.
        fallback = harness.chosen("")
        if fallback is not None:
            found = fallback
            note = (
                f"preferred harness {preferred!r} is not installed here — "
                f"used {fallback.id} instead"
            )
    if found is None:
        names = ", ".join(h.executable for h in harness.KNOWN)
        raise harness.NoHarness(
            f"no coding-agent CLI on PATH (looked for: {names})"
        )
    # Resolved against the harness that will actually run, not the one that
    # was preferred: a model chosen for claude handed to agy would be a name
    # from the wrong namespace running as if it were right.
    if not model.strip() and app_state_path is not None:
        from app import prefs
        from app.web import state

        try:
            conn = state.connect(app_state_path)
        except Exception:  # noqa: BLE001 — see `_preferred_model`
            conn = None
        if conn is not None:
            try:
                model = prefs.for_harness(conn, found.id)
            finally:
                conn.close()
    # Resolved against the harness that will actually run, on the same
    # reasoning as the model above: `xhigh` is a level claude accepts and agy
    # does not, so a level chosen for one handed to the other is an argument
    # error rather than a cheaper run.
    if not effort.strip() and app_state_path is not None:
        from app import prefs
        from app.web import state

        try:
            conn = state.connect(app_state_path)
        except Exception:  # noqa: BLE001 — see `_preferred_model`
            conn = None
        if conn is not None:
            try:
                effort = prefs.effort_for_harness(conn, found.id)
            finally:
                conn.close()
    # A level this machine's CLI will not take is dropped, not raised. The
    # reader chose it for a harness that is no longer the one running, or on a
    # build whose `--help` has since changed, and losing the run over a dial
    # would be worse than losing the dial.
    if effort.strip() and effort.strip() not in harness.efforts_for(found):
        effort = ""
    researcher = harness.HarnessResearcher(
        found, timeout=timeout or harness.TIMEOUT_SECONDS, model=model.strip(),
        effort=effort.strip(),
    )
    if note:
        # Duck-typed, read by `app/web/tasks.py` when the run gathers nothing
        # to say *why* — the same slot `_empty_run_note` already reads. Not
        # every run reaches that message (one that gathers real documents
        # never mentions it), which is a known gap: see the final report.
        researcher.note = note
    return researcher

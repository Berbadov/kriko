"""What the reader chose: which agent, which model, which search provider.

Three choices existed as facts and not as decisions: the harness plane took the
first CLI it could find, the paid plane took whatever `LLM_MODEL` said, and
search meant Exa because Exa was the only provider with code. Each is fine as a
default and wrong as a rule — a reader with Claude Code *and* opencode has a
preference, a reader paying per token has a very strong opinion about which
model, and a second search provider is worth nothing if nothing can select it.

Kept in `app.sqlite`'s settings, not in the environment: a preference is
interface state, it must survive an update, and it must not require editing a
file to change. Every one of them falls back to the old behaviour when unset,
so an installation that never opens this screen behaves exactly as it did.

**Nothing here decides what a run costs — it decides what a run *uses*.** The
cost of the choice is `app/costs.py`'s job, and the two are deliberately
separate: a preference the reader can set without being shown the bill is how
a $40 surprise happens.
"""

from app import modelcatalogue

#: The settings keys. Named once, here, because both the router that writes
#: them and the providers that read them would otherwise spell them twice.
HARNESS = "preferred_harness"
MODEL = "llm_model"
SEARCH = "search_provider"

#: One key per stage of a run, and every one of them optional.
#:
#: The reader asked to put a cheap model on extraction and a strong one on
#: synthesis, which only works if the stages can differ — but a first-time
#: reader must never meet four dropdowns where there was one. So each falls
#: back to `MODEL`, and an installation that never opens the advanced control
#: behaves exactly as it did.
def role_key(role: str) -> str:
    return f"{MODEL}_{role}"


ROLE_KEYS = tuple(role_key(one) for one in modelcatalogue.ROLES)


def harness_model_key(harness_id: str) -> str:
    return f"harness_model_{harness_id}".replace("-", "_")


def harness_effort_key(harness_id: str) -> str:
    """Where this harness's effort level is stored.

    A second dial beside the model, and a separate key rather than a field on
    the model's value, because the two are chosen independently: a reader
    surveying cheaply picks the same model and drops the effort, and a reader
    checking one expensive answer does the reverse.
    """
    return f"harness_effort_{harness_id}".replace("-", "_")


#: One key per harness that can take a model, and one for its effort.
#:
#: **Derived from the roster, not listed here.** The hand-written tuple this
#: replaces named three harnesses and Mistral Vibe was not one of them — so a
#: model chosen for the harness the reader added specifically to stop spending
#: Claude tokens was dropped on write and silently ran as the CLI's default.
#: That is the failure mode `CLAUDE.md`'s scalability rule is about: a list
#: somebody has to remember to extend, whose staleness raises nothing.
#:
#: Every harness gets both keys regardless of what it supports. Which dials a
#: *screen* offers is `models_for`/`efforts_for`'s answer and depends on the
#: machine; which keys are storable is a fixed shape, and gating storage on a
#: probe would mean a preference that vanishes when a CLI is uninstalled.
def _harness_ids() -> tuple[str, ...]:
    # Deferred: `app.providers.harness` is a heavier import than this module
    # wants at definition time, and nothing here needs it before first use.
    from app.providers import apiagent
    from app.providers import harness as harness_mod

    # The API agents take a model too (B153), and are picked in the same row.
    return (*(one.id for one in harness_mod.KNOWN), *(one.id for one in apiagent.KNOWN))


HARNESS_MODEL_KEYS = tuple(harness_model_key(one) for one in _harness_ids())
HARNESS_EFFORT_KEYS = tuple(harness_effort_key(one) for one in _harness_ids())

#: The local machine plane (B171). Address of the model server, the model it
#: should use, the search service's address, and how long one completion may
#: take, in seconds. All optional: empty means "discover it" (`app/localplane.py`).
LOCAL_URL = "local_url"
LOCAL_MODEL = "local_model"
LOCAL_SEARCH_URL = "local_search_url"
LOCAL_TIMEOUT = "local_timeout"
LOCAL_CONTEXT_TOKENS = "local_context_tokens"
LOCAL_KEYS = (LOCAL_URL, LOCAL_MODEL, LOCAL_SEARCH_URL, LOCAL_TIMEOUT, LOCAL_CONTEXT_TOKENS)

#: The Agents screen's order, comma-separated harness ids, newest first as
#: the reader arranged them; empty means the engine's own order.
AGENT_ORDER = "agent_order"

KEYS = (HARNESS, MODEL, SEARCH, *ROLE_KEYS,
        *HARNESS_MODEL_KEYS, *HARNESS_EFFORT_KEYS, *LOCAL_KEYS, AGENT_ORDER)


def for_role(conn, role: str, override: str = "") -> str:
    """Which model this stage should use. The role's own, or the default.

    Resolved here rather than at each call site, because a stage that forgot to
    fall back would silently use whatever the environment said and the reader
    would have no way to tell which model wrote what.
    """
    if role not in modelcatalogue.ACTIVE_ROLES:
        return ""
    from app.providers import llm

    stored = read(conn)
    return llm.model_name(
        override.strip() or stored.get(role_key(role)) or stored.get(MODEL) or ""
    )


def read(conn) -> dict:
    """The three, with empty meaning "whatever the machine offers"."""
    from app.web import state

    stored = state.all_settings(conn) if conn is not None else {}
    return {key: str(stored.get(key) or "").strip() for key in KEYS}


def write(conn, values: dict) -> dict:
    from app.web import state

    wanted = {key: str(values.get(key) or "").strip() for key in KEYS if key in values}
    if wanted:
        state.put_settings(conn, wanted)
    return read(conn)


def for_harness(conn, harness_id: str, override: str = "") -> str:
    """Which model this harness should run with. The run's own, the stored
    one for this harness, or empty for the CLI's default.

    Resolved here rather than at each call site for the same reason as
    `for_role`: a caller that forgot the fallback would run whatever the
    environment said. Empty is a real answer here, not a gap — every one of
    these CLIs has a default model, and naming one the reader never chose
    would be the guess this refuses to make.
    """
    stored = read(conn)
    return override.strip() or stored.get(harness_model_key(harness_id), "") or ""


def effort_for_harness(conn, harness_id: str, override: str = "") -> str:
    """How hard this harness should think. The run's own, the stored one, or
    empty for the CLI's default.

    Empty is a real answer, exactly as it is for the model: every one of these
    CLIs has a default effort, and naming a level the reader never chose would
    bill them for a decision they did not make.
    """
    stored = read(conn)
    return override.strip() or stored.get(harness_effort_key(harness_id), "") or ""


def effective(conn, *, model: str = "", search: str = "", harness: str = "") -> dict:
    from app import keys
    from app.providers import resolve_agent
    from app.web.settings import KRIKO_HOME

    stored = read(conn)
    name = for_role(conn, "extract", model)
    provider = modelcatalogue.provider_for(name, KRIKO_HOME)
    ready = {one["id"] for one in keys.status() if one["present"]}
    searchers = keys.search_providers()
    search = search.strip() or stored[SEARCH] or next(iter(searchers), "")
    reasons = []
    unavailable = modelcatalogue._usable(provider, ready)
    if unavailable:
        reasons.append(unavailable)
    if not search:
        reasons.append("no search key — add Exa or Tavily in Settings")
    elif search not in searchers:
        reasons.append(f"selected search provider {search!r} is unavailable — add its key or change the selection")
    wanted = harness.strip() or stored[HARNESS]
    # The run's own resolution, not a copy of it: a screen that named one
    # agent while the run took another is the drift B117 fixed once already.
    selected, note = resolve_agent(wanted)
    return {
        "llm": name, "completion_provider": provider, "search": search,
        "ready": not reasons, "reason": "; ".join(reasons),
        "harness": selected.id if selected else "",
        "harness_ready": selected is not None,
        "harness_note": note if selected else (
            "no usable coding-agent CLI installed, and no API agent picked"),
    }


def paid_plane_ready(app_state_path=None, env_path=None) -> bool:
    """Whether a paid-plane run would work *with the model it would use*.

    For the doors that choose the paid plane on the reader's behalf (the
    extension, the scheduler). `keys.ready` alone counts any completion key,
    and those two questions came apart once a key could be saved for another
    use: the Mistral key an API agent needs is not a key for `gpt-4o-mini`.
    """
    from app import keys
    from app.web import state
    from app.web.settings import KRIKO_HOME

    conn = None
    try:
        conn = state.connect(app_state_path) if app_state_path else None
    except Exception:  # noqa: BLE001 — an unreadable preference is no preference
        conn = None
    try:
        provider = modelcatalogue.provider_for(for_role(conn, "extract"), KRIKO_HOME)
    finally:
        if conn is not None:
            conn.close()
    return keys.ready(env_path, provider=provider)


def api_agent_rows(conn) -> tuple[list[dict], list[dict]]:
    """The API agents, shaped like the CLI rows: `(ready, missing)`.

    Ready means its key is saved, and a ready row is one the reader can
    *pick*; nothing runs on it until they do (`resolve_agent`). The row says
    what it bills, because unlike a CLI's subscription this one is metered.
    """
    from app import keys
    from app.providers import apiagent
    from app.web.settings import KRIKO_HOME

    ready = apiagent.available()
    def bills(one) -> str:
        return f"your {keys.BY_ID[one.key].label} key, per token and per search"

    rows = [
        {
            "id": one.id, "label": one.label, "path": one.host, "command": "",
            "needs_account": bills(one), "cost_basis": "per_token",
            "llm": for_harness(conn, one.id),
            "llms": apiagent.models_for(one, KRIKO_HOME), "llms_note": "",
            "llm_hint": one.model_hint, "llm_selectable": True,
            "effort": "", "efforts": [], "effort_hint": "",
        }
        for one in ready
    ]
    missing = [
        {
            "id": one.id, "label": one.label, "command": "", "download_url": one.key_url,
            "install_hint": one.install_hint,
            "needs_account": "Bills " + bills(one),
        }
        for one in apiagent.KNOWN
        if one not in ready
    ]
    return rows, missing


def choices(conn, app_state_path=None, *, fresh: bool = False) -> dict:
    """What could be chosen here, and what is chosen now.

    Everything is discovered rather than listed: the harnesses from what is
    installed on this machine, the search providers from which keys exist, the
    models from the completion provider's own catalogue where it has one. A
    hardcoded model list would be stale within a release and wrong for anyone
    pointing `LLM_BASE_URL` at their own gateway.
    """
    from app import keys, modeldiscovery
    from app.providers import harness, llm
    from app.web.settings import KRIKO_HOME

    chosen = read(conn)
    if fresh:
        # "Check again" after installing a CLI must see it at once.
        harness.forget_located()
    found = harness.available()
    lists = harness.models_for_each(found, fresh=fresh)
    installed = [
        {
            "id": one.id, "label": one.label, "path": harness.locate(one),
            "llm": for_harness(conn, one.id),
            "llms": lists.get(one.id, []),
            "llms_note": harness.models_note(one, lists.get(one.id, [])),
            "llm_hint": one.model_hint,
            # `model_env` counts. Mistral Vibe has no `--model` — its switch is
            # an environment variable its own config layer reads — so keying
            # this on the flag alone hid the picker for the one harness the
            # reader added specifically to stop spending Claude tokens.
            "llm_selectable": bool(one.model_flag or one.model_env),
            # The second dial. `efforts_for` probes this machine's `--help`,
            # so a CLI that has no such flag reports `[]` and the screen shows
            # no control rather than one whose every choice fails.
            "effort": effort_for_harness(conn, one.id),
            "efforts": harness.efforts_for(one),
            "effort_hint": one.effort_hint,
        }
        for one in found
    ]
    unusable = [
        {"id": one.id, "label": one.label, "why": one.unusable}
        for one in harness.found_but_unusable()
    ]
    have = {one.id for one in found}
    missing = [
        {
            "id": one.id, "label": one.label, "command": one.executable,
            "download_url": one.download_url, "install_hint": one.install_hint,
            "needs_account": one.needs_account,
        }
        for one in harness.KNOWN
        if one.id not in have and not one.unusable
    ]
    api_rows, api_missing = api_agent_rows(conn)
    return {
        "chosen": chosen,
        "effective": effective(conn),
        "harnesses": installed + api_rows,
        "unusable": unusable,
        "missing": missing + api_missing,
        "dirs_env": harness.DIRS_ENV,
        "search_providers": [
            {
                "id": one,
                "label": keys.BY_ID[one].label,
                "ready": one in keys.search_providers(),
            }
            for one in keys.SEARCH_PROVIDERS
        ],
        "models": {
            "current": chosen[MODEL] or llm.model_name(),
            "default": llm.DEFAULT_MODEL,
            # Still free text, and now also a list. The two are not in tension:
            # the endpoint a reader points this at may be a gateway or
            # something local, so a drop-down alone would make those
            # unreachable — but "type a model name" as the *only* affordance
            # was a choice offered with none of what you need to make it.
            "note": "Any model name your completion endpoint accepts.",
            "offered": modelcatalogue.offered(
                KRIKO_HOME,
                ready={one["id"] for one in keys.status() if one["present"]},
                # What each keyed provider lists today, beside the catalogue.
                # Never waited on here unless `fresh`: see modeldiscovery.
                discovered=modeldiscovery.cached(fresh=fresh),
            ),
            # Where the reader edits prices. Named rather than described,
            # because "editable config" is only true if they can find it.
            "catalogue": str(modelcatalogue.catalogue_path(KRIKO_HOME)),
        },
        # Per stage of a run, each falling back to the one above. Sent with the
        # notes so a client never has to write its own description of what a
        # stage does and then drift from it.
        "roles": [
            {
                "id": role,
                "note": modelcatalogue.ROLE_NOTES.get(role, ""),
                "chosen": chosen.get(role_key(role), ""),
                "active": role in modelcatalogue.ACTIVE_ROLES,
                "effective": for_role(conn, role),
                "inactive_reason": "" if role in modelcatalogue.ACTIVE_ROLES else "inactive — this stage makes no separate paid completion call",
            }
            for role in modelcatalogue.ROLES
        ],
    }

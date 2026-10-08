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
#: The pick that names the model on this machine rather than an agent: the
#: Agents tab's Local model row. Stored in `HARNESS` like any pick, so the
#: reader's choice is one setting, but it is never an agent id, and a door
#: that checks a pick against the installed CLIs must let it through.
LOCAL_PICK = "local"
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
    if harness_id == LOCAL_PICK:
        # The local row's model is the Local LLM page's own setting: one
        # choice, whichever screen it was made on.
        return LOCAL_MODEL
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
LOCAL_KEYS = (LOCAL_URL, LOCAL_MODEL, LOCAL_SEARCH_URL, LOCAL_TIMEOUT)

#: What every agent run reads, set once on the Agents tab: how many sources
#: at most (empty or 0 leaves it to the run), and which kinds of source to go
#: to first. The reader's words: "options for research: forum/review/and such
#: sources for options and source counts for agents".
RESEARCH_SOURCES = "research_sources"
RESEARCH_KINDS = "research_source_kinds"
RESEARCH_KEYS = (RESEARCH_SOURCES, RESEARCH_KINDS)
#: The kinds, as the prompt names them. A small closed vocabulary of where
#: evidence comes from, true of any category (CLAUDE.md's exception), never a
#: list of products: ordered as the Agents tab shows them.
SOURCE_KINDS = {
    "forums": "owner forums and discussion threads",
    "reviews": "professional reviews and long-term tests",
    "recalls": "recalls, service bulletins and official notices",
    "manufacturer": "the manufacturer's own documentation",
    "video": "video reviews and teardowns",
    "news": "news reports",
}
#: The ceiling the Agents tab offers; a run's own `max_documents` may not
#: exceed the schema's 50 either.
MAX_RESEARCH_SOURCES = 50


def research_options(conn, *, sources: int = 0, kinds: list[str] | None = None) -> dict:
    """`{"sources": n, "kinds": [...]}`: the run's own, else the stored.

    Unknown kinds are dropped rather than refused, so a request from an older
    client still runs.
    """
    stored = read(conn) if conn is not None else dict.fromkeys(KEYS, "")
    count = int(sources or 0)
    if count <= 0:
        try:
            count = int(stored.get(RESEARCH_SOURCES) or 0)
        except ValueError:
            count = 0
    wanted = kinds if kinds else [
        one.strip() for one in (stored.get(RESEARCH_KINDS) or "").split(",")]
    return {
        "sources": max(0, min(count, MAX_RESEARCH_SOURCES)),
        "kinds": [one for one in SOURCE_KINDS if one in set(wanted)],
    }


#: How many agent runs the job runner may have going at once (#133). The
#: reader's words: "concurrent agent runs, with options in settings". Unset
#: means one, which is how every run went before the choice existed.
RUN_CONCURRENCY = "run_concurrency"
#: The ceiling Settings offers. Each run is a CLI process or a model's
#: attention plus its own fetches; past four the machine, the provider's rate
#: limit and the reader's bill all say no before this number would.
MAX_RUN_CONCURRENCY = 4


def run_concurrency(conn) -> int:
    """How many runs at once, clamped to 1..`MAX_RUN_CONCURRENCY`.

    Read through `state.all_settings` rather than `read`, because Settings
    stores it as a number and `read` would hand back a string. Either form
    parses; anything that does not is one, never an error, since a job must
    not fail to start over a preference.
    """
    from app.web import state

    stored = state.all_settings(conn).get(RUN_CONCURRENCY) if conn is not None else None
    try:
        wanted = int(str(stored).strip() or 1) if stored is not None else 1
    except ValueError:
        wanted = 1
    return max(1, min(wanted, MAX_RUN_CONCURRENCY))


KEYS = (HARNESS, MODEL, SEARCH, *ROLE_KEYS,
        *HARNESS_MODEL_KEYS, *HARNESS_EFFORT_KEYS, *LOCAL_KEYS, *RESEARCH_KEYS,
        RUN_CONCURRENCY)


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


def local_agent_rows(conn) -> tuple[list[dict], list[dict], list[dict]]:
    """The model on this machine as one more agent row: `(ready, unusable, missing)`.

    The reader's words: "Local agent cannot be chosen in agents tab". It ran
    every check a reader with no agent started, and still had no row of its
    own, so it could not be picked over an installed CLI. Shaped like the CLI
    rows so every screen that lists agents lists it too; its models are the
    ones the server says it holds, and picking one writes `LOCAL_MODEL`.
    """
    from app import localplane

    try:
        mine = read(conn)
        plane = localplane.resolve(None, url=mine[LOCAL_URL], model=mine[LOCAL_MODEL],
                                   with_search=False)
    except Exception as exc:  # noqa: BLE001 - a probe never breaks the agents list
        return [], [], [{"id": LOCAL_PICK, "label": "Local model", "command": "",
                         "download_url": "", "install_hint": str(exc),
                         "needs_account": ""}]
    label = "Local model"
    if plane["ready"]:
        return [{
            "id": LOCAL_PICK, "label": label, "path": plane["url"], "command": "",
            "needs_account": "", "cost_basis": "self_hosted", "local": True,
            "llm": plane["model"], "llms": list(plane["models"]),
            "llms_note": f"served by {plane['name']} at {plane['url']}",
            "llm_hint": "", "llm_selectable": True,
            "effort": "", "efforts": [], "effort_hint": "",
        }], [], []
    if plane["url"]:
        return [], [{"id": LOCAL_PICK, "label": label, "why": plane["reason"]}], []
    return [], [], [{"id": LOCAL_PICK, "label": label, "command": "",
                     "download_url": "https://ollama.com/download",
                     "install_hint": plane["reason"], "needs_account": ""}]


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
    local_ready, local_unusable, local_missing = local_agent_rows(conn)
    installed += local_ready
    unusable += local_unusable
    missing += local_missing
    return {
        "chosen": chosen,
        "effective": effective(conn),
        "harnesses": installed + api_rows,
        "unusable": unusable,
        "missing": missing + api_missing,
        "dirs_env": harness.DIRS_ENV,
        "source_kinds": [{"id": one, "label": label}
                         for one, label in SOURCE_KINDS.items()],
        "research": research_options(conn),
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

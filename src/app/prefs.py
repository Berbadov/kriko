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

KEYS = (HARNESS, MODEL, SEARCH, *ROLE_KEYS)


def for_role(conn, role: str) -> str:
    """Which model this stage should use. The role's own, or the default.

    Resolved here rather than at each call site, because a stage that forgot to
    fall back would silently use whatever the environment said and the reader
    would have no way to tell which model wrote what.
    """
    stored = read(conn)
    return stored.get(role_key(role)) or stored.get(MODEL) or ""


def read(conn) -> dict:
    """The three, with empty meaning "whatever the machine offers"."""
    from app.web import state

    stored = state.all_settings(conn) if conn is not None else {}
    return {key: str(stored.get(key) or "") for key in KEYS}


def write(conn, values: dict) -> dict:
    from app.web import state

    wanted = {key: str(values.get(key) or "") for key in KEYS if key in values}
    if wanted:
        state.put_settings(conn, wanted)
    return read(conn)


def choices(conn, app_state_path=None) -> dict:
    """What could be chosen here, and what is chosen now.

    Everything is discovered rather than listed: the harnesses from what is
    installed on this machine, the search providers from which keys exist, the
    models from the completion provider's own catalogue where it has one. A
    hardcoded model list would be stale within a release and wrong for anyone
    pointing `LLM_BASE_URL` at their own gateway.
    """
    from app import keys
    from app.providers import harness, llm
    from app.web.settings import KRIKO_HOME

    chosen = read(conn)
    installed = [
        {"id": one.id, "label": one.label, "path": harness.locate(one)}
        for one in harness.available()
    ]
    unusable = [
        {"id": one.id, "label": one.label, "why": one.unusable}
        for one in harness.found_but_unusable()
    ]
    return {
        "chosen": chosen,
        "harnesses": installed,
        "unusable": unusable,
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
            }
            for role in modelcatalogue.ROLES
        ],
    }

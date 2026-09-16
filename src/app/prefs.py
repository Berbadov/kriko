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

#: The settings keys. Named once, here, because both the router that writes
#: them and the providers that read them would otherwise spell them twice.
HARNESS = "preferred_harness"
MODEL = "llm_model"
SEARCH = "search_provider"

KEYS = (HARNESS, MODEL, SEARCH)


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
            # Free text on purpose. The endpoint a reader points this at may be
            # OpenAI, a gateway, or something local, and a drop-down built from
            # one vendor's list would make the other two unreachable.
            "note": "Any model name your completion endpoint accepts.",
        },
    }

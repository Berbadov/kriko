"""The local machine plane: is it ready, where, and with which model (B171).

One answer, asked by everything that needs it: the planes card, Settings, the
extension door, `default_backend`, and the run itself. A screen that said
"ready" while the run found no model is the drift this file exists to prevent,
so the run resolves its address and model through `resolve` too.

Ready means a model server answers *and* serves a model. The server's own list
is the only source of model names; nothing here knows what a good model is. The
search half never blocks readiness: OpenSERP when it answers, otherwise Exa's
free hosted search (decision D3), so a local model alone is enough to run.
"""

from app import prefs
from app.providers import local_discovery as discovery
from app.providers.local_inference import DEFAULT_TIMEOUT, runtime_incomplete

#: A server lists every model it holds, including ones that only embed text.
#: Such a model cannot answer a prompt, so it is never picked by default. The
#: substring is a closed engineering convention (every such model says it).
_NOT_A_CHAT_MODEL = "embed"

#: The window asked of a runtime that takes one, in tokens. Eight thousand
#: holds five pages beside the brief and the reply; the key-value cache it
#: costs is small beside the weights, so it fits the machines a small model
#: is chosen for.
DEFAULT_CONTEXT = 8192


def stored(app_state_path=None) -> dict:
    """The four local preferences, empty where the reader set none."""
    empty = dict.fromkeys(prefs.LOCAL_KEYS, "")
    if app_state_path is None:
        return empty
    from app.web import state

    try:
        conn = state.connect(app_state_path)
    except Exception:  # noqa: BLE001 - a preference is never why a run fails
        return empty
    try:
        return {key: prefs.read(conn).get(key, "") for key in prefs.LOCAL_KEYS}
    finally:
        conn.close()


def timeout_of(value: str) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return seconds if seconds > 0 else DEFAULT_TIMEOUT


def _pick(models: list[str], wanted: str) -> str:
    if wanted in models:
        return wanted
    chat = [one for one in models if _NOT_A_CHAT_MODEL not in one.casefold()]
    return (chat or models or [""])[0]


def resolve(app_state_path=None, *, url: str = "", model: str = "",
            search_url: str = "", with_search: bool = True) -> dict:
    """Probe this machine and say what a local run would use.

    `url`, `model` and `search_url` are a run's own choices and win over the
    stored ones, which win over discovery. A `model` that the server does not
    list is not used, and the reason says what it lists instead: a name from
    another provider's namespace must not reach a server that would 404 it.
    """
    mine = stored(app_state_path)
    want_url = url.strip() or mine[prefs.LOCAL_URL]
    want_model = model.strip() or mine[prefs.LOCAL_MODEL]
    want_search = search_url.strip() or mine[prefs.LOCAL_SEARCH_URL]
    # Side by side: each probe can cost its whole timeout when nothing
    # listens, and the screen waits for the slowest rather than the sum.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        found = pool.submit(discovery.discover, want_url)
        asked = pool.submit(discovery.search_answers, want_search) if with_search else None
        servers = found.result()
        searching = asked.result() if asked is not None else False

    chosen: dict | None
    if want_url:
        chosen = servers[0]
    else:
        chosen = None
        for wanted in ("models", "up"):
            chosen = next(iter(s for s in servers if s[wanted]), None)
            if chosen:
                break

    search = {
        "search_kind": "openserp" if searching else "exa",
        "search_url": discovery.base_of(want_search) or discovery.SEARCH_DEFAULT_URL,
        "search_label": ("the search service on this machine" if searching
                         else "Exa's free hosted search"),
    }
    out = {
        "servers": servers,
        "url": chosen["url"] if chosen else "",
        "name": chosen["name"] if chosen else "",
        "models": chosen["models"] if chosen else [],
        "model": "",
        "timeout": timeout_of(mine[prefs.LOCAL_TIMEOUT]),
        "runtime_options": {},
        "ready": False,
        "reason": "",
        "line": "",
        **search,
    }

    if chosen is None or not chosen["up"]:
        looked = ", ".join(f"{s['name']} at {s['url']}" for s in servers)
        out["reason"] = (
            f"Nothing answers at {want_url}. Start that server or correct the "
            "address in Settings, Local machine." if want_url else
            f"No local model server is running (looked for {looked}). Start "
            "Ollama, LM Studio or llama-server, then check again.")
    elif not chosen["models"]:
        out["reason"] = (
            f"{chosen['name']} is running at {chosen['url']} but no model is "
            "downloaded. Download one in that app, then check again.")
    elif want_model and want_model not in chosen["models"]:
        out["reason"] = (
            f"{chosen['name']} at {chosen['url']} has no model named "
            f"{want_model!r}. It has: {', '.join(chosen['models'])}. Pick one "
            "in Settings, Local machine.")
    else:
        out["model"] = _pick(chosen["models"], want_model)
        out["ready"] = True
    # A server that lists models and answers /api/version can still have no
    # runner to start one with (an install that was interrupted). A call that
    # found that out has said so; until the install is repaired the plane is
    # not ready, and the reason says what to press instead of "Ready".
    broken = runtime_incomplete(out["url"]) if chosen else ""
    out["runtime_incomplete"] = bool(broken)
    if broken:
        out["ready"] = False
        out["reason"] = broken
    from app.localruntime import inspect, options
    out["runtime"] = inspect(out["url"], out["name"], out["model"], mine)
    if out["runtime"]["runtime"] == "Ollama":
        out["name"] = "Ollama"
        if chosen:
            chosen["name"] = "Ollama"
    # Ollama loads a model at 4096 tokens unless told otherwise, which left a
    # quick look room for two or three pages and cut the rest from the front.
    # The reader's own context setting still wins; this is only the default.
    out["runtime_options"] = (
        {"num_ctx": DEFAULT_CONTEXT, **options(mine)} if out["runtime"]["supported"] else {})
    if not with_search:
        # Not asked, so not claimed: a readiness check that skipped the
        # search probe must not say which search is in use.
        out["search_kind"] = out["search_label"] = ""
    out["line"] = (
        f"Ready: {out['model']} on {out['name']} at {out['url']}"
        + (f"; search through {search['search_label']}." if with_search else ".")
        if out["ready"] else out["reason"])
    # The keys the planes card has always carried.
    out["inference_url"] = out["url"]
    out["serp_url"] = search["search_url"]
    return out


def is_ready(app_state_path=None) -> bool:
    try:
        return bool(resolve(app_state_path, with_search=False)["ready"])
    except Exception:  # noqa: BLE001 - a gate answers no rather than crashing
        return False


def reader_chose_an_agent(app_state_path=None) -> bool:
    """Whether the reader picked a coding or API agent in Settings.

    A pick is a choice of plane: the local plane goes first only for a reader
    who has not said otherwise (B172).
    """
    if app_state_path is None:
        return False
    from app.web import state

    try:
        conn = state.connect(app_state_path)
    except Exception:  # noqa: BLE001
        return False
    try:
        # Picking the Local model row is a pick of the local plane, not an
        # agent, so it keeps the local plane first.
        return prefs.read(conn).get(prefs.HARNESS) not in ("", prefs.LOCAL_PICK)
    finally:
        conn.close()

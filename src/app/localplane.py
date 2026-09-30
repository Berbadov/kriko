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
from app.providers.local_inference import DEFAULT_TIMEOUT

#: A server lists every model it holds, including ones that only embed text.
#: Such a model cannot answer a prompt, so it is never picked by default. The
#: substring is a closed engineering convention (every such model says it).
_NOT_A_CHAT_MODEL = "embed"


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
        return bool(prefs.read(conn).get(prefs.HARNESS))
    finally:
        conn.close()
